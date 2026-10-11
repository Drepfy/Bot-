using System.Text.Json;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Core.Safety;
using CleanerPro.Infrastructure;
using CleanerPro.TestSupport;

namespace CleanerPro.Quarantine.Tests;

public sealed class QuarantineServiceTests : IDisposable
{
    private readonly TempDirectory _temp = new();
    private readonly string _game;
    private readonly string _quarantineRoot;
    private readonly OperationLog _log;
    private readonly ManualTimeProvider _time = new(new DateTimeOffset(2026, 10, 11, 10, 0, 0, TimeSpan.Zero));

    public QuarantineServiceTests()
    {
        _game = _temp.CreateDirectory("game");
        _quarantineRoot = _temp.Combine("quarantine");
        _log = new OperationLog(_temp.Combine("ops.jsonl"));
    }

    public void Dispose() => _temp.Dispose();

    private QuarantineService Service(Func<string, Stream>? payloadStream = null, PathSafetyPolicy? policy = null) =>
        new(() => _quarantineRoot, policy ?? TestPolicies.Create(), _log, time: _time, createPayloadStream: payloadStream);

    private string Cheat(string name = "cheat.jar", string content = "harmless fixture content")
    {
        return _temp.WriteText($"game/mods/{name}", content);
    }

    private QuarantineRequest Request(string path, string? sha = null) => new()
    {
        Path = path,
        ApprovedRoots = [_game],
        ExpectedSha256 = sha ?? FileHasher.Compute(path, false).Sha256,
        FindingId = "finding-1",
        SessionId = "session-1",
        RuleIds = ["CP-HC-0001"],
        Family = "Wurst Client",
    };

    [Fact]
    public void RemovePermanentlyVerifiesThenDeletesExactlyThatFile()
    {
        var file = Cheat();
        var other = Cheat("other.jar", "a different file");
        var service = Service();

        var result = service.RemovePermanently(Request(file), isDirectory: false);

        Assert.True(result.Succeeded, result.Message);
        Assert.False(File.Exists(file));
        Assert.True(File.Exists(other));
        Assert.Empty(service.ListEntries());
        Assert.Equal([OperationType.Quarantine, OperationType.PermanentDelete], _log.ReadAll().Select(r => r.Type));
        Assert.All(_log.ReadAll(), r => Assert.True(r.Succeeded));
    }

