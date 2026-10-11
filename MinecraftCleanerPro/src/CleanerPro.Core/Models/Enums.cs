namespace CleanerPro.Core.Models;

/// <summary>
/// Evidence-based classification of a finding. Kept separate from confidence, severity,
/// reputation and the recommended action (see docs/DETECTION.md).
/// </summary>
public enum Classification
{
    /// <summary>A validated indicator matched a documented detection rule.</summary>
    KnownMatch,

    /// <summary>Multiple meaningful indicators support suspicion.</summary>
    HighConfidenceSuspicion,

    /// <summary>The available evidence is ambiguous and needs a human decision.</summary>
    NeedsReview,

    /// <summary>Trusted evidence supports legitimacy. Not an absolute guarantee.</summary>
    LikelyLegitimate,

    /// <summary>The item could not be reliably classified (for example, it could not be fully read).</summary>
    Unverified,
}

/// <summary>How strongly the collected evidence supports the classification.</summary>
public enum DetectionConfidence
{
    None,
    Low,
    Medium,
    High,
    Verified,
}

/// <summary>How harmful the matched family would be if the classification is correct.</summary>
public enum ThreatSeverity
{
    None,
    Informational,
    Low,
    Medium,
    High,
    Critical,
}

/// <summary>What is known about the file itself, independent of the rule that matched it.</summary>
public enum FileReputation
{
    Unknown,
    KnownMalicious,
    KnownCheat,
    Suspicious,
    KnownLegitimate,
    TrustedSignature,
}

/// <summary>The action the application suggests. Permanent deletion is never recommended automatically.</summary>
public enum RecommendedAction
{
    NoAction,
    ManualReview,
    Quarantine,
    QuarantineAndCheckSystem,
}

/// <summary>Weight of an individual evidence item.</summary>
public enum EvidenceStrength
{
    Weak,
    Moderate,
    Strong,
    Definitive,
}

/// <summary>The kind of indicator that produced an evidence item.</summary>
public enum IndicatorType
{
    Sha256,
    Sha1,
    ModId,
    ClassPackagePrefix,
    ArchiveEntry,
    ArchiveEntryPattern,
    BytecodeSignature,
    FileName,
    FileNamePattern,
    RelativePath,
    DirectoryName,
    KnownLocation,
    ManifestAttribute,
    StartupCommandPattern,
    AuthenticodeSignature,
    Metadata,

    /// <summary>An entrypoint key declared in Fabric/Quilt mod metadata (for example "meteor" for Meteor Client add-ons).</summary>
    ModEntrypoint,
}

/// <summary>Detection categories that can be enabled or disabled in configuration.</summary>
public enum DetectionCategory
{
    HackedClient,
    GhostClient,
    CombatAutomation,
    AimAssistance,
    AutoClicker,
    ReachModification,
    VelocityManipulation,
    XRayOrEsp,
    MovementOrTimer,
    InventoryAutomation,
    InjectedModule,
    Malware,
    MaliciousLauncher,
    CheatConfiguration,
    GameplayAutomation,
    LegitimateSoftware,
    TestSignature,
}

/// <summary>Lifecycle of a finding with respect to cleanup.</summary>
public enum CleanupStatus
{
    NotActioned,
    Quarantined,
    QuarantineFailed,
    Restored,
    PermanentlyDeleted,
    Blocked,
    Skipped,
}

public enum ScanMode
{
    Quick,
    Full,
    Custom,
    Verification,
}

public enum ScanState
{
    NotStarted,
    Running,
    Paused,
    Completed,
    Cancelled,
    Failed,
}

public enum ScanStage
{
    Idle,
    DiscoveringLocations,
    EnumeratingFiles,
    InspectingFiles,
    CheckingSystemArtifacts,
    Finalizing,
    Completed,
}

public enum SkipReason
{
    Excluded,
    TooLarge,
    AccessDenied,
    ReparsePoint,
    NotFound,
    ChangedDuringScan,
    ArchiveLimitExceeded,
    CorruptArchive,
    Unreadable,
    UnsupportedType,
    DepthLimit,
    Cancelled,
    TrustedExclusion,
}

public enum ModLoader
{
    Unknown,
    Vanilla,
    Fabric,
    Quilt,
    Forge,
    NeoForge,
    LiteLoader,
    Other,
}

public enum LauncherKind
{
    OfficialLauncher,
    PrismLauncher,
    MultiMC,
    ModrinthApp,
    CurseForge,
    ATLauncher,
    GDLauncher,
    LunarClient,
    BadlionClient,
    FeatherClient,
    Custom,

    /// <summary>A launcher whose data folder uses the MultiMC instance format (forks such as PollyMC or UltimMC).</summary>
    MultiMcCompatible,

    TechnicLauncher,

    /// <summary>A game folder found by the folder search that no known launcher lists (portable launchers, copies, other drives).</summary>
    Unlisted,
}

public enum ScanRootKind
{
    Installation,
    CustomDirectory,
    SystemArtifactLocation,

    /// <summary>A file referenced by launch settings (for example a Java agent), scanned wherever it is stored.</summary>
    ReferencedFile,

    /// <summary>Common download locations (Downloads, Desktop) checked for cheat and malware files.</summary>
    DownloadLocation,
}

public enum OperationType
{
    Quarantine,
    Restore,
    PermanentDelete,
    Recovery,
}
