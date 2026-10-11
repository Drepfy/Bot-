using System.Text.Json;
using System.Text.Json.Nodes;
using CleanerPro.Core;
using CleanerPro.Core.Safety;
using CleanerPro.Infrastructure;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace CleanerPro.Configuration;

/// <summary>Outcome of loading the configuration file.</summary>
public sealed record ConfigLoadResult
{
    public required string FilePath { get; init; }

    public bool CreatedDefaultFile { get; init; }

    /// <summary>True when the file could not be used and safe defaults are active instead.</summary>
    public bool UsingSafeDefaults { get; init; }

    public string? FailureMessage { get; init; }

    public MigrationOutcome? Migration { get; init; }

    public string? BackupPath { get; init; }

    public ConfigValidationResult Validation { get; init; } = new([]);
}

public sealed record ConfigSaveResult(bool Succeeded, ConfigValidationResult Validation, string? BackupPath, string Message);

/// <summary>
/// Owns config.json: creation on first launch, parsing, migration, validation, backups, export and
/// restoring defaults. Invalid files are never overwritten automatically; safe defaults are used instead.
/// </summary>
public sealed class ConfigurationService
{
    private const int MaxBackups = 20;

    private readonly AppPaths _paths;
    private readonly ConfigValidator _validator;
    private readonly ConfigMigrator _migrator;
    private readonly TimeProvider _time;
    private readonly ILogger _logger;
    private readonly object _gate = new();
    private AppConfiguration _current = new();

    public ConfigurationService(AppPaths paths, PathSafetyPolicy pathPolicy, ILogger<ConfigurationService>? logger = null,
        ConfigMigrator? migrator = null, TimeProvider? time = null)
    {
        _paths = paths;
        _validator = new ConfigValidator(pathPolicy);
        _migrator = migrator ?? new ConfigMigrator();
        _time = time ?? TimeProvider.System;
        _logger = logger ?? NullLogger<ConfigurationService>.Instance;
        LastLoad = new ConfigLoadResult { FilePath = paths.ConfigFile };
    }

    public string FilePath => _paths.ConfigFile;

    public AppConfiguration Current
    {
        get
        {
            lock (_gate)
            {
                return _current;
            }
        }
    }

    public ConfigLoadResult LastLoad { get; private set; }

    public event EventHandler<AppConfiguration>? ConfigurationChanged;

    public static AppConfiguration CreateDefault() => new();

    public ConfigLoadResult Load()
    {
        ConfigLoadResult result;
        AppConfiguration effective;
        try
        {
            (result, effective) = LoadCore();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _logger.LogError(ex, "Configuration could not be read; using safe defaults");
            result = new ConfigLoadResult
            {
                FilePath = FilePath,
                UsingSafeDefaults = true,
                FailureMessage = $"The configuration file could not be read ({ex.Message}). Safe defaults are in use.",
            };
            effective = CreateDefault();
        }

        lock (_gate)
        {
            _current = effective;
            LastLoad = result;
        }

        ConfigurationChanged?.Invoke(this, effective);
        return result;
    }

    private (ConfigLoadResult, AppConfiguration) LoadCore()
    {
        if (!File.Exists(FilePath))
        {
            var defaults = CreateDefault();
            AtomicFile.WriteAllText(FilePath, Serialize(defaults));
            _logger.LogInformation("Created default configuration at {Path}", FilePath);
            return (new ConfigLoadResult { FilePath = FilePath, CreatedDefaultFile = true, Validation = _validator.Validate(defaults) }, defaults);
        }

        var text = File.ReadAllText(FilePath);
        var parse = Parse(text);
        if (parse.Config is null)
        {
            _logger.LogWarning("Configuration is invalid: {Message}", parse.Error);
            return (new ConfigLoadResult
            {
                FilePath = FilePath,
                UsingSafeDefaults = true,
                FailureMessage = parse.Error + " Safe defaults are in use and your file was left unchanged so you can correct it.",
                Validation = new ConfigValidationResult([new ConfigIssue(ConfigIssueSeverity.Error, parse.Setting ?? "(file)", parse.Error!, "Fix the file and choose 'Reload', or use 'Restore Defaults'.")]),
            }, CreateDefault());
        }

        string? backup = null;
        if (parse.Migration is { AppliedSteps.Count: > 0 })
        {
            backup = Backup("pre-migration");
            AtomicFile.WriteAllText(FilePath, Serialize(parse.Config));
            _logger.LogInformation("Migrated configuration from schema {From} to {To}", parse.Migration.FromVersion, parse.Migration.ToVersion);
        }

        var validation = _validator.Validate(parse.Config);
        if (!validation.IsValid)
        {
            var first = validation.Errors.First();
            return (new ConfigLoadResult
            {
                FilePath = FilePath,
                UsingSafeDefaults = true,
                FailureMessage = $"The configuration contains {validation.Errors.Count()} error(s), for example '{first.Setting}': {first.Message} Safe defaults are in use.",
                Validation = validation,
                Migration = parse.Migration,
                BackupPath = backup,
            }, CreateDefault());
        }

        return (new ConfigLoadResult { FilePath = FilePath, Validation = validation, Migration = parse.Migration, BackupPath = backup }, parse.Config);
    }

