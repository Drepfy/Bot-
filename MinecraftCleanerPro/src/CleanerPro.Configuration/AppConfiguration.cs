using System.Text.Json;
using System.Text.Json.Serialization;
using CleanerPro.Core.Models;

namespace CleanerPro.Configuration;

/// <summary>
/// The complete, strongly typed configuration stored in %LocalAppData%\MinecraftCleanerPro\config.json.
/// Every setting is documented in docs/CONFIGURATION.md.
/// </summary>
public sealed class AppConfiguration
{
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; set; } = CurrentSchemaVersion;

    public ScanSettings Scan { get; set; } = new();

    public DetectionSettings Detection { get; set; } = new();

    public PerformanceSettings Performance { get; set; } = new();

    public RuleUpdateSettings RuleUpdates { get; set; } = new();

    public QuarantineSettings Quarantine { get; set; } = new();

    public ReportSettings Reports { get; set; } = new();

    public LoggingSettings Logging { get; set; } = new();

    public PrivacySettings Privacy { get; set; } = new();

    public SafetySettings Safety { get; set; } = new();

    public StartupSettings Startup { get; set; } = new();

    public InterfaceSettings Interface { get; set; } = new();

    public AccessibilitySettings Accessibility { get; set; } = new();

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? UnknownSettings { get; set; }
}

public abstract class SettingsSection
{
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? UnknownSettings { get; set; }
}

public sealed class ScanSettings : SettingsSection
{
    /// <summary>Scan installations found by launcher discovery.</summary>
    public bool IncludeDiscoveredInstallations { get; set; } = true;

    /// <summary>Discovered installation ids the user unticked. They stay listed but are not scanned.</summary>
    public List<string> DisabledInstallationIds { get; set; } = [];

    /// <summary>Additional directories chosen by the user (absolute paths).</summary>
    public List<string> CustomDirectories { get; set; } = [];

    /// <summary>Absolute directories that are never scanned.</summary>
    public List<string> ExcludedDirectories { get; set; } = [];

    /// <summary>Directory names skipped anywhere inside an installation (large, irrelevant data).</summary>
    public List<string> ExcludedDirectoryNames { get; set; } = ["saves", "screenshots"];

    /// <summary>File extensions whose content is inspected. Other files are counted but not opened.</summary>
    public List<string> FileExtensions { get; set; } =
        [".jar", ".zip", ".litemod", ".json", ".toml", ".cfg", ".txt", ".properties", ".exe", ".dll", ".bat", ".cmd", ".ref"];

    public int MaxFileSizeMegabytes { get; set; } = 256;

    public int MaxDirectoryDepth { get; set; } = 24;

    /// <summary>When false (default) symbolic links and junctions are never followed.</summary>
    public bool FollowDirectoryLinks { get; set; }

    public bool InspectArchives { get; set; } = true;

    public ArchiveLimits ArchiveLimits { get; set; } = new();

    /// <summary>Static (non-executing) inspection of Java class files for documented bytecode signatures.</summary>
    public bool InspectBytecode { get; set; } = true;

    public int MaxClassFileKilobytes { get; set; } = 2048;

    /// <summary>Check documented malware persistence locations outside Minecraft folders (read-only).</summary>
    public bool InspectSystemArtifacts { get; set; } = true;

    /// <summary>Read (never modify) per-user startup entries for documented malware persistence.</summary>
    public bool InspectStartupEntries { get; set; } = true;

    /// <summary>List running processes whose executable lives in a flagged location (read-only).</summary>
    public bool InspectRunningProcesses { get; set; }
}

public sealed class ArchiveLimits : SettingsSection
{
    public int MaxEntries { get; set; } = 50_000;

    public int MaxTotalUncompressedMegabytes { get; set; } = 1024;

    public int MaxEntryUncompressedMegabytes { get; set; } = 64;

    public int MaxCompressionRatio { get; set; } = 250;

    public int MaxNestedArchiveDepth { get; set; } = 2;

    public int MaxNestedArchiveMegabytes { get; set; } = 64;
}

public sealed class DetectionSettings : SettingsSection
{
    public List<DetectionCategory> EnabledCategories { get; set; } = Enum.GetValues<DetectionCategory>().ToList();

    /// <summary>Compute SHA-256 for inspected files. Required for hash rules and for quarantine integrity.</summary>
    public bool HashVerification { get; set; } = true;

    /// <summary>Also compute SHA-1, which some public advisories use for indicators.</summary>
    public bool ComputeSha1 { get; set; } = true;

    public bool MetadataInspection { get; set; } = true;

    /// <summary>Verify Authenticode signatures of executables found in scanned locations (Windows, offline).</summary>
    public bool VerifyDigitalSignatures { get; set; } = true;

    /// <summary>List files classified as likely legitimate in the findings table.</summary>
    public bool ReportLikelyLegitimate { get; set; }

    /// <summary>Reuse results for files whose path, size, timestamp and hash are unchanged since a previous scan with the same rules.</summary>
    public bool ReuseVerifiedResults { get; set; } = true;

    public List<TrustedExclusion> TrustedExclusions { get; set; } = [];
}

public sealed class TrustedExclusion : SettingsSection
{
    /// <summary>SHA-256 of a file the user has reviewed and trusts.</summary>
    public string? Sha256 { get; set; }

    /// <summary>Optional absolute file path the exclusion is limited to.</summary>
    public string? Path { get; set; }

    public string? Note { get; set; }
}

