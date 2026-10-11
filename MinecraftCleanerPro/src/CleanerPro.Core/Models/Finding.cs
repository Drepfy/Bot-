using System.Security.Cryptography;
using System.Text;

namespace CleanerPro.Core.Models;

/// <summary>
/// One flagged file or directory. A finding aggregates every rule match for the same item so a
/// file matched by several rules is still counted once.
/// </summary>
public sealed class Finding
{
    public required string Id { get; init; }

    public required string Path { get; init; }

    public bool IsDirectory { get; init; }

    public bool IsSystemArtifact { get; init; }

    public long? SizeBytes { get; init; }

    public DateTimeOffset? LastWriteUtc { get; init; }

    public string? Sha256 { get; init; }

    public string? Sha1 { get; init; }

    public string? InstallationId { get; init; }

    public string? InstallationName { get; init; }

    public ModIdentity? Identity { get; init; }

    public required Classification Classification { get; set; }

    public required DetectionConfidence Confidence { get; set; }

    public required ThreatSeverity Severity { get; set; }

    public required FileReputation Reputation { get; set; }

    public required RecommendedAction RecommendedAction { get; set; }

    public required string ConfidenceRationale { get; set; }

    public List<RuleMatch> RuleMatches { get; init; } = [];

    public List<Evidence> Evidence { get; init; } = [];

    public List<string> Limitations { get; init; } = [];

    public CleanupStatus CleanupStatus { get; set; } = CleanupStatus.NotActioned;

    public string? CleanupMessage { get; set; }

    public string? QuarantineEntryId { get; set; }

    /// <summary>
    /// True for findings that cannot be moved to quarantine safely, such as registry entries, environment variables
    /// or a line inside a launcher's settings file. <see cref="ManualCleanupGuidance"/> explains what to do instead.
    /// </summary>
    public bool RequiresManualCleanup { get; init; }

    public string? ManualCleanupGuidance { get; init; }

    /// <summary>Stable identifier derived from the normalized path and content hash.</summary>
    public static string CreateId(string normalizedPathKey, string? contentHash)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(normalizedPathKey + "|" + (contentHash ?? "-")));
        return Convert.ToHexString(bytes, 0, 12).ToLowerInvariant();
    }
}
