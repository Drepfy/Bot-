using System.Buffers;
using System.IO.Compression;
using System.Text;
using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Bytecode;
using CleanerPro.Detection.Matching;

namespace CleanerPro.Scanner.Inspection;

public sealed record ArchiveInspectionOptions
{
    public int MaxEntries { get; init; } = 50_000;

    public long MaxTotalUncompressedBytes { get; init; } = 1024L * 1024 * 1024;

    public long MaxEntryUncompressedBytes { get; init; } = 64L * 1024 * 1024;

    public int MaxCompressionRatio { get; init; } = 250;

    public int MaxNestedDepth { get; init; } = 2;

    public long MaxNestedArchiveBytes { get; init; } = 64L * 1024 * 1024;

    public bool InspectBytecode { get; init; } = true;

    public int MaxClassFileBytes { get; init; } = 2 * 1024 * 1024;

    public static ArchiveInspectionOptions FromConfiguration(AppConfiguration config) => new()
    {
        MaxEntries = config.Scan.ArchiveLimits.MaxEntries,
        MaxTotalUncompressedBytes = config.Scan.ArchiveLimits.MaxTotalUncompressedMegabytes * 1024L * 1024,
        MaxEntryUncompressedBytes = config.Scan.ArchiveLimits.MaxEntryUncompressedMegabytes * 1024L * 1024,
        MaxCompressionRatio = config.Scan.ArchiveLimits.MaxCompressionRatio,
        MaxNestedDepth = config.Scan.ArchiveLimits.MaxNestedArchiveDepth,
        MaxNestedArchiveBytes = config.Scan.ArchiveLimits.MaxNestedArchiveMegabytes * 1024L * 1024,
        InspectBytecode = config.Scan.InspectBytecode,
        MaxClassFileBytes = config.Scan.MaxClassFileKilobytes * 1024,
    };
}

/// <summary>
/// Reads ZIP/JAR archives as untrusted input. Nothing is extracted to disk and nothing is executed.
/// Entry counts, uncompressed sizes, compression ratios and nesting are bounded to defeat archive bombs.
/// </summary>
public sealed class ArchiveInspector
{
    private const int MaxMetadataBytes = 1024 * 1024;

    private static readonly string[] MetadataFiles =
    [
        "fabric.mod.json", "quilt.mod.json", "META-INF/mods.toml", "META-INF/neoforge.mods.toml", "mcmod.info", "META-INF/MANIFEST.MF",
    ];

    private readonly ArchiveInspectionOptions _options;
    private readonly BytecodeSignatureMatcher? _matcher;
    private readonly MemoryBudget _budget;

    public ArchiveInspector(ArchiveInspectionOptions options, BytecodeSignatureMatcher? matcher, MemoryBudget budget)
    {
        _options = options;
        _matcher = matcher is { HasSignatures: true } && options.InspectBytecode ? matcher : null;
        _budget = budget;
    }

    public static bool IsArchiveExtension(string extension) =>
        extension is ".jar" or ".zip" or ".litemod";

    /// <summary>Inspects the archive. Problems are appended to <paramref name="problems"/>; returns null if it is not a readable archive.</summary>
    public ArchiveObservation? Inspect(Stream stream, List<string> problems, CancellationToken cancellationToken)
    {
        var state = new InspectionState();
        return InspectCore(stream, string.Empty, 0, problems, state, cancellationToken);
    }

    private sealed class InspectionState
    {
        public long BytesRead;

        public bool TotalLimitReported;
    }

