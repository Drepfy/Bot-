using CleanerPro.Core.Models;

namespace CleanerPro.Detection.Rules;

/// <summary>
/// JSON document format of the detection rule database (rules/cleanerpro-rules.json).
/// Rule data is never executed; it only describes indicators and how they combine.
/// </summary>
public sealed class RuleDatabaseDocument
{
    public const int SupportedFormatVersion = 1;

    public int FormatVersion { get; set; }

    /// <summary>Monotonically increasing version used for anti-rollback.</summary>
    public long DatabaseVersion { get; set; }

    public string DisplayVersion { get; set; } = string.Empty;

    public DateTimeOffset PublishedAt { get; set; }

    /// <summary>Downloaded updates must expire; the bundled database may leave this null.</summary>
    public DateTimeOffset? ExpiresAt { get; set; }

    public string? Description { get; set; }

    public List<RuleDefinition> Rules { get; set; } = [];
}

public enum RuleTarget
{
    /// <summary>Readable ZIP/JAR archives (content and metadata).</summary>
    Archive,

    /// <summary>Any regular file (name, path, hash).</summary>
    File,

    /// <summary>Directories (name and location).</summary>
    Directory,

    /// <summary>Per-user startup entries (registry Run key values).</summary>
    StartupEntry,
}

public sealed class RuleDefinition
{
    public string Id { get; set; } = string.Empty;

    public int Version { get; set; }

    public string Family { get; set; } = string.Empty;

    public DetectionCategory Category { get; set; }

    /// <summary>Potential harm if the classification is correct.</summary>
    public ThreatSeverity Severity { get; set; }

    public List<RuleTarget> AppliesTo { get; set; } = [];

    /// <summary>Optional file extension filter (".jar"). Empty means every file type allowed by <see cref="AppliesTo"/>.</summary>
    public List<string> FileExtensions { get; set; } = [];

    /// <summary>Optional platform filter ("windows", "linux", "macos"). Empty means all platforms.</summary>
    public List<string> Platforms { get; set; } = [];

    /// <summary>Heuristic rules are generic patterns; legitimacy evidence may override them.</summary>
    public bool Heuristic { get; set; }

    public List<IndicatorDefinition> Indicators { get; set; } = [];

    public ClassificationDefinition Classification { get; set; } = new();

    public RecommendedAction RecommendedAction { get; set; } = RecommendedAction.ManualReview;

    public FileReputation ReputationOnMatch { get; set; } = FileReputation.Suspicious;

    public string ConfidenceRationale { get; set; } = string.Empty;

    public string? FalsePositiveNotes { get; set; }

    public string? Limitations { get; set; }

    public List<SourceReference> Sources { get; set; } = [];

    /// <summary>Date (yyyy-MM-dd) the indicators were last verified against the sources.</summary>
    public string? VerifiedOn { get; set; }
}

public sealed class IndicatorDefinition
{
    public string Id { get; set; } = string.Empty;

    public IndicatorType Type { get; set; }

    public string? Value { get; set; }

    /// <summary>For <see cref="IndicatorType.ModId"/>: restrict to a loader's metadata format.</summary>
    public ModLoader? Loader { get; set; }

    /// <summary>For <see cref="IndicatorType.ManifestAttribute"/>: the manifest attribute name.</summary>
    public string? Attribute { get; set; }

    /// <summary>For file-name indicators: the file must be directly inside this expanded location template.</summary>
    public string? LocationTemplate { get; set; }

    /// <summary>For <see cref="IndicatorType.DirectoryName"/>: the directory must be directly inside an installation root.</summary>
    public bool AtInstallationRoot { get; set; }

    /// <summary>For <see cref="IndicatorType.KnownLocation"/>: "File", "Directory" or "Any".</summary>
    public string? Expect { get; set; }

    public EvidenceStrength Strength { get; set; } = EvidenceStrength.Weak;

    public string? Description { get; set; }

    public BytecodeSignatureDefinition? Bytecode { get; set; }
}

public enum BytecodeMatchMode
{
    /// <summary>
    /// Every instruction whose opcode appears at the current signature position must match it, in order
    /// (nekodetector "SIG1" semantics).
    /// </summary>
    OrderedOpcodeFilter,

    /// <summary>Like <see cref="OrderedOpcodeFilter"/>, but may start at any instruction (nekodetector "SIG2").</summary>
    OrderedOpcodeFilterAnyStart,

    /// <summary>The instructions must appear contiguously, including integer operands.</summary>
    Contiguous,
}

public sealed class BytecodeSignatureDefinition
{
    public BytecodeMatchMode Mode { get; set; }

    public List<InstructionPattern> Instructions { get; set; } = [];
}

public sealed class InstructionPattern
{
    /// <summary>JVM mnemonic such as "INVOKESTATIC", "NEW", "BIPUSH", "DUP".</summary>
    public string Op { get; set; } = string.Empty;

    /// <summary>For NEW / CHECKCAST / ANEWARRAY / INSTANCEOF: internal class name.</summary>
    public string? Type { get; set; }

    public string? Owner { get; set; }

    public string? Name { get; set; }

    public string? Desc { get; set; }

    /// <summary>For BIPUSH / SIPUSH: the operand value.</summary>
    public int? Operand { get; set; }
}

public sealed class ClassificationDefinition
{
    public List<ConditionDefinition> KnownMatch { get; set; } = [];

    public List<ConditionDefinition> HighConfidenceSuspicion { get; set; } = [];

    public List<ConditionDefinition> NeedsReview { get; set; } = [];

    public List<ConditionDefinition> LikelyLegitimate { get; set; } = [];
}

/// <summary>An alternative: every part that is present must be satisfied.</summary>
public sealed class ConditionDefinition
{
    public List<string>? All { get; set; }

    public List<string>? Any { get; set; }

    public List<CountDefinition>? Counts { get; set; }

    /// <summary>
    /// None of these indicators may match. Only allowed together with a positive part (all/any/counts), and never
    /// satisfied when the item could not be fully inspected, because then a missing indicator proves nothing.
    /// </summary>
    public List<string>? None { get; set; }
}

public sealed class CountDefinition
{
    public int AtLeast { get; set; }

    public List<string> Of { get; set; } = [];
}
