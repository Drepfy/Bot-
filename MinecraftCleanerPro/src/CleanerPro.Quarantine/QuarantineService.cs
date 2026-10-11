using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Core.Safety;
using CleanerPro.Infrastructure;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace CleanerPro.Quarantine;

/// <summary>
/// Moves approved files into quarantine with copy → verify → delete semantics and a journal, so an
/// interrupted operation never loses data. Every step is validated by <see cref="PathSafetyPolicy"/>.
/// The original is removed only after the quarantined copy has been verified by SHA-256.
/// </summary>
public sealed class QuarantineService
{
    private const string ManifestName = "manifest.json";
    private const string PayloadName = "payload.bin";
    private const int MaxDirectoryFiles = 500;
    private const long MaxDirectoryBytes = 512L * 1024 * 1024;

    private readonly Func<string> _root;
    private readonly PathSafetyPolicy _policy;
    private readonly OperationLog _operations;
    private readonly ILogger _logger;
    private readonly TimeProvider _time;
    private readonly Func<string, Stream> _createPayloadStream;
    private readonly byte[] _tokenSecret = RandomNumberGenerator.GetBytes(32);

    public QuarantineService(Func<string> quarantineDirectory, PathSafetyPolicy policy, OperationLog operations,
        ILogger<QuarantineService>? logger = null, TimeProvider? time = null, Func<string, Stream>? createPayloadStream = null)
    {
        _root = quarantineDirectory;
        _policy = policy;
        _operations = operations;
        _logger = logger ?? NullLogger<QuarantineService>.Instance;
        _time = time ?? TimeProvider.System;
        _createPayloadStream = createPayloadStream ?? (path => new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 81920));
    }

    public string RootDirectory => _root();

    private string EntriesDirectory => Path.Combine(_root(), "entries");

    private string JournalDirectory => Path.Combine(_root(), "journal");

    // ------------------------------------------------------------------ quarantine

    public QuarantineResult Quarantine(QuarantineRequest request, CancellationToken cancellationToken = default)
    {
        var validation = _policy.ValidateCleanupTarget(request.Path, request.ApprovedRoots, PathTargetKind.File);
        if (!validation.IsAllowed)
        {
            return Record(Blocked(request.Path, validation), request);
        }

        var path = validation.NormalizedPath!;
        var info = new FileInfo(path);
        if (request.ExpectedSize is { } expectedSize && info.Length != expectedSize)
        {
            return Record(Fail(path, "The file has changed since the scan (different size). Scan again before cleaning it."), request);
        }

        string currentHash;
        try
        {
            currentHash = FileHasher.Compute(path, includeSha1: false, cancellationToken: cancellationToken).Sha256;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Record(Fail(path, $"The file could not be read ({ex.Message}). If Minecraft or a launcher is running, close it and try again."), request);
        }

        if (request.ExpectedSha256 is { } expected && !string.Equals(expected, currentHash, StringComparison.OrdinalIgnoreCase))
        {
            return Record(Fail(path, "The file has changed since the scan (different SHA-256). Scan again before cleaning it."), request);
        }

        var id = Guid.NewGuid().ToString("N");
        var entryDirectory = Path.Combine(EntriesDirectory, id);
        var payloadPath = Path.Combine(entryDirectory, PayloadName);
        var temporaryPayload = payloadPath + ".tmp";
        var key = RandomNumberGenerator.GetBytes(32);
        var originalAttributes = info.Attributes;
        var creation = SafeTime(() => info.CreationTimeUtc);
        var lastWrite = SafeTime(() => info.LastWriteTimeUtc);

        try
        {
            Directory.CreateDirectory(entryDirectory);
            Directory.CreateDirectory(JournalDirectory);
            WriteJournal(new JournalRecord(id, path, currentHash, JournalStage.Started, _time.GetUtcNow()));

            // 1. Copy the original into an encoded payload while hashing exactly what was read.
            string copiedHash;
            string payloadHash;
            using (var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 81920, FileOptions.SequentialScan))
            using (var target = _createPayloadStream(temporaryPayload))
            {
                (copiedHash, payloadHash) = CopyEncoded(source, target, key, cancellationToken);
                target.Flush();
                if (target is FileStream fileStream)
                {
                    fileStream.Flush(flushToDisk: true);
                }
            }

            if (!string.Equals(copiedHash, currentHash, StringComparison.Ordinal))
            {
                RollBack(entryDirectory, id);
                return Record(Fail(path, "The file changed while it was being copied. Nothing was removed; scan again."), request);
            }

            File.Move(temporaryPayload, payloadPath);

            // 2. Verify the stored copy independently before touching the original.
            if (!string.Equals(DecodeHash(payloadPath, key, cancellationToken), currentHash, StringComparison.Ordinal))
            {
                RollBack(entryDirectory, id);
                return Record(Fail(path, "The quarantined copy could not be verified. Nothing was removed."), request);
            }

            var entry = new QuarantineEntry
            {
                Id = id,
                OriginalPath = path,
                OriginalName = Path.GetFileName(path),
                Size = info.Length,
                Sha256 = currentHash,
                PayloadSha256 = payloadHash,
                EncodingKey = Convert.ToBase64String(key),
                OriginalAttributes = (int)originalAttributes,
                CreationTimeUtc = creation,
                LastWriteTimeUtc = lastWrite,
                QuarantinedAtUtc = _time.GetUtcNow(),
                ApprovedRoots = request.ApprovedRoots.ToList(),
                FindingId = request.FindingId,
                SessionId = request.SessionId,
                RuleIds = request.RuleIds,
                Classification = request.Classification,
                Family = request.Family,
                Status = QuarantineEntryStatus.Pending,
            };
            SaveManifest(entry);
            WriteJournal(new JournalRecord(id, path, currentHash, JournalStage.PayloadVerified, _time.GetUtcNow()));

            // 3. Re-validate (the path could have been swapped for a link meanwhile) and remove the original.
            var recheck = _policy.ValidateCleanupTarget(path, request.ApprovedRoots, PathTargetKind.File);
            info.Refresh();
            if (!recheck.IsAllowed || !info.Exists || info.Length != entry.Size || SafeTime(() => info.LastWriteTimeUtc) != lastWrite)
            {
                RollBack(entryDirectory, id);
                return Record(Fail(path, recheck.IsAllowed ? "The file changed during quarantine. Nothing was removed." : recheck.Reason ?? "Blocked by the safety policy."), request);
            }

            try
            {
                if (info.Attributes.HasFlag(FileAttributes.ReadOnly))
                {
                    File.SetAttributes(path, info.Attributes & ~FileAttributes.ReadOnly);
                }

                File.Delete(path);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                TryRestoreAttributes(path, originalAttributes);
                RollBack(entryDirectory, id);
                return Record(Fail(path, $"The original could not be removed ({ex.Message}). It may be in use: close Minecraft and launchers, then try again. Nothing was changed."), request);
            }

            if (File.Exists(path))
            {
                RollBack(entryDirectory, id);
                return Record(Fail(path, "The original file still exists after deletion (it may be protected). Nothing was quarantined."), request);
            }

            WriteJournal(new JournalRecord(id, path, currentHash, JournalStage.OriginalDeleted, _time.GetUtcNow()));
            entry = entry with { Status = QuarantineEntryStatus.Quarantined };
            SaveManifest(entry);
            DeleteJournal(id);

            _logger.LogInformation("Quarantined {Path} as {Id}", path, id);
            return Record(new QuarantineResult
            {
                Succeeded = true,
                Message = "Quarantined and verified. The file can be restored at any time from the Quarantine page.",
                Path = path,
                Entry = entry,
                OriginalPreserved = false,
            }, request);
        }
        catch (OperationCanceledException)
        {
            RollBack(entryDirectory, id);
            return Record(Fail(path, "Cancelled. Nothing was removed."), request);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // Includes "disk full": the original is untouched because it is only deleted after verification.
            RollBack(entryDirectory, id);
            _logger.LogWarning(ex, "Quarantine of {Path} failed", path);
            return Record(Fail(path, $"Quarantine failed ({ex.Message}). The original file was not removed."), request);
        }
    }

    /// <summary>
    /// Quarantines every file inside a flagged directory individually (bounded), then removes the
    /// directories only if they are empty. Directories containing links are refused as a whole.
    /// </summary>
    public IReadOnlyList<QuarantineResult> QuarantineDirectory(QuarantineRequest request, CancellationToken cancellationToken = default)
    {
        var validation = _policy.ValidateCleanupTarget(request.Path, request.ApprovedRoots, PathTargetKind.Directory);
        if (!validation.IsAllowed)
        {
            return [Record(Blocked(request.Path, validation), request)];
        }

        var directory = validation.NormalizedPath!;
        var files = new List<string>();
        var directories = new List<string>();
        long total = 0;
        try
        {
            foreach (var entry in new DirectoryInfo(directory).EnumerateFileSystemInfos("*", new EnumerationOptions { RecurseSubdirectories = true, AttributesToSkip = 0, IgnoreInaccessible = false }))
            {
                if (entry.Attributes.HasFlag(FileAttributes.ReparsePoint) || entry.LinkTarget is not null)
                {
                    return [Record(Fail(directory, $"'{entry.FullName}' is a link or junction, so the folder was not cleaned. Remove the link manually first."), request)];
                }

                if (entry is DirectoryInfo)
                {
                    directories.Add(entry.FullName);
                    continue;
                }

                files.Add(entry.FullName);
                total += ((FileInfo)entry).Length;
                if (files.Count > MaxDirectoryFiles || total > MaxDirectoryBytes)
                {
                    return [Record(Fail(directory, $"The folder is larger than the safety limit ({MaxDirectoryFiles} files / {MaxDirectoryBytes / (1024 * 1024)} MB) for folder cleanup. Review it manually."), request)];
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return [Record(Fail(directory, $"The folder could not be listed ({ex.Message})."), request)];
        }

        var results = new List<QuarantineResult>();
        foreach (var file in files)
        {
            cancellationToken.ThrowIfCancellationRequested();
            results.Add(Quarantine(request with { Path = file, ExpectedSha256 = null, ExpectedSize = null }, cancellationToken));
        }

        if (results.All(r => r.Succeeded))
        {
            // Remove now-empty folders bottom-up; never recursive.
            foreach (var sub in directories.OrderByDescending(d => d.Length).Append(directory))
            {
                try
                {
                    if (!Directory.EnumerateFileSystemEntries(sub).Any())
                    {
                        Directory.Delete(sub, recursive: false);
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    _logger.LogInformation("Folder {Path} left in place: {Message}", sub, ex.Message);
                }
            }
        }

        return results;
    }

    // ------------------------------------------------------------------ restore

    public RestoreResult Restore(RestoreRequest request, CancellationToken cancellationToken = default)
    {
        var entry = LoadEntry(request.EntryId);
        if (entry is null || entry.Status != QuarantineEntryStatus.Quarantined)
        {
            return RecordRestore(new RestoreResult { Succeeded = false, Message = "The quarantine item does not exist or was already restored." }, request.EntryId, entry);
        }

        var integrity = VerifyIntegrity(entry, cancellationToken);
        if (integrity != IntegrityStatus.Verified)
        {
            return RecordRestore(new RestoreResult { Succeeded = false, Message = $"The quarantined copy failed its integrity check ({integrity}). It was not restored." }, entry.Id, entry);
        }

        string destination;
        IReadOnlyList<string> roots;
        switch (request.Mode)
        {
            case RestoreMode.OriginalLocation:
                destination = entry.OriginalPath;
                roots = entry.ApprovedRoots;
                break;
            case RestoreMode.OriginalLocationWithNewName:
                destination = UniqueName(entry.OriginalPath);
                roots = entry.ApprovedRoots;
                break;
            case RestoreMode.AlternateDirectory when request.AlternateDirectory is { } alternate:
                var check = _policy.ValidateScanRoot(alternate);
                if (!check.IsAllowed)
                {
                    return RecordRestore(new RestoreResult { Succeeded = false, Message = check.Reason ?? "The chosen folder is not allowed." }, entry.Id, entry);
                }

                destination = UniqueName(Path.Combine(check.NormalizedPath!, entry.OriginalName));
                roots = [check.NormalizedPath!];
                break;
            default:
                return RecordRestore(new RestoreResult { Succeeded = false, Message = "Choose a folder to restore to." }, entry.Id, entry);
        }

        var validation = _policy.ValidateRestoreDestination(destination, roots);
        if (!validation.IsAllowed)
        {
            return RecordRestore(new RestoreResult { Succeeded = false, Message = $"Restore blocked: {validation.Reason}" }, entry.Id, entry);
        }

        destination = validation.NormalizedPath!;
        if (File.Exists(destination) || Directory.Exists(destination))
        {
            return new RestoreResult
            {
                Succeeded = false,
                Conflict = true,
                ConflictPath = destination,
                Message = "Another file already exists at the original location. Nothing was changed. Choose to restore with a new name or to another folder.",
            };
        }

        var parent = Path.GetDirectoryName(destination)!;
        var temporary = Path.Combine(parent, $".{Path.GetFileName(destination)}.restore-{entry.Id[..8]}.tmp");
        try
        {
            Directory.CreateDirectory(parent);
            var key = Convert.FromBase64String(entry.EncodingKey);
            string restoredHash;
            using (var source = File.OpenRead(Path.Combine(EntriesDirectory, entry.Id, PayloadName)))
            using (var target = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                (_, restoredHash) = CopyEncoded(source, target, key, cancellationToken, hashOutput: true);
                target.Flush(flushToDisk: true);
            }

            if (!string.Equals(restoredHash, entry.Sha256, StringComparison.Ordinal))
            {
                AtomicFile.TryDelete(temporary);
                return RecordRestore(new RestoreResult { Succeeded = false, Message = "The restored data did not match the original hash. Nothing was restored." }, entry.Id, entry);
            }

            File.Move(temporary, destination, overwrite: false);
            TrySetTimes(destination, entry);
            TryRestoreAttributes(destination, (FileAttributes)entry.OriginalAttributes);

            var restored = entry with { Status = QuarantineEntryStatus.Restored, RestoredAtUtc = _time.GetUtcNow(), RestoredTo = destination };
            SaveManifest(restored);
            AtomicFile.TryDelete(Path.Combine(EntriesDirectory, entry.Id, PayloadName));
            _logger.LogInformation("Restored {Id} to {Path}", entry.Id, destination);
            return RecordRestore(new RestoreResult { Succeeded = true, Message = $"Restored and verified at {destination}.", RestoredPath = destination }, entry.Id, restored);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or OperationCanceledException)
        {
            AtomicFile.TryDelete(temporary);
            if (File.Exists(destination) && ex is IOException && !File.Exists(temporary))
            {
                // File.Move refused because something appeared at the destination meanwhile.
                return new RestoreResult { Succeeded = false, Conflict = true, ConflictPath = destination, Message = "A file appeared at the destination during restore. Nothing was overwritten." };
            }

            return RecordRestore(new RestoreResult { Succeeded = false, Message = $"Restore failed ({ex.Message}). The quarantined copy is unchanged." }, entry.Id, entry);
        }
    }

    // ------------------------------------------------------------------ permanent deletion

    /// <summary>Lists the exact items that would be deleted and issues a short-lived confirmation token for that set.</summary>
    public DeletionPlan PrepareDeletion(IEnumerable<string> entryIds)
    {
        var targets = new List<DeletionTarget>();
        foreach (var id in entryIds.Distinct(StringComparer.Ordinal))
        {
            var entry = LoadEntry(id);
            if (entry is { Status: QuarantineEntryStatus.Quarantined })
            {
                targets.Add(new DeletionTarget(entry.Id, entry.OriginalPath, entry.Size, entry.Sha256, entry.QuarantinedAtUtc));
            }
        }

        var expires = _time.GetUtcNow().AddMinutes(10);
        return new DeletionPlan(targets, ComputeToken(targets.Select(t => t.EntryId), expires), expires);
    }

    /// <summary>Deletes exactly the items in the plan, and only when the confirmation token matches.</summary>
    public DeletionResult ExecuteDeletion(DeletionPlan plan, string confirmationToken)
    {
        if (plan.Targets.Count == 0)
        {
            return new DeletionResult(false, "Nothing was selected.", []);
        }

        var expected = ComputeToken(plan.Targets.Select(t => t.EntryId), plan.ExpiresAtUtc);
        if (!CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(expected), Encoding.ASCII.GetBytes(confirmationToken ?? string.Empty)) ||
            !string.Equals(expected, plan.Token, StringComparison.Ordinal))
        {
            return new DeletionResult(false, "The deletion was not confirmed for exactly these items. Nothing was deleted.", []);
        }

        if (_time.GetUtcNow() > plan.ExpiresAtUtc)
        {
            return new DeletionResult(false, "The confirmation expired. Select the items and confirm again. Nothing was deleted.", []);
        }

        var results = new List<DeletionItemResult>();
        foreach (var target in plan.Targets)
        {
            var entryDirectory = Path.Combine(EntriesDirectory, target.EntryId);
            if (!PathKey.IsSameOrWithin(Path.GetFullPath(entryDirectory), Path.GetFullPath(EntriesDirectory)) || target.EntryId.Any(c => !char.IsAsciiHexDigit(c)))
            {
                results.Add(new DeletionItemResult(target.EntryId, false, "Invalid quarantine item."));
                continue;
            }

            try
            {
                AtomicFile.TryDelete(Path.Combine(entryDirectory, PayloadName));
                if (File.Exists(Path.Combine(entryDirectory, PayloadName)))
                {
                    throw new IOException("The payload could not be deleted.");
                }

                File.Delete(Path.Combine(entryDirectory, ManifestName));
                Directory.Delete(entryDirectory, recursive: false);
                results.Add(new DeletionItemResult(target.EntryId, true, $"Permanently deleted the quarantined copy of {target.OriginalPath}."));
                _operations.Append(new OperationRecord
                {
                    Id = Guid.NewGuid().ToString("N"), Type = OperationType.PermanentDelete, TimestampUtc = _time.GetUtcNow(), Succeeded = true,
                    Message = "Permanently deleted after explicit confirmation.", Path = target.OriginalPath, Sha256 = target.Sha256, QuarantineEntryId = target.EntryId,
                });
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                results.Add(new DeletionItemResult(target.EntryId, false, $"Could not delete: {ex.Message}"));
                _operations.Append(new OperationRecord
                {
                    Id = Guid.NewGuid().ToString("N"), Type = OperationType.PermanentDelete, TimestampUtc = _time.GetUtcNow(), Succeeded = false,
                    Message = ex.Message, Path = target.OriginalPath, Sha256 = target.Sha256, QuarantineEntryId = target.EntryId,
                });
            }
        }

        var succeeded = results.Count(r => r.Succeeded);
        return new DeletionResult(true, $"{succeeded} of {results.Count} item(s) permanently deleted.", results);
    }

    // ------------------------------------------------------------------ listing and integrity

    public IReadOnlyList<QuarantineEntry> ListEntries(bool includeRestored = false)
    {
        if (!Directory.Exists(EntriesDirectory))
        {
            return [];
        }

        var entries = new List<QuarantineEntry>();
        foreach (var directory in Directory.EnumerateDirectories(EntriesDirectory))
        {
            var entry = LoadEntry(Path.GetFileName(directory));
            if (entry is not null && (includeRestored || entry.Status == QuarantineEntryStatus.Quarantined))
            {
                entries.Add(entry);
            }
        }

        return entries.OrderByDescending(e => e.QuarantinedAtUtc).ToList();
    }

    public QuarantineEntry? LoadEntry(string id)
    {
        if (string.IsNullOrEmpty(id) || id.Any(c => !char.IsAsciiHexDigit(c)))
        {
            return null;
        }

        var manifest = Path.Combine(EntriesDirectory, id, ManifestName);
        try
        {
            return File.Exists(manifest) ? JsonSerializer.Deserialize<QuarantineEntry>(File.ReadAllText(manifest), CleanerJson.Default) : null;
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            _logger.LogWarning(ex, "Quarantine manifest {Id} is unreadable", id);
            return null;
        }
    }

    public IntegrityStatus VerifyIntegrity(string entryId, CancellationToken cancellationToken = default)
    {
        var entry = LoadEntry(entryId);
        return entry is null ? IntegrityStatus.ManifestDamaged : VerifyIntegrity(entry, cancellationToken);
    }

    private IntegrityStatus VerifyIntegrity(QuarantineEntry entry, CancellationToken cancellationToken)
    {
        if (entry.Status != QuarantineEntryStatus.Quarantined)
        {
            return IntegrityStatus.NotApplicable;
        }

        var payload = Path.Combine(EntriesDirectory, entry.Id, PayloadName);
        if (!File.Exists(payload))
        {
            return IntegrityStatus.PayloadMissing;
        }

        try
        {
            return string.Equals(DecodeHash(payload, Convert.FromBase64String(entry.EncodingKey), cancellationToken), entry.Sha256, StringComparison.Ordinal)
                ? IntegrityStatus.Verified
                : IntegrityStatus.HashMismatch;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or FormatException)
        {
            return IntegrityStatus.PayloadMissing;
        }
    }

    // ------------------------------------------------------------------ recovery

    /// <summary>Completes or rolls back operations that were interrupted (crash, power loss, forced shutdown).</summary>
    public RecoveryReport RecoverInterruptedOperations()
    {
        var actions = new List<string>();
        if (!Directory.Exists(JournalDirectory))
        {
            return new RecoveryReport(actions);
        }

        foreach (var file in Directory.EnumerateFiles(JournalDirectory, "*.json"))
        {
            JournalRecord? record;
            try
            {
                record = JsonSerializer.Deserialize<JournalRecord>(File.ReadAllText(file), CleanerJson.Default);
            }
            catch (Exception ex) when (ex is JsonException or IOException)
            {
                actions.Add($"An unreadable journal record ({Path.GetFileName(file)}) was found and left for manual inspection.");
                continue;
            }

            if (record is null || record.EntryId.Any(c => !char.IsAsciiHexDigit(c)))
            {
                continue;
            }

            var entryDirectory = Path.Combine(EntriesDirectory, record.EntryId);
            var originalExists = File.Exists(record.OriginalPath);
            var entry = LoadEntry(record.EntryId);
            var payloadOk = entry is not null && VerifyIntegrity(entry with { Status = QuarantineEntryStatus.Quarantined }, CancellationToken.None) == IntegrityStatus.Verified;

            if (originalExists)
            {
                // The original was never removed: undo the partial quarantine. No data is lost.
                RollBack(entryDirectory, record.EntryId);
                actions.Add($"Rolled back an interrupted quarantine of {record.OriginalPath}; the original file is intact.");
            }
            else if (payloadOk)
            {
                SaveManifest(entry! with { Status = QuarantineEntryStatus.Quarantined });
                DeleteJournal(record.EntryId);
                actions.Add($"Completed an interrupted quarantine of {record.OriginalPath}; the verified copy is in quarantine.");
            }
            else
            {
                actions.Add($"WARNING: an interrupted quarantine of {record.OriginalPath} could not be verified and the original is missing. The journal and any partial data were kept in {entryDirectory} for manual recovery.");
            }

            _operations.Append(new OperationRecord
            {
                Id = Guid.NewGuid().ToString("N"), Type = OperationType.Recovery, TimestampUtc = _time.GetUtcNow(), Succeeded = originalExists || payloadOk,
                Message = actions[^1], Path = record.OriginalPath, Sha256 = record.Sha256, QuarantineEntryId = record.EntryId,
            });
        }

        return new RecoveryReport(actions);
    }

    // ------------------------------------------------------------------ helpers

    private enum JournalStage
    {
        Started,
        PayloadVerified,
        OriginalDeleted,
    }

    private sealed record JournalRecord(string EntryId, string OriginalPath, string Sha256, JournalStage Stage, DateTimeOffset TimestampUtc);

    private void WriteJournal(JournalRecord record) =>
        AtomicFile.WriteAllText(Path.Combine(JournalDirectory, record.EntryId + ".json"), JsonSerializer.Serialize(record, CleanerJson.Default));

    private void DeleteJournal(string id) => AtomicFile.TryDelete(Path.Combine(JournalDirectory, id + ".json"));

    private void SaveManifest(QuarantineEntry entry) =>
        AtomicFile.WriteAllText(Path.Combine(EntriesDirectory, entry.Id, ManifestName), JsonSerializer.Serialize(entry, CleanerJson.Default));

    private void RollBack(string entryDirectory, string id)
    {
        try
        {
            if (Directory.Exists(entryDirectory))
            {
                foreach (var name in new[] { PayloadName, PayloadName + ".tmp", ManifestName })
                {
                    AtomicFile.TryDelete(Path.Combine(entryDirectory, name));
                }

                if (!Directory.EnumerateFileSystemEntries(entryDirectory).Any())
                {
                    Directory.Delete(entryDirectory, recursive: false);
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _logger.LogWarning(ex, "Could not clean up partial quarantine entry {Id}", id);
        }

        DeleteJournal(id);
    }

    /// <summary>Copies with XOR encoding. Returns (hash of input, hash of output).</summary>
    private static (string InputHash, string OutputHash) CopyEncoded(Stream source, Stream target, byte[] key, CancellationToken cancellationToken, bool hashOutput = true)
    {
        using var inputHash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        using var outputHash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[81920];
        long position = 0;
        int read;
        while ((read = source.Read(buffer, 0, buffer.Length)) > 0)
        {
            cancellationToken.ThrowIfCancellationRequested();
            inputHash.AppendData(buffer, 0, read);
            for (var i = 0; i < read; i++)
            {
                buffer[i] ^= key[(position + i) % key.Length];
            }

            if (hashOutput)
            {
                outputHash.AppendData(buffer, 0, read);
            }

            target.Write(buffer, 0, read);
            position += read;
        }

        return (Convert.ToHexString(inputHash.GetHashAndReset()).ToLowerInvariant(), Convert.ToHexString(outputHash.GetHashAndReset()).ToLowerInvariant());
    }

    private static string DecodeHash(string payloadPath, byte[] key, CancellationToken cancellationToken)
    {
        using var source = File.OpenRead(payloadPath);
        return CopyEncoded(source, Stream.Null, key, cancellationToken).OutputHash;
    }

    private string ComputeToken(IEnumerable<string> ids, DateTimeOffset expires)
    {
        var text = string.Join(",", ids.Order(StringComparer.Ordinal)) + "|" + expires.UtcTicks;
        return Convert.ToHexString(HMACSHA256.HashData(_tokenSecret, Encoding.UTF8.GetBytes(text)), 0, 16);
    }

    private static string UniqueName(string path)
    {
        if (!File.Exists(path) && !Directory.Exists(path))
        {
            return path;
        }

        var directory = Path.GetDirectoryName(path)!;
        var name = Path.GetFileNameWithoutExtension(path);
        var extension = Path.GetExtension(path);
        for (var i = 1; i < 1000; i++)
        {
            var candidate = Path.Combine(directory, i == 1 ? $"{name} (restored){extension}" : $"{name} (restored {i}){extension}");
            if (!File.Exists(candidate) && !Directory.Exists(candidate))
            {
                return candidate;
            }
        }

        return Path.Combine(directory, $"{name} (restored {Guid.NewGuid():N}){extension}");
    }

    private static DateTimeOffset? SafeTime(Func<DateTime> getter)
    {
        try
        {
            return new DateTimeOffset(getter(), TimeSpan.Zero);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static void TrySetTimes(string path, QuarantineEntry entry)
    {
        try
        {
            if (entry.CreationTimeUtc is { } created)
            {
                File.SetCreationTimeUtc(path, created.UtcDateTime);
            }

            if (entry.LastWriteTimeUtc is { } written)
            {
                File.SetLastWriteTimeUtc(path, written.UtcDateTime);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or PlatformNotSupportedException)
        {
        }
    }

    private static void TryRestoreAttributes(string path, FileAttributes attributes)
    {
        try
        {
            var safe = attributes & (FileAttributes.ReadOnly | FileAttributes.Hidden | FileAttributes.Archive);
            if (OperatingSystem.IsWindows() && File.Exists(path))
            {
                File.SetAttributes(path, safe == 0 ? FileAttributes.Normal : safe);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }
    }

    private static QuarantineResult Blocked(string path, PathValidationResult validation) => new()
    {
        Succeeded = false,
        Message = $"Blocked by the safety policy: {validation.Reason}",
        Path = path,
        BlockCode = validation.Code,
        OriginalPreserved = true,
    };

    private static QuarantineResult Fail(string path, string message) => new()
    {
        Succeeded = false,
        Message = message,
        Path = path,
        OriginalPreserved = true,
    };

    private QuarantineResult Record(QuarantineResult result, QuarantineRequest request)
    {
        _operations.Append(new OperationRecord
        {
            Id = Guid.NewGuid().ToString("N"),
            Type = OperationType.Quarantine,
            TimestampUtc = _time.GetUtcNow(),
            Succeeded = result.Succeeded,
            Message = result.Message,
            Path = result.Path,
            Sha256 = result.Entry?.Sha256 ?? request.ExpectedSha256,
            SessionId = request.SessionId,
            FindingId = request.FindingId,
            QuarantineEntryId = result.Entry?.Id,
        });
        return result;
    }

    private RestoreResult RecordRestore(RestoreResult result, string entryId, QuarantineEntry? entry)
    {
        _operations.Append(new OperationRecord
        {
            Id = Guid.NewGuid().ToString("N"),
            Type = OperationType.Restore,
            TimestampUtc = _time.GetUtcNow(),
            Succeeded = result.Succeeded,
            Message = result.Message,
            Path = result.RestoredPath ?? entry?.OriginalPath,
            Sha256 = entry?.Sha256,
            SessionId = entry?.SessionId,
            FindingId = entry?.FindingId,
            QuarantineEntryId = entryId,
        });
        return result;
    }
}