    private sealed record ParseOutcome(AppConfiguration? Config, string? Error, string? Setting, MigrationOutcome? Migration);

    private ParseOutcome Parse(string text)
    {
        JsonNode? node;
        try
        {
            node = JsonNode.Parse(text, documentOptions: new JsonDocumentOptions { CommentHandling = JsonCommentHandling.Skip, AllowTrailingCommas = true });
        }
        catch (JsonException ex)
        {
            return new ParseOutcome(null, $"config.json is not valid JSON (line {ex.LineNumber + 1}, position {ex.BytePositionInLine + 1}): {ex.Message}", null, null);
        }

        if (node is not JsonObject document)
        {
            return new ParseOutcome(null, "config.json must contain a JSON object.", null, null);
        }

        var version = ConfigMigrator.ReadVersion(document);
        if (version > _migrator.TargetVersion)
        {
            return new ParseOutcome(null,
                $"config.json uses schema version {version}, which was written by a newer version of the application (this version supports {_migrator.TargetVersion}).",
                "schemaVersion", null);
        }

        MigrationOutcome? migration = null;
        try
        {
            migration = _migrator.Migrate(document);
        }
        catch (InvalidOperationException ex)
        {
            return new ParseOutcome(null, $"The configuration could not be migrated: {ex.Message}", "schemaVersion", null);
        }

        try
        {
            var config = document.Deserialize<AppConfiguration>(CleanerJson.Default);
            return config is null
                ? new ParseOutcome(null, "config.json is empty.", null, migration)
                : new ParseOutcome(Normalize(config), null, null, migration);
        }
        catch (JsonException ex)
        {
            var setting = string.IsNullOrEmpty(ex.Path) ? null : ex.Path.TrimStart('$', '.');
            return new ParseOutcome(null, $"A setting has the wrong type{(setting is null ? string.Empty : $" at '{setting}'")}: {ex.Message}", setting, migration);
        }
    }

    /// <summary>Validates the file as it currently is on disk without changing the active configuration.</summary>
    public ConfigValidationResult ValidateFile()
    {
        if (!File.Exists(FilePath))
        {
            return new ConfigValidationResult([new ConfigIssue(ConfigIssueSeverity.Error, "(file)", "config.json does not exist.", "Choose 'Restore Defaults' to create it.")]);
        }

        var parse = Parse(File.ReadAllText(FilePath));
        return parse.Config is null
            ? new ConfigValidationResult([new ConfigIssue(ConfigIssueSeverity.Error, parse.Setting ?? "(file)", parse.Error!, "Fix the file and validate again.")])
            : _validator.Validate(parse.Config);
    }

    public ConfigValidationResult Validate(AppConfiguration config) => _validator.Validate(config);

