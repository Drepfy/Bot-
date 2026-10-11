using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using CleanerPro.Core.Safety;

namespace CleanerPro.Configuration;

public enum ConfigIssueSeverity
{
    Warning,
    Error,
}

/// <summary>A validation problem with the exact setting and a hint on how to correct it.</summary>
public sealed record ConfigIssue(ConfigIssueSeverity Severity, string Setting, string Message, string HowToFix);

public sealed record ConfigValidationResult(IReadOnlyList<ConfigIssue> Issues)
{
    public bool IsValid => Issues.All(i => i.Severity != ConfigIssueSeverity.Error);

    public IEnumerable<ConfigIssue> Errors => Issues.Where(i => i.Severity == ConfigIssueSeverity.Error);

    public IEnumerable<ConfigIssue> Warnings => Issues.Where(i => i.Severity == ConfigIssueSeverity.Warning);
}

/// <summary>Validates a configuration. Unsafe values and attempts to weaken mandatory protections are errors.</summary>
public sealed partial class ConfigValidator
{
    private static readonly string[] LogLevels = ["Trace", "Debug", "Information", "Warning", "Error", "Critical", "None"];

    private readonly PathSafetyPolicy _pathPolicy;

    public ConfigValidator(PathSafetyPolicy pathPolicy)
    {
        _pathPolicy = pathPolicy;
    }