    [Fact]
    public void RemovePermanentlyKeepsAFileThatChangedSinceTheScan()
    {
        var file = Cheat();
        var request = Request(file);
        File.WriteAllText(file, "modified after the scan");

        var result = Service().RemovePermanently(request, isDirectory: false);

        Assert.False(result.Succeeded);
        Assert.Null(result.Deletion);
        Assert.True(File.Exists(file));
        Assert.StartsWith("Nothing was deleted", result.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void RemovePermanentlyHonoursPathProtection()
    {
        var outside = _temp.WriteText("elsewhere/x.jar", "outside the approved folder");
        var result = Service().RemovePermanently(Request(outside), isDirectory: false);
        Assert.False(result.Succeeded);
        Assert.True(File.Exists(outside));
    }

    [Fact]
    public void QuarantineMovesTheFileAndVerifiesTheCopy()
    {
        var file = Cheat();
        var original = File.ReadAllBytes(file);
        var service = Service();

        var result = service.Quarantine(Request(file));

        Assert.True(result.Succeeded, result.Message);
        Assert.False(result.OriginalPreserved);
        Assert.False(File.Exists(file));
        var entry = Assert.Single(service.ListEntries());
        Assert.Equal(file, entry.OriginalPath);
        Assert.Equal(FileHasher.Sha256Hex(original), entry.Sha256);
        Assert.Equal(IntegrityStatus.Verified, service.VerifyIntegrity(entry.Id));

        var payload = File.ReadAllBytes(Path.Combine(_quarantineRoot, "entries", entry.Id, "payload.bin"));
        Assert.NotEqual(original, payload); // encoded so it cannot be run or opened by accident
        Assert.Empty(Directory.GetFiles(Path.Combine(_quarantineRoot, "journal")));
        var record = Assert.Single(_log.ReadAll());
        Assert.True(record.Succeeded);
        Assert.Equal(OperationType.Quarantine, record.Type);
        Assert.Equal("finding-1", record.FindingId);
    }

    [Fact]
    public void FilesOutsideTheApprovedScopeAreBlocked()
    {
        var outside = _temp.WriteText("elsewhere/file.jar", "x");
        var result = Service().Quarantine(Request(outside));
        Assert.False(result.Succeeded);
        Assert.True(result.OriginalPreserved);
        Assert.Equal(PathBlockCode.OutsideApprovedScope, result.BlockCode);
        Assert.True(File.Exists(outside));
    }

    [Fact]
    public void ProtectedLocationsAreBlocked()
    {
        var file = Cheat();
        var result = Service(policy: TestPolicies.Create(Path.Combine(_game, "mods"))).Quarantine(Request(file));
        Assert.Equal(PathBlockCode.ProtectedLocation, result.BlockCode);
        Assert.True(File.Exists(file));
    }

    [Fact]
    public void FilesThatChangedSinceTheScanAreNotQuarantined()
    {
        var file = Cheat();
        var request = Request(file, sha: new string('0', 64));
        var result = Service().Quarantine(request);
        Assert.False(result.Succeeded);
        Assert.Contains("changed since the scan", result.Message);
        Assert.True(File.Exists(file));
        Assert.Empty(Service().ListEntries());
    }

    [Fact]
    public void DiskFullDuringCopyKeepsTheOriginalAndLeavesNoPartialEntry()
    {
        var file = Cheat(content: new string('x', 200_000));
        var service = Service(path => new FailingStream(path, failAfterBytes: 50_000));

        var result = service.Quarantine(Request(file));

        Assert.False(result.Succeeded);
        Assert.True(result.OriginalPreserved);
        Assert.Contains("not removed", result.Message);
        Assert.True(File.Exists(file));
        Assert.Equal(200_000, new FileInfo(file).Length);
        Assert.Empty(service.ListEntries(includeRestored: true));
        Assert.Empty(Directory.GetDirectories(Path.Combine(_quarantineRoot, "entries")));
        Assert.False(_log.ReadAll().Single().Succeeded);
    }

    [Fact]
    public void LinkedFilesAreNeverQuarantined()
    {
        var real = _temp.WriteText("outside/real.jar", "x");
        var link = Path.Combine(_game, "mods", "link.jar");
        Directory.CreateDirectory(Path.GetDirectoryName(link)!);
        if (!SymlinkSupport.TryCreateFileLink(link, real))
        {
            return;
        }

        var result = Service().Quarantine(new QuarantineRequest { Path = link, ApprovedRoots = [_game] });
        Assert.Equal(PathBlockCode.ReparsePoint, result.BlockCode);
        Assert.True(File.Exists(real));
    }

    [Fact]
    public void RestoreReturnsTheExactOriginalContent()
    {
        var file = Cheat();
        var original = File.ReadAllBytes(file);
        var service = Service();
        var entry = service.Quarantine(Request(file)).Entry!;

        var restore = service.Restore(new RestoreRequest(entry.Id, RestoreMode.OriginalLocation));

        Assert.True(restore.Succeeded, restore.Message);
        Assert.Equal(original, File.ReadAllBytes(file));
        Assert.Empty(service.ListEntries());
        Assert.Equal(QuarantineEntryStatus.Restored, service.LoadEntry(entry.Id)!.Status);
        Assert.Contains(_log.ReadAll(), r => r.Type == OperationType.Restore && r.Succeeded);
    }

    [Fact]
    public void RestoreNeverOverwritesAnExistingFile()
    {
        var file = Cheat();
        var service = Service();
        var entry = service.Quarantine(Request(file)).Entry!;
        File.WriteAllText(file, "a new, different file");

        var conflict = service.Restore(new RestoreRequest(entry.Id, RestoreMode.OriginalLocation));

        Assert.False(conflict.Succeeded);
        Assert.True(conflict.Conflict);
        Assert.Equal("a new, different file", File.ReadAllText(file));
        Assert.Single(service.ListEntries());

        var renamed = service.Restore(new RestoreRequest(entry.Id, RestoreMode.OriginalLocationWithNewName));
        Assert.True(renamed.Succeeded, renamed.Message);
        Assert.EndsWith("cheat (restored).jar", renamed.RestoredPath, StringComparison.Ordinal);
        Assert.Equal("harmless fixture content", File.ReadAllText(renamed.RestoredPath!));
        Assert.Equal("a new, different file", File.ReadAllText(file));
    }

    [Fact]
    public void RestoreToAnAlternateFolder()
    {
        var file = Cheat();
        var service = Service();
        var entry = service.Quarantine(Request(file)).Entry!;
        var target = _temp.CreateDirectory("restored-here");

        var result = service.Restore(new RestoreRequest(entry.Id, RestoreMode.AlternateDirectory, target));

        Assert.True(result.Succeeded, result.Message);
        Assert.Equal(Path.Combine(target, "cheat.jar"), result.RestoredPath);
    }

    [Fact]
    public void RestoreRecreatesAMissingParentFolderInsideTheScope()
    {
        var file = Cheat();
        var service = Service();
        var entry = service.Quarantine(Request(file)).Entry!;
        Directory.Delete(Path.Combine(_game, "mods"));

        Assert.True(service.Restore(new RestoreRequest(entry.Id, RestoreMode.OriginalLocation)).Succeeded);
        Assert.True(File.Exists(file));
    }

    [Fact]
    public void ADamagedQuarantineCopyIsNotRestored()
    {
        var file = Cheat();
        var service = Service();
        var entry = service.Quarantine(Request(file)).Entry!;
        var payload = Path.Combine(_quarantineRoot, "entries", entry.Id, "payload.bin");
        var bytes = File.ReadAllBytes(payload);
        bytes[0] ^= 0xFF;
        File.WriteAllBytes(payload, bytes);

        Assert.Equal(IntegrityStatus.HashMismatch, service.VerifyIntegrity(entry.Id));
        var result = service.Restore(new RestoreRequest(entry.Id, RestoreMode.OriginalLocation));
        Assert.False(result.Succeeded);
        Assert.Contains("integrity", result.Message);
        Assert.False(File.Exists(file));

        File.Delete(payload);
        Assert.Equal(IntegrityStatus.PayloadMissing, service.VerifyIntegrity(entry.Id));
    }

    [Fact]
    public void PermanentDeletionRequiresTheExactConfirmedSet()
    {
        var service = Service();
        var a = service.Quarantine(Request(Cheat("a.jar", "a"))).Entry!;
        var b = service.Quarantine(Request(Cheat("b.jar", "b"))).Entry!;

        var plan = service.PrepareDeletion([a.Id]);
        Assert.Equal(a.OriginalPath, Assert.Single(plan.Targets).OriginalPath);

        var wrongToken = service.ExecuteDeletion(plan, "0000");
        Assert.False(wrongToken.Executed);
        Assert.Equal(2, service.ListEntries().Count);

        // A plan that was altered after confirmation (an extra item added) is refused.
        var tampered = plan with { Targets = [.. plan.Targets, new DeletionTarget(b.Id, b.OriginalPath, b.Size, b.Sha256, b.QuarantinedAtUtc)] };
        Assert.False(service.ExecuteDeletion(tampered, plan.Token).Executed);
        Assert.Equal(2, service.ListEntries().Count);

        var result = service.ExecuteDeletion(plan, plan.Token);
        Assert.True(result.Executed);
        Assert.True(Assert.Single(result.Items).Succeeded);
        Assert.Equal(b.Id, Assert.Single(service.ListEntries()).Id);
        Assert.False(Directory.Exists(Path.Combine(_quarantineRoot, "entries", a.Id)));
        Assert.Contains(_log.ReadAll(), r => r.Type == OperationType.PermanentDelete && r.QuarantineEntryId == a.Id);
    }

    [Fact]
    public void DeletionConfirmationsExpire()
    {
        var service = Service();
        var entry = service.Quarantine(Request(Cheat())).Entry!;
        var plan = service.PrepareDeletion([entry.Id]);
        _time.Advance(TimeSpan.FromMinutes(11));
        var result = service.ExecuteDeletion(plan, plan.Token);
        Assert.False(result.Executed);
        Assert.Contains("expired", result.Message);
        Assert.Single(service.ListEntries());
    }

    [Fact]
    public void EmptySelectionsDeleteNothing()
    {
        var service = Service();
        var plan = service.PrepareDeletion(["not-a-real-id"]);
        Assert.Empty(plan.Targets);
        Assert.False(service.ExecuteDeletion(plan, plan.Token).Executed);
    }

    [Fact]
    public void InterruptedQuarantineWithTheOriginalPresentIsRolledBack()
    {
        var file = Cheat();
        var id = "0123456789abcdef0123456789abcdef";
        Directory.CreateDirectory(Path.Combine(_quarantineRoot, "entries", id));
        File.WriteAllBytes(Path.Combine(_quarantineRoot, "entries", id, "payload.bin.tmp"), [1, 2, 3]);
        WriteJournal(id, file, "Started");

        var report = Service().RecoverInterruptedOperations();

        Assert.True(report.AnythingRecovered);
        Assert.Contains(report.Actions, a => a.Contains("Rolled back"));
        Assert.True(File.Exists(file));
        Assert.False(Directory.Exists(Path.Combine(_quarantineRoot, "entries", id)));
        Assert.Empty(Directory.GetFiles(Path.Combine(_quarantineRoot, "journal")));
    }

    [Fact]
    public void InterruptedQuarantineAfterVerificationIsCompleted()
    {
        var file = Cheat();
        var service = Service();
        // Quarantine normally, then simulate a crash between deleting the original and finalising the manifest.
        var entry = service.Quarantine(Request(file)).Entry!;
        var manifestPath = Path.Combine(_quarantineRoot, "entries", entry.Id, "manifest.json");
        File.WriteAllText(manifestPath, JsonSerializer.Serialize(entry with { Status = QuarantineEntryStatus.Pending }, CleanerJson.Default));
        WriteJournal(entry.Id, file, "OriginalDeleted");

        var report = service.RecoverInterruptedOperations();

        Assert.Contains(report.Actions, a => a.Contains("Completed"));
        Assert.Equal(QuarantineEntryStatus.Quarantined, service.LoadEntry(entry.Id)!.Status);
        Assert.Single(service.ListEntries());
    }

    [Fact]
    public void DirectoryFindingsAreQuarantinedFileByFile()
    {
        _temp.WriteText("game/meteor-client/config.json", "{}");
        _temp.WriteText("game/meteor-client/profiles/default.json", "{}");
        var directory = Path.Combine(_game, "meteor-client");
        var service = Service();

        var results = service.QuarantineDirectory(new QuarantineRequest { Path = directory, ApprovedRoots = [_game] });

        Assert.Equal(2, results.Count);
        Assert.All(results, r => Assert.True(r.Succeeded, r.Message));
        Assert.False(Directory.Exists(directory));
        Assert.Equal(2, service.ListEntries().Count);
        Assert.True(Directory.Exists(_game));
    }

    [Fact]
    public void DirectoriesContainingLinksAreRefused()
    {
        var outside = _temp.CreateDirectory("outside");
        _temp.WriteText("outside/keep.txt", "x");
        var directory = _temp.CreateDirectory("game", "LiquidBounce");
        if (!SymlinkSupport.TryCreateDirectoryLink(Path.Combine(directory, "link"), outside))
        {
            return;
        }

        var result = Assert.Single(Service().QuarantineDirectory(new QuarantineRequest { Path = directory, ApprovedRoots = [_game] }));
        Assert.False(result.Succeeded);
        Assert.True(File.Exists(Path.Combine(outside, "keep.txt")));
    }

    [Fact]
    public void TheInstallationRootItselfCannotBeQuarantined()
    {
        var result = Assert.Single(Service().QuarantineDirectory(new QuarantineRequest { Path = _game, ApprovedRoots = [_game] }));
        Assert.Equal(PathBlockCode.IsApprovedRoot, result.BlockCode);
    }

    private void WriteJournal(string id, string originalPath, string stage)
    {
        var directory = Path.Combine(_quarantineRoot, "journal");
        Directory.CreateDirectory(directory);
        var json = JsonSerializer.Serialize(new { entryId = id, originalPath, sha256 = "x", stage, timestampUtc = DateTimeOffset.UtcNow }, CleanerJson.Default);
        File.WriteAllText(Path.Combine(directory, id + ".json"), json);
    }

    /// <summary>Simulates a full disk: throws the Windows "disk full" error after a number of bytes.</summary>
    private sealed class FailingStream(string path, long failAfterBytes) : FileStream(path, FileMode.CreateNew, FileAccess.Write)
    {
        private long _written;

        public override void Write(byte[] buffer, int offset, int count)
        {
            _written += count;
            if (_written > failAfterBytes)
            {
                throw new IOException("There is not enough space on the disk.", unchecked((int)0x80070070));
            }

            base.Write(buffer, offset, count);
        }
    }
}
