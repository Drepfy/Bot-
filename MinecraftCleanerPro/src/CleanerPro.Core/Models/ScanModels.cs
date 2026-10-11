namespace CleanerPro.Core.Models;

/// <summary>A location that is part of a scan's approved scope.</summary>
public sealed record ScanRoot
{
    public required string Path { get; init; }

    public required ScanRootKind Kind { get; init; }

    /// <summary>Why this location is in scope; shown to the user before the scan starts.</summary>
    public required string Reason { get; init; }

    public string? InstallationId { get; init; }

    public string? InstallationName { get; init; }

    /// <summary>The installation's game directory (used for relative-path rules), when the root belongs to one.</summary>
    public string? InstallationRoot { get; init; }

    public bool Recursive { get; init; } = true;

    /// <summary>True when the root is a single file rather than a directory.</summary>
    public bool IsFile { get; init; }
}

/// <summary>The complete, explicit scope of a scan.</summary>
public sealed record ScanScope
{
    public required ScanMode Mode { get; init; }

    public IReadOnlyList<ScanRoot> Roots { get; init; } = [];

    public IReadOnlyList<string> ExcludedPaths { get; init; } = [];

    public bool IncludeSystemArtifactChecks { get; init; }

    public bool IncludeStartupInspection { get; init; }

    public bool IncludeProcessInspection { get; init; }
}

/// <summary>Snapshot of scan counters. Every value reflects work that actually happened.</summary>
public sealed record ScanStatistics
{
    public long FilesDiscovered { get; init; }

    public long FilesInspected { get; init; }

    public long FilesSkipped { get; init; }

    /// <summary>Files seen during enumeration whose type is not inspected (for example world data).</summary>
    public long FilesNotApplicable { get; init; }

    public long DirectoriesVisited { get; init; }

    public long ArchivesInspected { get; init; }

    public long ClassFilesInspected { get; init; }

    public long FilesHashed { get; init; }

    public long BytesHashed { get; init; }

    public long CacheHits { get; init; }

    public long Errors { get; init; }

    public long UniqueFilesFlagged { get; init; }

    public long DetectionEvents { get; init; }
}

public sealed record SkippedItem
{
    public required string Path { get; init; }

    public required SkipReason Reason { get; init; }

    public string? Detail { get; init; }
}

public sealed record ScanProgress
{
    public required ScanStage Stage { get; init; }

    public required ScanState State { get; init; }

    public long FilesDiscovered { get; init; }

    public long FilesInspected { get; init; }

    public long FilesSkipped { get; init; }

    public long FindingsCount { get; init; }

    public bool EnumerationComplete { get; init; }

    public string? CurrentPath { get; init; }

    /// <summary>
    /// Fraction of discovered files that have been processed. Only meaningful once enumeration is
    /// complete; before that the total is still growing, so the UI shows counts instead.
    /// </summary>
    public double? CompletedFraction =>
        EnumerationComplete && FilesDiscovered > 0
            ? Math.Clamp((double)(FilesInspected + FilesSkipped) / FilesDiscovered, 0, 1)
            : null;
}

/// <summary>A completed (or cancelled / failed) scan, persisted to history.</summary>
public sealed class ScanSession
{
    public required string Id { get; init; }

    public required ScanMode Mode { get; init; }

    public required DateTimeOffset StartedAtUtc { get; init; }

    public DateTimeOffset? CompletedAtUtc { get; set; }

    public ScanState State { get; set; } = ScanState.NotStarted;

    public required string AppVersion { get; init; }

    public required string RulesVersion { get; init; }

    public long RulesDatabaseVersion { get; init; }

    public string? ParentSessionId { get; init; }

    public required ScanScope Scope { get; init; }

    public ScanStatistics Statistics { get; set; } = new();

    public List<Finding> Findings { get; init; } = [];

    public List<SkippedItem> Skipped { get; init; } = [];

    /// <summary>Total skipped items, which can exceed <see cref="Skipped"/> when the list was capped.</summary>
    public long SkippedTotal { get; set; }

    public List<string> Errors { get; init; } = [];

    public List<string> Notes { get; init; } = [];

    public List<string> Limitations { get; init; } = [];

    public string? FailureMessage { get; set; }
}

/// <summary>An auditable record of a cleanup operation.</summary>
public sealed record OperationRecord
{
    public required string Id { get; init; }

    public required OperationType Type { get; init; }

    public required DateTimeOffset TimestampUtc { get; init; }

    public required bool Succeeded { get; init; }

    public required string Message { get; init; }

    public string? Path { get; init; }

    public string? Sha256 { get; init; }

    public string? SessionId { get; init; }

    public string? FindingId { get; init; }

    public string? QuarantineEntryId { get; init; }
}
