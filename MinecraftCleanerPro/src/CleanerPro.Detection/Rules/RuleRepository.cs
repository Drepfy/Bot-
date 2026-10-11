using System.Text.Json;
using CleanerPro.Core;
using CleanerPro.Infrastructure;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace CleanerPro.Detection.Rules;

public enum RuleSource
{
    Bundled,
    InstalledUpdate,
}

public sealed record ActiveRules(CompiledRuleDatabase Database, RuleSource Source, string StatusMessage, IReadOnlyList<string> Warnings);

public sealed record RuleInstallResult(bool Installed, string Message, IReadOnlyList<string> Details);

internal sealed record RuleState
{
    public long HighestAcceptedVersion { get; init; }

    public DateTimeOffset? InstalledAtUtc { get; init; }

    public string? SigningKeyFingerprint { get; init; }
}

/// <summary>
/// Provides the active rule database: the bundled database embedded in the application, or a newer
/// signed update. Updates are verified on install and again on every load, must not be expired, and can
/// never roll back to an older version than one already accepted.
/// </summary>
public sealed class RuleRepository
{
    public const string BundledResourceName = "CleanerPro.Rules.Bundled.json";

    private readonly AppPaths _paths;
    private readonly Func<IReadOnlyList<string>> _trustedKeys;
    private readonly ILogger _logger;
    private readonly TimeProvider _time;
    private readonly string? _platform;
    private readonly Func<byte[]> _bundled;
    private readonly object _gate = new();
    private ActiveRules? _active;

    public RuleRepository(AppPaths paths, Func<IReadOnlyList<string>> trustedKeys, ILogger<RuleRepository>? logger = null,
        TimeProvider? time = null, string? platform = null, Func<byte[]>? bundledProvider = null)
    {
        _paths = paths;
        _trustedKeys = trustedKeys;
        _logger = logger ?? NullLogger<RuleRepository>.Instance;
        _time = time ?? TimeProvider.System;
        _platform = platform;
        _bundled = bundledProvider ?? ReadBundledBytes;
    }

    public event EventHandler<ActiveRules>? RulesChanged;

    public string InstalledRulesFile => Path.Combine(_paths.RulesDirectory, "installed-rules.json");

    public string InstalledSignatureFile => InstalledRulesFile + ".sig";

    private string StateFile => Path.Combine(_paths.RulesDirectory, "state.json");

    public ActiveRules Active
    {
        get
        {
            lock (_gate)
            {
                return _active ?? throw new InvalidOperationException("Rules have not been loaded.");
            }
        }
    }

    public static byte[] ReadBundledBytes()
    {
        using var stream = typeof(RuleRepository).Assembly.GetManifestResourceStream(BundledResourceName)
                           ?? throw new InvalidOperationException("The bundled rule database is missing from the application.");
        using var memory = new MemoryStream();
        stream.CopyTo(memory);
        return memory.ToArray();
    }

    public ActiveRules Load()
    {
        var bundledOutcome = RuleDatabaseLoader.Load(_bundled(), _platform);
        if (!bundledOutcome.Succeeded)
        {
            throw new InvalidOperationException("The bundled rule database is invalid: " + string.Join(" ", bundledOutcome.Errors));
        }

        var bundled = bundledOutcome.Database!;
        var warnings = new List<string>(bundledOutcome.Warnings);
        ActiveRules active = new(bundled, RuleSource.Bundled,
            $"Using bundled rules {bundled.DisplayVersion} ({bundled.Rules.Count} rules active on this platform).", warnings);

        if (File.Exists(InstalledRulesFile))
        {
            var installed = TryLoadInstalled(bundled, warnings);
            if (installed is not null)
            {
                active = new ActiveRules(installed, RuleSource.InstalledUpdate,
                    $"Using signed rule update {installed.DisplayVersion} ({installed.Rules.Count} rules active on this platform).", warnings);
            }
        }

        lock (_gate)
        {
            _active = active;
        }

        _logger.LogInformation("{Status}", active.StatusMessage);
        RulesChanged?.Invoke(this, active);
        return active;
    }

