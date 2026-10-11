using CleanerPro.Core.Models;
using CleanerPro.Infrastructure.Platform;

namespace CleanerPro.Detection.Matching;

/// <summary>
/// Everything the scanner observed about one item (file, directory, startup entry). Rules are matched
/// against observations only; the detection engine never opens or runs files itself.
/// </summary>
public sealed class ItemObservation
{
    public required string Path { get; init; }

    public required string Name { get; init; }

    public bool IsDirectory { get; init; }

    public bool IsSystemArtifact { get; init; }

    public string? InstallationId { get; init; }

    public string? InstallationName { get; init; }

    public string? InstallationRoot { get; init; }

    /// <summary>Path relative to the installation root with '/' separators, when inside an installation.</summary>
    public string? RelativePath { get; init; }

    public long? Size { get; set; }

    public DateTimeOffset? LastWriteUtc { get; set; }

    public string? Sha256 { get; set; }

    public string? Sha1 { get; set; }

    public ArchiveObservation? Archive { get; set; }

    /// <summary>"ruleId/indicatorId" keys of known-location indicators that resolve to this item.</summary>
    public HashSet<string> KnownLocationHits { get; } = new(StringComparer.Ordinal);

    public SignatureInfo? Signature { get; set; }

    public StartupEntry? StartupEntry { get; init; }

    /// <summary>Reasons the item could not be fully inspected (corrupt archive, limits...).</summary>
    public List<string> InspectionProblems { get; } = [];

    public bool InspectionIncomplete => InspectionProblems.Count > 0;

    public string Extension => IsDirectory ? string.Empty : System.IO.Path.GetExtension(Name).ToLowerInvariant();

    /// <summary>
    /// True when the file starts with a ZIP signature although its name does not end in .jar/.zip (for example
    /// "client.jar.disabled" or a jar renamed to ".dat"). Such files are inspected and matched like jars.
    /// </summary>
    public bool ContentIsArchive { get; set; }

    /// <summary>Whether a rule's extension filter accepts this item, treating archives detected by content as jars.</summary>
    public bool HasExtension(IReadOnlyCollection<string> extensions)
    {
        if (extensions.Count == 0 || extensions.Contains(Extension, StringComparer.OrdinalIgnoreCase))
        {
            return true;
        }

        return ContentIsArchive && (extensions.Contains(".jar", StringComparer.OrdinalIgnoreCase) || extensions.Contains(".zip", StringComparer.OrdinalIgnoreCase));
    }
}

/// <summary>Static metadata extracted from a ZIP/JAR archive.</summary>
public sealed class ArchiveObservation
{
    public HashSet<string> Entries { get; } = new(StringComparer.Ordinal);

    /// <summary>Every package prefix ("a/", "a/b/") that contains at least one class.</summary>
    public HashSet<string> ClassPackages { get; } = new(StringComparer.Ordinal);

    public List<ModIdentity> Mods { get; } = [];

    public Dictionary<string, string> ManifestAttributes { get; } = new(StringComparer.OrdinalIgnoreCase);

    /// <summary>Bytecode signature key → class entry where it was found.</summary>
    public Dictionary<string, string> BytecodeHits { get; } = new(StringComparer.Ordinal);

    public List<string> NestedArchives { get; } = [];

    public int EntryCount { get; set; }

    public int ClassCount { get; set; }

    public int ClassFilesInspected { get; set; }

    public int ClassFilesUnparseable { get; set; }

    public bool HasJarSignatureFiles { get; set; }

    public void AddEntry(string name)
    {
        Entries.Add(name);
        if (!name.EndsWith(".class", StringComparison.Ordinal))
        {
            return;
        }

        ClassCount++;
        var slash = name.LastIndexOf('/');
        while (slash > 0)
        {
            if (!ClassPackages.Add(name[..(slash + 1)]))
            {
                break; // Parent prefixes were already added for an earlier class.
            }

            slash = name.LastIndexOf('/', slash - 1);
        }
    }
}