    private ArchiveObservation? InspectCore(Stream stream, string prefix, int depth, List<string> problems, InspectionState state, CancellationToken cancellationToken)
    {
        ZipArchive archive;
        try
        {
            archive = new ZipArchive(stream, ZipArchiveMode.Read, leaveOpen: true);
        }
        catch (InvalidDataException ex)
        {
            problems.Add($"{Describe(prefix)} is not a readable ZIP/JAR archive ({ex.Message}).");
            return null;
        }

        using (archive)
        {
            var observation = new ArchiveObservation();
            IReadOnlyCollection<ZipArchiveEntry> entries;
            try
            {
                entries = archive.Entries;
            }
            catch (InvalidDataException ex)
            {
                problems.Add($"{Describe(prefix)} has a corrupt central directory ({ex.Message}).");
                return null;
            }

            var count = 0;
            foreach (var entry in entries)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (++count > _options.MaxEntries)
                {
                    problems.Add($"{Describe(prefix)} has more than {_options.MaxEntries} entries; only the first {_options.MaxEntries} were inspected.");
                    break;
                }

                var name = entry.FullName.Replace('\\', '/');
                if (name.EndsWith('/'))
                {
                    continue; // directory entry
                }

                observation.AddEntry(name);
                observation.EntryCount++;

                if (name.StartsWith("META-INF/", StringComparison.OrdinalIgnoreCase) &&
                    (name.EndsWith(".SF", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".RSA", StringComparison.OrdinalIgnoreCase) ||
                     name.EndsWith(".DSA", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".EC", StringComparison.OrdinalIgnoreCase)))
                {
                    observation.HasJarSignatureFiles = true;
                }

                if (MetadataFiles.Contains(name, StringComparer.Ordinal))
                {
                    ReadMetadata(entry, name, prefix, observation, problems, state);
                }
                else if (_matcher is not null && name.EndsWith(".class", StringComparison.Ordinal))
                {
                    ScanClass(entry, name, prefix, observation, problems, state, cancellationToken);
                }
                else if (depth < _options.MaxNestedDepth && name.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
                {
                    InspectNested(entry, name, prefix, depth, observation, problems, state, cancellationToken);
                }
            }

            return observation;
        }
    }

    private void ReadMetadata(ZipArchiveEntry entry, string name, string prefix, ArchiveObservation observation, List<string> problems, InspectionState state)
    {
        var bytes = ReadBounded(entry, MaxMetadataBytes, prefix, problems, state);
        if (bytes is null)
        {
            return;
        }

        var text = Encoding.UTF8.GetString(bytes);
        var location = prefix + name;
        string? problem = null;
        switch (name)
        {
            case "fabric.mod.json":
                if (ModMetadataParser.ParseFabric(text, location, out problem) is { } fabric)
                {
                    observation.Mods.Add(fabric);
                }

                break;
            case "quilt.mod.json":
                if (ModMetadataParser.ParseQuilt(text, location, out problem) is { } quilt)
                {
                    observation.Mods.Add(quilt);
                }

                break;
            case "META-INF/mods.toml":
                observation.Mods.AddRange(ModMetadataParser.ParseModsToml(text, location, ModLoader.Forge));
                break;
            case "META-INF/neoforge.mods.toml":
                observation.Mods.AddRange(ModMetadataParser.ParseModsToml(text, location, ModLoader.NeoForge));
                break;
            case "mcmod.info":
                observation.Mods.AddRange(ModMetadataParser.ParseMcmodInfo(text, location, out problem));
                break;
            case "META-INF/MANIFEST.MF" when prefix.Length == 0:
                foreach (var (key, value) in ModMetadataParser.ParseManifest(text))
                {
                    observation.ManifestAttributes[key] = value;
                }

                break;
        }

        if (problem is not null)
        {
            problems.Add(problem);
        }
    }

