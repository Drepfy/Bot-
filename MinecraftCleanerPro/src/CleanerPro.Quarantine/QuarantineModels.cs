using CleanerPro.Core.Safety;

namespace CleanerPro.Quarantine;

public enum QuarantineEntryStatus
{
    Pending,
    Quarantined,
    Restored,
}

public enum IntegrityStatus
{
    Verified,
    PayloadMissing,
    HashMismatch,
    ManifestDamaged,
    NotApplicable,
}

/// <summary>Manifest describing one quarantined file. Stored as manifest.json next to the encoded payload.</summary>
public sealed record QuarantineEntry
{
    public required string Id { get; init; }

    public required string OriginalPath { get; init; }

    public required string OriginalName { get; init; }

    public required long Size { get; init; }

    /// <summary>SHA-256 of the original file content.</summary>
    public required string Sha256 { get; init; }

    /// <summary>SHA-256 of the encoded payload stored on disk.</summary>
    public required string PayloadSha256 { get; init; }

    /// <summary>Per-entry key used to encode the payload so it cannot be run or opened by accident (not encryption).</summary>
    public required string EncodingKey { get; init; }

    public int OriginalAttributes { get; init; }

    public DateTimeOffset? CreationTimeUtc { get; init; }

    public DateTimeOffset? LastWriteTimeUtc { get; init; }

    public required DateTimeOffset QuarantinedAtUtc { get; init; }

    /// <summary>Approved scan locations at quarantine time; restores must stay inside them.</summary>
    public IReadOnlyList<string> ApprovedRoots { get; init; } = [];

    public string? FindingId { get; init; }

    public string? SessionId { get; init; }

    public IReadOnlyList<string> RuleIds { get; init; } = [];

    public string? Classification { get; init; }

    public string? Family { get; init; }

    public QuarantineEntryStatus Status { get; init; }

    public DateTimeOffset? RestoredAtUtc { get; init; }

    public string? RestoredTo { get; init; }
}

public sealed record QuarantineRequest
{
    public required string Path { get; init; }

    public required IReadOnlyList<string> ApprovedRoots { get; init; }

    /// <summary>Hash recorded during the scan. If the file no longer matches, quarantine is refused.</summary>
    public string? ExpectedSha256 { get; init; }

    public long? ExpectedSize { get; init; }

    public string? FindingId { get; init; }

    public string? SessionId { get; init; }

    public IReadOnlyList<string> RuleIds { get; init; } = [];

    public string? Classification { get; init; }

    public string? Family { get; init; }
}

public sealed record QuarantineResult
{
    public required bool Succeeded { get; init; }

    public required string Message { get; init; }

    public required string Path { get; init; }

    public QuarantineEntry? Entry { get; init; }

    public PathBlockCode BlockCode { get; init; }

    /// <summary>True whenever the original file is still in place (always true on failure).</summary>
    public required bool OriginalPreserved { get; init; }
}

public enum RestoreMode
{
    OriginalLocation,
    OriginalLocationWithNewName,
    AlternateDirectory,
}

public sealed record RestoreRequest(string EntryId, RestoreMode Mode, string? AlternateDirectory = null);

public sealed record RestoreResult
{
    public required bool Succeeded { get; init; }

    public required string Message { get; init; }

    public string? RestoredPath { get; init; }

    /// <summary>The destination already contains a file; nothing was changed. Ask the user how to proceed.</summary>
    public bool Conflict { get; init; }

    public string? ConflictPath { get; init; }
}

public sealed record DeletionTarget(string EntryId, string OriginalPath, long Size, string Sha256, DateTimeOffset QuarantinedAtUtc);

/// <summary>The exact items the user is asked to confirm. The token is only valid for this set and expires.</summary>
public sealed record DeletionPlan(IReadOnlyList<DeletionTarget> Targets, string Token, DateTimeOffset ExpiresAtUtc);

public sealed record DeletionItemResult(string EntryId, bool Succeeded, string Message);

public sealed record DeletionResult(bool Executed, string Message, IReadOnlyList<DeletionItemResult> Items);

public sealed record RecoveryReport(IReadOnlyList<string> Actions)
{
    public bool AnythingRecovered => Actions.Count > 0;
}