public sealed class PerformanceSettings : SettingsSection
{
    /// <summary>Uses one worker, small buffers and short pauses between files to minimise impact.</summary>
    public bool LowResourceMode { get; set; }

    public int MaxParallelTasks { get; set; } = 2;

    public int MaxQueuedFiles { get; set; } = 512;

    /// <summary>Upper bound for in-memory archive buffers (nested archives and class files) across all workers.</summary>
    public int MaxMemoryMegabytes { get; set; } = 512;

    /// <summary>Run scan workers at below-normal priority (Windows background mode for CPU and disk).</summary>
    public bool ReducedPriority { get; set; } = true;

    public int HashBufferKilobytes { get; set; } = 1024;
}

public sealed class RuleUpdateSettings : SettingsSection
{
    /// <summary>Online rule updates are off by default and also require privacy.offlineMode = false.</summary>
    public bool Enabled { get; set; }

    /// <summary>HTTPS base URL that serves rules.json and rules.json.sig. No trusted source is configured by default.</summary>
    public string? Endpoint { get; set; }

    public int TimeoutSeconds { get; set; } = 30;

    public int MaxDownloadKilobytes { get; set; } = 4096;

    /// <summary>Base64 SubjectPublicKeyInfo (ECDSA P-256) keys trusted to sign rule databases, in addition to built-in keys.</summary>
    public List<string> AdditionalTrustedPublicKeys { get; set; } = [];
}

public sealed class QuarantineSettings : SettingsSection
{
    /// <summary>Absolute quarantine directory. Null uses %LocalAppData%\MinecraftCleanerPro\quarantine.</summary>
    public string? Directory { get; set; }

    /// <summary>Mandatory: every quarantined copy is verified by SHA-256 before the original is removed.</summary>
    public bool VerifyIntegrity { get; set; } = true;
}

public enum ReportFormat
{
    Html,
    Txt,
    Json,
}

public sealed class ReportSettings : SettingsSection
{
    /// <summary>Absolute report directory. Null uses %LocalAppData%\MinecraftCleanerPro\reports.</summary>
    public string? Directory { get; set; }

    public ReportFormat DefaultFormat { get; set; } = ReportFormat.Html;

    public bool RedactPersonalPathsByDefault { get; set; } = true;

    public int RetentionDays { get; set; } = 180;

    public int MaxReports { get; set; } = 200;

    public int HistoryRetentionDays { get; set; } = 365;

    public int MaxHistorySessions { get; set; } = 200;
}

public sealed class LoggingSettings : SettingsSection
{
    /// <summary>Trace, Debug, Information, Warning, Error, Critical or None.</summary>
    public string Level { get; set; } = "Information";

    public int RetentionDays { get; set; } = 14;

    public int MaxFileMegabytes { get; set; } = 10;

    public int MaxTotalMegabytes { get; set; } = 100;
}

public sealed class PrivacySettings : SettingsSection
{
    /// <summary>When true (default) the application never makes network requests.</summary>
    public bool OfflineMode { get; set; } = true;

    public bool IncludeUserNameInReports { get; set; }

    public bool IncludeMachineNameInReports { get; set; }
}

public sealed class SafetySettings : SettingsSection
{
    /// <summary>Ask before quarantining. Quarantine is reversible, so this may be turned off.</summary>
    public bool ConfirmQuarantine { get; set; } = true;

    /// <summary>Ask before restoring a quarantined file.</summary>
    public bool ConfirmRestore { get; set; } = true;

    /// <summary>Mandatory. Permanent deletion always requires explicit confirmation of the exact targets.</summary>
    public bool ConfirmPermanentDeletion { get; set; } = true;

    /// <summary>Mandatory. Every filesystem modification is checked by the path safety policy.</summary>
    public bool EnforcePathValidation { get; set; } = true;
}

public sealed class StartupSettings : SettingsSection
{
    /// <summary>Automatic scanning when the application starts. Manual by default.</summary>
    public bool ScanOnLaunch { get; set; }

    public ScanMode ScanModeOnLaunch { get; set; } = ScanMode.Quick;

    public bool CheckRuleUpdatesOnLaunch { get; set; }
}

public enum ThemePreference
{
    System,
    Light,
    Dark,
}

public sealed class InterfaceSettings : SettingsSection
{
    public ThemePreference Theme { get; set; } = ThemePreference.System;

    public bool ShowScanScopeBeforeScan { get; set; } = true;

    public bool ConfirmExitDuringScan { get; set; } = true;
}

public sealed class AccessibilitySettings : SettingsSection
{
    /// <summary>Multiplier for all text (0.8 – 2.0).</summary>
    public double FontScale { get; set; } = 1.0;

    /// <summary>Force the high-contrast palette even if Windows high contrast is off.</summary>
    public bool HighContrast { get; set; }

    public bool ReduceMotion { get; set; } = true;

    public bool ShowTooltips { get; set; } = true;
}

/// <summary>Resolves configured locations against the defaults.</summary>
public static class EffectiveLocations
{
    public static string QuarantineDirectory(AppConfiguration config, Infrastructure.AppPaths paths) =>
        string.IsNullOrWhiteSpace(config.Quarantine.Directory) ? paths.DefaultQuarantineDirectory : Path.GetFullPath(config.Quarantine.Directory);

    public static string ReportsDirectory(AppConfiguration config, Infrastructure.AppPaths paths) =>
        string.IsNullOrWhiteSpace(config.Reports.Directory) ? paths.DefaultReportsDirectory : Path.GetFullPath(config.Reports.Directory);
}