    private void ScanClass(ZipArchiveEntry entry, string name, string prefix, ArchiveObservation observation, List<string> problems,
        InspectionState state, CancellationToken cancellationToken)
    {
        if (entry.Length > _options.MaxClassFileBytes)
        {
            return; // Very large classes are skipped; documented limitation.
        }

        using var lease = _budget.Acquire(Math.Max(entry.Length, 1), cancellationToken);
        if (lease is null)
        {
            return;
        }

        var buffer = ArrayPool<byte>.Shared.Rent((int)Math.Max(entry.Length, 1));
        try
        {
            var length = ReadInto(entry, buffer, _options.MaxClassFileBytes, prefix, problems, state);
            if (length < 0)
            {
                return;
            }

            try
            {
                foreach (var key in _matcher!.Match(buffer.AsSpan(0, length)))
                {
                    observation.BytecodeHits.TryAdd(key, prefix + name);
                }

                observation.ClassFilesInspected++;
            }
            catch (ClassFormatException)
            {
                observation.ClassFilesUnparseable++;
            }
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private void InspectNested(ZipArchiveEntry entry, string name, string prefix, int depth, ArchiveObservation observation, List<string> problems,
        InspectionState state, CancellationToken cancellationToken)
    {
        var nestedName = prefix + name;
        if (entry.Length > _options.MaxNestedArchiveBytes)
        {
            problems.Add($"Nested archive {nestedName} is larger than the {_options.MaxNestedArchiveBytes / (1024 * 1024)} MB limit and was not inspected.");
            return;
        }

        using var lease = _budget.Acquire(Math.Max(entry.Length, 1), cancellationToken);
        if (lease is null)
        {
            problems.Add($"Nested archive {nestedName} exceeds the memory budget and was not inspected.");
            return;
        }

        var bytes = ReadBounded(entry, _options.MaxNestedArchiveBytes, prefix, problems, state);
        if (bytes is null)
        {
            return;
        }

        observation.NestedArchives.Add(nestedName);
        using var memory = new MemoryStream(bytes, writable: false);
        var nested = InspectCore(memory, nestedName + "!/", depth + 1, problems, state, cancellationToken);
        if (nested is null)
        {
            return;
        }

        // Nested (jar-in-jar) content is part of the outer file, so it is merged for matching.
        foreach (var nestedEntry in nested.Entries)
        {
            observation.Entries.Add(nestedEntry);
        }

        observation.ClassPackages.UnionWith(nested.ClassPackages);
        observation.Mods.AddRange(nested.Mods);
        foreach (var (key, location) in nested.BytecodeHits)
        {
            observation.BytecodeHits.TryAdd(key, location);
        }

        observation.NestedArchives.AddRange(nested.NestedArchives);
        observation.ClassCount += nested.ClassCount;
        observation.ClassFilesInspected += nested.ClassFilesInspected;
        observation.ClassFilesUnparseable += nested.ClassFilesUnparseable;
    }

    private byte[]? ReadBounded(ZipArchiveEntry entry, long limit, string prefix, List<string> problems, InspectionState state)
    {
        if (!PassesBombChecks(entry, limit, prefix, problems, state))
        {
            return null;
        }

        var buffer = new byte[(int)Math.Max(entry.Length, 0)];
        var length = ReadUnchecked(entry, buffer, prefix, problems, state);
        return length < 0 ? null : length == buffer.Length ? buffer : buffer[..length];
    }

    /// <summary>Reads the entry into <paramref name="buffer"/>, refusing to read more than declared or allowed. Returns -1 on failure.</summary>
    private int ReadInto(ZipArchiveEntry entry, byte[] buffer, long limit, string prefix, List<string> problems, InspectionState state) =>
        PassesBombChecks(entry, limit, prefix, problems, state) ? ReadUnchecked(entry, buffer, prefix, problems, state) : -1;

    private static int ReadUnchecked(ZipArchiveEntry entry, byte[] buffer, string prefix, List<string> problems, InspectionState state)
    {
        var declared = (int)entry.Length;
        try
        {
            using var stream = entry.Open();
            var total = 0;
            int read;
            while (total < declared && (read = stream.Read(buffer, total, declared - total)) > 0)
            {
                total += read;
            }

            // A stream that yields more data than its declared size is malformed (or a bomb); stop here.
            if (stream.ReadByte() >= 0)
            {
                problems.Add($"{Describe(prefix)} entry '{entry.FullName}' is larger than its declared size and was not trusted.");
                return -1;
            }

            Interlocked.Add(ref state.BytesRead, total);
            return total;
        }
        catch (InvalidDataException ex)
        {
            problems.Add($"{Describe(prefix)} entry '{entry.FullName}' is corrupt ({ex.Message}).");
            return -1;
        }
        catch (NotSupportedException ex)
        {
            problems.Add($"{Describe(prefix)} entry '{entry.FullName}' uses an unsupported format ({ex.Message}).");
            return -1;
        }
    }

    private bool PassesBombChecks(ZipArchiveEntry entry, long limit, string prefix, List<string> problems, InspectionState state)
    {
        if (entry.Length < 0 || entry.Length > Math.Min(limit, _options.MaxEntryUncompressedBytes) || entry.Length > int.MaxValue)
        {
            problems.Add($"{Describe(prefix)} entry '{entry.FullName}' is too large to inspect ({entry.Length} bytes).");
            return false;
        }

        if (entry.CompressedLength > 0 && entry.Length / Math.Max(entry.CompressedLength, 1) > _options.MaxCompressionRatio)
        {
            problems.Add($"{Describe(prefix)} entry '{entry.FullName}' has a suspicious compression ratio and was not expanded.");
            return false;
        }

        if (state.BytesRead + entry.Length > _options.MaxTotalUncompressedBytes)
        {
            if (!state.TotalLimitReported)
            {
                state.TotalLimitReported = true;
                problems.Add($"{Describe(prefix)} exceeds the total uncompressed size limit; remaining entries were not expanded.");
            }

            return false;
        }

        return true;
    }

    private static string Describe(string prefix) => prefix.Length == 0 ? "The archive" : $"Nested archive {prefix.TrimEnd('/', '!')}";
}
