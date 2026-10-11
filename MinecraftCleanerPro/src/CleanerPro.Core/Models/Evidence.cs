namespace CleanerPro.Core.Models;

/// <summary>A single, traceable piece of evidence collected for a finding.</summary>
public sealed record Evidence
{
    public required IndicatorType Kind { get; init; }

    /// <summary>The rule that defined the indicator, if any.</summary>
    public string? RuleId { get; init; }

    /// <summary>The indicator identifier inside the rule.</summary>
    public string? IndicatorId { get; init; }

    /// <summary>Human-readable description of what was observed.</summary>
    public required string Description { get; init; }

    /// <summary>The concrete value that matched (hash, mod id, archive entry name...).</summary>
    public string? MatchedValue { get; init; }

    /// <summary>Where inside the file the value was observed (for example an archive entry).</summary>
    public string? Location { get; init; }

    public EvidenceStrength Strength { get; init; } = EvidenceStrength.Weak;
}

/// <summary>A citation backing a detection rule.</summary>
public sealed record SourceReference
{
    public required string Title { get; init; }

    public required string Url { get; init; }

    /// <summary>Date (yyyy-MM-dd) on which the source was retrieved and checked.</summary>
    public string? Retrieved { get; init; }
}

/// <summary>Records which rule matched a file and why.</summary>
public sealed record RuleMatch
{
    public required string RuleId { get; init; }

    public required int RuleVersion { get; init; }

    public required string Family { get; init; }

    public required DetectionCategory Category { get; init; }

    public required Classification Classification { get; init; }

    public required ThreatSeverity Severity { get; init; }

    public required RecommendedAction RecommendedAction { get; init; }

    public IReadOnlyList<string> MatchedIndicatorIds { get; init; } = [];

    public IReadOnlyList<SourceReference> Sources { get; init; } = [];

    public string? VerifiedOn { get; init; }

    public string? ConfidenceRationale { get; init; }

    public string? FalsePositiveNotes { get; init; }

    public string? Limitations { get; init; }
}

/// <summary>Identity information extracted from mod metadata.</summary>
public sealed record ModIdentity
{
    public ModLoader Loader { get; init; }

    public string? ModId { get; init; }

    public string? Name { get; init; }

    public string? Version { get; init; }

    public string? MetadataFile { get; init; }

    /// <summary>Entrypoint keys declared in Fabric/Quilt metadata (for example "main", "client" or "meteor").</summary>
    public IReadOnlyList<string> Entrypoints { get; init; } = [];
}