    /// <summary>Validates, backs up the current file and writes the new configuration atomically.</summary>
    public ConfigSaveResult Save(AppConfiguration config, string reason)
    {
        var normalized = Normalize(Clone(config));
        var validation = _validator.Validate(normalized);
        if (!validation.IsValid)
        {
            return new ConfigSaveResult(false, validation, null, "The configuration was not saved because it contains errors.");
        }

        string? backup;
        try
        {
            backup = File.Exists(FilePath) ? Backup(reason) : null;
            AtomicFile.WriteAllText(FilePath, Serialize(normalized));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _logger.LogError(ex, "Saving configuration failed");
            return new ConfigSaveResult(false, validation, null, $"The configuration could not be written: {ex.Message}");
        }

        lock (_gate)
        {
            _current = normalized;
            LastLoad = new ConfigLoadResult { FilePath = FilePath, Validation = validation };
        }

        _logger.LogInformation("Configuration saved ({Reason})", reason);
        ConfigurationChanged?.Invoke(this, normalized);
        return new ConfigSaveResult(true, validation, backup, backup is null ? "Configuration saved." : $"Configuration saved. Previous version backed up to {backup}.");
    }

    public ConfigSaveResult RestoreDefaults() => Save(CreateDefault(), "restore-defaults");

    /// <summary>Writes the effective configuration to a user-chosen file.</summary>
    public void Export(string destinationPath)
    {
        var check = Path.GetFullPath(destinationPath);
        AtomicFile.WriteAllText(check, Serialize(Current));
        _logger.LogInformation("Configuration exported to {Path}", check);
    }

    public string SerializeEffective() => Serialize(Current);

    public AppConfiguration CloneCurrent() => Clone(Current);

    public IReadOnlyList<string> ListBackups() =>
        Directory.Exists(_paths.ConfigBackupDirectory)
            ? Directory.GetFiles(_paths.ConfigBackupDirectory, "config-*.json").OrderDescending().ToList()
            : [];

    public static string Serialize(AppConfiguration config) => JsonSerializer.Serialize(config, CleanerJson.Default);

    public static AppConfiguration Clone(AppConfiguration config) =>
        JsonSerializer.Deserialize<AppConfiguration>(Serialize(config), CleanerJson.Default) ?? CreateDefault();

    private string Backup(string reason)
    {
        Directory.CreateDirectory(_paths.ConfigBackupDirectory);
        var safeReason = new string(reason.Select(c => char.IsLetterOrDigit(c) || c == '-' ? c : '-').ToArray());
        var destination = Path.Combine(_paths.ConfigBackupDirectory, $"config-{_time.GetUtcNow():yyyyMMdd-HHmmssfff}-{safeReason}.json");
        File.Copy(FilePath, destination, overwrite: false);

        foreach (var old in ListBackups().Skip(MaxBackups))
        {
            AtomicFile.TryDelete(old);
        }

        return destination;
    }

    private static AppConfiguration Normalize(AppConfiguration config)
    {
        static List<string> Clean(List<string>? values) =>
            (values ?? []).Where(v => !string.IsNullOrWhiteSpace(v)).Select(v => v.Trim()).Distinct(StringComparer.OrdinalIgnoreCase).ToList();

        if (config.Scan is not null)
        {
            config.Scan.CustomDirectories = Clean(config.Scan.CustomDirectories);
            config.Scan.ExcludedDirectories = Clean(config.Scan.ExcludedDirectories);
            config.Scan.ExcludedDirectoryNames = Clean(config.Scan.ExcludedDirectoryNames);
            config.Scan.DisabledInstallationIds = Clean(config.Scan.DisabledInstallationIds);
            config.Scan.FileExtensions = Clean(config.Scan.FileExtensions).Select(e => e.ToLowerInvariant()).Distinct().ToList();
        }

        if (config.Detection?.EnabledCategories is not null)
        {
            config.Detection.EnabledCategories = config.Detection.EnabledCategories.Distinct().ToList();
        }

        if (config.RuleUpdates is not null)
        {
            config.RuleUpdates.Endpoint = string.IsNullOrWhiteSpace(config.RuleUpdates.Endpoint) ? null : config.RuleUpdates.Endpoint.Trim();
            config.RuleUpdates.AdditionalTrustedPublicKeys = Clean(config.RuleUpdates.AdditionalTrustedPublicKeys);
        }

        if (config.Quarantine is not null && string.IsNullOrWhiteSpace(config.Quarantine.Directory))
        {
            config.Quarantine.Directory = null;
        }

        if (config.Reports is not null && string.IsNullOrWhiteSpace(config.Reports.Directory))
        {
            config.Reports.Directory = null;
        }

        return config;
    }
}