    private CompiledRuleDatabase? TryLoadInstalled(CompiledRuleDatabase bundled, List<string> warnings)
    {
        try
        {
            var json = File.ReadAllBytes(InstalledRulesFile);
            var signature = File.Exists(InstalledSignatureFile) ? File.ReadAllText(InstalledSignatureFile) : string.Empty;
            if (!RuleSignature.Verify(json, signature, _trustedKeys(), out _))
            {
                warnings.Add("The installed rule update failed signature verification (it may have been modified). Bundled rules are used instead.");
                return null;
            }

            var outcome = RuleDatabaseLoader.Load(json, _platform);
            if (!outcome.Succeeded)
            {
                warnings.Add("The installed rule update is invalid and was ignored: " + string.Join(" ", outcome.Errors));
                return null;
            }

            var database = outcome.Database!;
            if (database.Document.ExpiresAt is { } expires && expires <= _time.GetUtcNow())
            {
                warnings.Add($"The installed rule update expired on {expires:yyyy-MM-dd}. Bundled rules are used until a newer update is installed.");
                return null;
            }

            var state = ReadState();
            if (database.DatabaseVersion < state.HighestAcceptedVersion)
            {
                warnings.Add($"The installed rule update (version {database.DatabaseVersion}) is older than a version already accepted ({state.HighestAcceptedVersion}). It was rejected to prevent a rollback.");
                return null;
            }

            if (database.DatabaseVersion <= bundled.DatabaseVersion)
            {
                warnings.Add("The installed rule update is not newer than the bundled rules, so the bundled rules are used.");
                return null;
            }

            return database;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            warnings.Add($"The installed rule update could not be read: {ex.Message}");
            return null;
        }
    }

    /// <summary>Verifies and installs a downloaded rule database.</summary>
    public RuleInstallResult InstallUpdate(byte[] json, string signature)
    {
        var keys = _trustedKeys();
        if (keys.Count == 0)
        {
            return new RuleInstallResult(false, "No trusted signing key is configured, so the update cannot be verified and was not installed.", []);
        }

        if (!RuleSignature.Verify(json, signature, keys, out var fingerprint))
        {
            return new RuleInstallResult(false, "The update's signature is invalid or was made with an untrusted key. It was rejected.", []);
        }

        var outcome = RuleDatabaseLoader.Load(json, _platform);
        if (!outcome.Succeeded)
        {
            return new RuleInstallResult(false, "The update is not a valid rule database and was rejected.", outcome.Errors);
        }

        var database = outcome.Database!;
        if (database.Document.ExpiresAt is not { } expires)
        {
            return new RuleInstallResult(false, "The update does not declare an expiry date and was rejected.", []);
        }

        if (expires <= _time.GetUtcNow())
        {
            return new RuleInstallResult(false, $"The update expired on {expires:yyyy-MM-dd} and was rejected.", []);
        }

        var current = Active.Database.DatabaseVersion;
        var floor = Math.Max(current, ReadState().HighestAcceptedVersion);
        if (database.DatabaseVersion <= floor)
        {
            return new RuleInstallResult(false,
                database.DatabaseVersion == floor
                    ? $"Rule version {database.DatabaseVersion} is already installed."
                    : $"The update (version {database.DatabaseVersion}) is older than the accepted version {floor} and was rejected to prevent a rollback.", []);
        }

        Directory.CreateDirectory(_paths.RulesDirectory);
        AtomicFile.WriteAllBytes(InstalledRulesFile, json);
        AtomicFile.WriteAllText(InstalledSignatureFile, signature.Trim());
        WriteState(new RuleState { HighestAcceptedVersion = database.DatabaseVersion, InstalledAtUtc = _time.GetUtcNow(), SigningKeyFingerprint = fingerprint });

        var active = new ActiveRules(database, RuleSource.InstalledUpdate,
            $"Using signed rule update {database.DisplayVersion} ({database.Rules.Count} rules active on this platform).", outcome.Warnings);
        lock (_gate)
        {
            _active = active;
        }

        _logger.LogInformation("Installed rule update {Version} signed by key {Fingerprint}", database.DisplayVersion, fingerprint);
        RulesChanged?.Invoke(this, active);
        return new RuleInstallResult(true, $"Installed rule database {database.DisplayVersion}.", outcome.Warnings);
    }

    private RuleState ReadState()
    {
        try
        {
            return File.Exists(StateFile)
                ? JsonSerializer.Deserialize<RuleState>(File.ReadAllText(StateFile), CleanerJson.Default) ?? new RuleState()
                : new RuleState();
        }
        catch (Exception ex) when (ex is JsonException or IOException)
        {
            _logger.LogWarning(ex, "Rule state file is unreadable");
            return new RuleState();
        }
    }

    private void WriteState(RuleState state) => AtomicFile.WriteAllText(StateFile, JsonSerializer.Serialize(state, CleanerJson.Default));
}