    public ConfigValidationResult Validate(AppConfiguration config)
    {
        var issues = new List<ConfigIssue>();

        void Error(string setting, string message, string fix) => issues.Add(new ConfigIssue(ConfigIssueSeverity.Error, setting, message, fix));
        void Warn(string setting, string message, string fix) => issues.Add(new ConfigIssue(ConfigIssueSeverity.Warning, setting, message, fix));

        void Range(string setting, double value, double min, double max)
        {
            if (value < min || value > max)
            {
                Error(setting, $"Value {value} is outside the allowed range {min} – {max}.", $"Set '{setting}' to a value between {min} and {max}.");
            }
        }

        if (config.SchemaVersion != AppConfiguration.CurrentSchemaVersion)
        {
            Error("schemaVersion", $"Schema version {config.SchemaVersion} is not supported (expected {AppConfiguration.CurrentSchemaVersion}).",
                "Use 'Restore Defaults' or set schemaVersion to the supported value.");
        }

        ReportUnknown(issues, string.Empty, config.UnknownSettings, critical: false);
        ReportUnknown(issues, "scan", config.Scan?.UnknownSettings, critical: false);
        ReportUnknown(issues, "scan.archiveLimits", config.Scan?.ArchiveLimits?.UnknownSettings, critical: false);
        ReportUnknown(issues, "detection", config.Detection?.UnknownSettings, critical: false);
        ReportUnknown(issues, "performance", config.Performance?.UnknownSettings, critical: false);
        ReportUnknown(issues, "ruleUpdates", config.RuleUpdates?.UnknownSettings, critical: true);
        ReportUnknown(issues, "quarantine", config.Quarantine?.UnknownSettings, critical: true);
        ReportUnknown(issues, "reports", config.Reports?.UnknownSettings, critical: false);
        ReportUnknown(issues, "logging", config.Logging?.UnknownSettings, critical: false);
        ReportUnknown(issues, "privacy", config.Privacy?.UnknownSettings, critical: true);
        ReportUnknown(issues, "safety", config.Safety?.UnknownSettings, critical: true);
        ReportUnknown(issues, "startup", config.Startup?.UnknownSettings, critical: false);
        ReportUnknown(issues, "interface", config.Interface?.UnknownSettings, critical: false);
        ReportUnknown(issues, "accessibility", config.Accessibility?.UnknownSettings, critical: false);

        if (config.Scan is null || config.Detection is null || config.Performance is null || config.RuleUpdates is null ||
            config.Quarantine is null || config.Reports is null || config.Logging is null || config.Privacy is null ||
            config.Safety is null || config.Startup is null || config.Interface is null || config.Accessibility is null ||
            config.Scan.ArchiveLimits is null)
        {
            Error("(root)", "One or more configuration sections are null.", "Remove the null section so the default is used, or use 'Restore Defaults'.");
            return new ConfigValidationResult(issues);
        }

        // ---- scan ----
        var scan = config.Scan;
        Range("scan.maxFileSizeMegabytes", scan.MaxFileSizeMegabytes, 1, 4096);
        Range("scan.maxDirectoryDepth", scan.MaxDirectoryDepth, 1, 256);
        Range("scan.maxClassFileKilobytes", scan.MaxClassFileKilobytes, 16, 65536);
        ValidatePathList(issues, "scan.customDirectories", scan.CustomDirectories, warnIfMissing: true);
        ValidatePathList(issues, "scan.excludedDirectories", scan.ExcludedDirectories, warnIfMissing: false);
        foreach (var directory in scan.CustomDirectories ?? [])
        {
            if (!string.IsNullOrWhiteSpace(directory) && Path.IsPathFullyQualified(directory) &&
                string.Equals(Path.GetPathRoot(directory)?.TrimEnd('\\', '/'), directory.TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase))
            {
                Warn("scan.customDirectories", $"'{directory}' is an entire drive. Scanning it can take a long time.",
                    "Prefer the specific folder that contains your Minecraft files.");
            }
        }

        foreach (var name in scan.ExcludedDirectoryNames ?? [])
        {
            if (string.IsNullOrWhiteSpace(name) || name.IndexOfAny(['\\', '/', '*', '?', ':']) >= 0)
            {
                Error("scan.excludedDirectoryNames", $"'{name}' is not a plain directory name.", "Use names such as \"saves\" without slashes or wildcards.");
            }
        }

        if (scan.FileExtensions is null || scan.FileExtensions.Count == 0)
        {
            Error("scan.fileExtensions", "At least one file extension must be inspected.", "Add \".jar\" (mods) at minimum.");
        }
        else
        {
            foreach (var extension in scan.FileExtensions)
            {
                if (string.IsNullOrWhiteSpace(extension) || !ExtensionPattern().IsMatch(extension))
                {
                    Error("scan.fileExtensions", $"'{extension}' is not a valid extension.", "Use the form \".jar\" (a dot followed by letters or digits).");
                }
            }

            if (!scan.FileExtensions.Contains(".jar", StringComparer.OrdinalIgnoreCase))
            {
                Warn("scan.fileExtensions", "'.jar' is not inspected, so mods and most cheat clients will not be detected.", "Add \".jar\" back to the list.");
            }
        }

        if (scan.FollowDirectoryLinks)
        {
            Warn("scan.followDirectoryLinks", "Links will be followed, but only when their target is inside another approved scan location.",
                "Leave this off unless your Minecraft folders are intentionally linked.");
        }

        var limits = scan.ArchiveLimits;
        Range("scan.archiveLimits.maxEntries", limits.MaxEntries, 100, 1_000_000);
        Range("scan.archiveLimits.maxTotalUncompressedMegabytes", limits.MaxTotalUncompressedMegabytes, 1, 16384);
        Range("scan.archiveLimits.maxEntryUncompressedMegabytes", limits.MaxEntryUncompressedMegabytes, 1, 2048);
        Range("scan.archiveLimits.maxCompressionRatio", limits.MaxCompressionRatio, 10, 10000);
        Range("scan.archiveLimits.maxNestedArchiveDepth", limits.MaxNestedArchiveDepth, 0, 4);
        Range("scan.archiveLimits.maxNestedArchiveMegabytes", limits.MaxNestedArchiveMegabytes, 1, 512);

        // ---- detection ----
        var detection = config.Detection;
        if (detection.EnabledCategories is null || detection.EnabledCategories.Count == 0)
        {
            Warn("detection.enabledCategories", "No detection categories are enabled, so nothing will be detected.", "Enable at least one category.");
        }

        if (!detection.HashVerification)
        {
            Warn("detection.hashVerification", "Hash-based rules cannot match while hashing is off. Files are still hashed before quarantine.",
                "Turn hash verification back on for complete detection.");
        }

        for (var i = 0; i < (detection.TrustedExclusions?.Count ?? 0); i++)
        {
            var exclusion = detection.TrustedExclusions![i];
            var setting = $"detection.trustedExclusions[{i}]";
            if (exclusion is null)
            {
                Error(setting, "Exclusion entry is null.", "Remove the empty entry.");
                continue;
            }

            if (string.IsNullOrWhiteSpace(exclusion.Sha256) && string.IsNullOrWhiteSpace(exclusion.Path))
            {
                Error(setting, "An exclusion needs a sha256 value, a path, or both.", "Add the SHA-256 shown on the Findings page.");
            }

            if (!string.IsNullOrWhiteSpace(exclusion.Sha256) && !Sha256Pattern().IsMatch(exclusion.Sha256))
            {
                Error(setting + ".sha256", "Not a valid SHA-256 value (64 hexadecimal characters).", "Copy the hash from the Findings page.");
            }

            if (!string.IsNullOrWhiteSpace(exclusion.Path))
            {
                var check = _pathPolicy.ValidateSyntax(exclusion.Path);
                if (!check.IsAllowed)
                {
                    Error(setting + ".path", check.Reason ?? "Invalid path.", "Use an absolute path to a single file.");
                }
            }
        }

        // ---- performance ----
        var performance = config.Performance;
        Range("performance.maxParallelTasks", performance.MaxParallelTasks, 1, 64);
        Range("performance.maxQueuedFiles", performance.MaxQueuedFiles, 16, 100_000);
        Range("performance.maxMemoryMegabytes", performance.MaxMemoryMegabytes, 64, 8192);
        Range("performance.hashBufferKilobytes", performance.HashBufferKilobytes, 64, 16384);
        if (performance.MaxParallelTasks > Environment.ProcessorCount * 2)
        {
            Warn("performance.maxParallelTasks", $"More workers ({performance.MaxParallelTasks}) than twice the logical processors ({Environment.ProcessorCount}) rarely helps.",
                "Lower the value to reduce the impact on other programs.");
        }

        // ---- rule updates ----
        var updates = config.RuleUpdates;
        Range("ruleUpdates.timeoutSeconds", updates.TimeoutSeconds, 5, 300);
        Range("ruleUpdates.maxDownloadKilobytes", updates.MaxDownloadKilobytes, 16, 65536);
        if (!string.IsNullOrWhiteSpace(updates.Endpoint))
        {
            if (!Uri.TryCreate(updates.Endpoint, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps)
            {
                Error("ruleUpdates.endpoint", "The update endpoint must be an absolute https:// URL.", "Use an HTTPS address or leave the value null.");
            }
            else if (!string.IsNullOrEmpty(uri.UserInfo))
            {
                Error("ruleUpdates.endpoint", "Credentials must not be embedded in the update URL.", "Remove the user name/password from the URL.");
            }
        }

        if (updates.Enabled && string.IsNullOrWhiteSpace(updates.Endpoint))
        {
            Warn("ruleUpdates.enabled", "Updates are enabled but no trusted update source is configured. Bundled rules will be used.",
                "Set ruleUpdates.endpoint to a trusted HTTPS source, or disable updates.");
        }

        if (updates.Enabled && config.Privacy.OfflineMode)
        {
            Warn("ruleUpdates.enabled", "Offline mode is on, so rule updates will not be downloaded.", "Turn off privacy.offlineMode to allow updates.");
        }

        for (var i = 0; i < (updates.AdditionalTrustedPublicKeys?.Count ?? 0); i++)
        {
            var key = updates.AdditionalTrustedPublicKeys![i];
            if (!IsValidEcdsaKey(key))
            {
                Error($"ruleUpdates.additionalTrustedPublicKeys[{i}]", "Not a valid base64 ECDSA P-256 public key (SubjectPublicKeyInfo).",
                    "Use the public key printed by 'CleanerPro.RuleTool keygen'.");
            }
            else
            {
                Warn($"ruleUpdates.additionalTrustedPublicKeys[{i}]", "An additional rule-signing key is trusted. Only add keys from a source you trust.",
                    "Remove the key if you did not add it yourself.");
            }
        }

        // ---- quarantine ----
        if (!config.Quarantine.VerifyIntegrity)
        {
            Error("quarantine.verifyIntegrity", "Quarantine integrity verification is mandatory and cannot be disabled.",
                "Set quarantine.verifyIntegrity to true.");
        }

        ValidateOptionalDirectory(issues, "quarantine.directory", config.Quarantine.Directory);

        // ---- reports ----
        ValidateOptionalDirectory(issues, "reports.directory", config.Reports.Directory);
        Range("reports.retentionDays", config.Reports.RetentionDays, 1, 3650);
        Range("reports.maxReports", config.Reports.MaxReports, 1, 10000);
        Range("reports.historyRetentionDays", config.Reports.HistoryRetentionDays, 1, 3650);
        Range("reports.maxHistorySessions", config.Reports.MaxHistorySessions, 1, 10000);

        // ---- logging ----
        if (!LogLevels.Contains(config.Logging.Level, StringComparer.OrdinalIgnoreCase))
        {
            Error("logging.level", $"'{config.Logging.Level}' is not a log level.", $"Use one of: {string.Join(", ", LogLevels)}.");
        }

        Range("logging.retentionDays", config.Logging.RetentionDays, 1, 365);
        Range("logging.maxFileMegabytes", config.Logging.MaxFileMegabytes, 1, 100);
        Range("logging.maxTotalMegabytes", config.Logging.MaxTotalMegabytes, 1, 2048);

        // ---- safety (mandatory protections) ----
        if (!config.Safety.ConfirmPermanentDeletion)
        {
            Error("safety.confirmPermanentDeletion", "Permanent deletion always requires confirmation; this protection cannot be disabled.",
                "Set safety.confirmPermanentDeletion to true.");
        }

        if (!config.Safety.EnforcePathValidation)
        {
            Error("safety.enforcePathValidation", "Path validation protects system files and cannot be disabled.",
                "Set safety.enforcePathValidation to true.");
        }

        if (!config.Safety.ConfirmQuarantine)
        {
            Warn("safety.confirmQuarantine", "Quarantine will run without a confirmation dialog (it remains reversible).",
                "Set to true to review each quarantine action before it happens.");
        }

        // ---- accessibility ----
        Range("accessibility.fontScale", config.Accessibility.FontScale, 0.8, 2.0);

        return new ConfigValidationResult(issues);
    }

    private void ValidatePathList(List<ConfigIssue> issues, string setting, List<string>? paths, bool warnIfMissing)
    {
        if (paths is null)
        {
            issues.Add(new ConfigIssue(ConfigIssueSeverity.Error, setting, "The list is null.", "Use [] for an empty list."));
            return;
        }

        foreach (var path in paths)
        {
            var check = _pathPolicy.ValidateSyntax(path);
            if (!check.IsAllowed)
            {
                issues.Add(new ConfigIssue(ConfigIssueSeverity.Error, setting, $"'{path}': {check.Reason}", "Use an absolute path such as C:\\Games\\Minecraft."));
            }
            else if (warnIfMissing && !Directory.Exists(check.NormalizedPath))
            {
                issues.Add(new ConfigIssue(ConfigIssueSeverity.Warning, setting, $"'{path}' does not exist and will be skipped.", "Remove it or correct the path."));
            }
        }
    }

    private void ValidateOptionalDirectory(List<ConfigIssue> issues, string setting, string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        var check = _pathPolicy.ValidateSyntax(path);
        if (!check.IsAllowed)
        {
            issues.Add(new ConfigIssue(ConfigIssueSeverity.Error, setting, $"'{path}': {check.Reason}", "Use an absolute directory path, or null for the default."));
            return;
        }

        foreach (var root in _pathPolicy.ProtectedRoots)
        {
            if (Core.PathKey.IsSameOrWithin(check.NormalizedPath!, root))
            {
                issues.Add(new ConfigIssue(ConfigIssueSeverity.Error, setting, $"'{path}' is inside a protected system location.", "Choose a folder in your user profile or on a data drive."));
                return;
            }
        }
    }

    private static void ReportUnknown(List<ConfigIssue> issues, string section, Dictionary<string, JsonElement>? unknown, bool critical)
    {
        if (unknown is null)
        {
            return;
        }

        foreach (var key in unknown.Keys)
        {
            var setting = string.IsNullOrEmpty(section) ? key : $"{section}.{key}";
            issues.Add(critical
                ? new ConfigIssue(ConfigIssueSeverity.Error, setting, $"Unknown setting '{setting}' in a security-critical section.",
                    "Remove it. Unknown settings in this section are rejected so typos cannot silently weaken protections.")
                : new ConfigIssue(ConfigIssueSeverity.Warning, setting, $"Unknown setting '{setting}' will be ignored.", "Check the spelling against docs/CONFIGURATION.md or remove it."));
        }
    }

    internal static bool IsValidEcdsaKey(string? base64)
    {
        if (string.IsNullOrWhiteSpace(base64))
        {
            return false;
        }

        try
        {
            using var ecdsa = ECDsa.Create();
            ecdsa.ImportSubjectPublicKeyInfo(Convert.FromBase64String(base64), out _);
            return ecdsa.KeySize == 256;
        }
        catch (Exception ex) when (ex is FormatException or CryptographicException)
        {
            return false;
        }
    }

    [GeneratedRegex("^\\.[A-Za-z0-9_-]{1,16}$")]
    private static partial Regex ExtensionPattern();

    [GeneratedRegex("^[A-Fa-f0-9]{64}$")]
    private static partial Regex Sha256Pattern();
}
