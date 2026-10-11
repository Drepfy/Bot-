using System.Text;
using System.Text.Json;
using CleanerPro.Configuration;
using CleanerPro.Core;
using CleanerPro.Infrastructure;
using CleanerPro.Privacy;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace CleanerPro.Detection.Rules;

public sealed record RuleUpdateStatus
{
    public DateTimeOffset? LastCheckUtc { get; init; }

    public bool? LastSucceeded { get; init; }

    public string Message { get; init; } = "No update check has been performed.";
}

/// <summary>
/// Downloads signed rule updates from the configured HTTPS endpoint (rules.json + rules.json.sig).
/// Nothing is downloaded unless updates are enabled, offline mode is off and an endpoint is configured.
/// </summary>
public sealed class RuleUpdateService
{
    private readonly RuleRepository _repository;
    private readonly GuardedHttpClient _http;
    private readonly Func<AppConfiguration> _config;
    private readonly AppPaths _paths;
    private readonly ILogger _logger;
    private readonly TimeProvider _time;

    public RuleUpdateService(RuleRepository repository, GuardedHttpClient http, Func<AppConfiguration> config, AppPaths paths,
        ILogger<RuleUpdateService>? logger = null, TimeProvider? time = null)
    {
        _repository = repository;
        _http = http;
        _config = config;
        _paths = paths;
        _logger = logger ?? NullLogger<RuleUpdateService>.Instance;
        _time = time ?? TimeProvider.System;
    }

    private string StatusFile => Path.Combine(_paths.RulesDirectory, "update-status.json");

    public static IReadOnlyList<string> TrustedKeys(AppConfiguration config) =>
        RuleSignature.BuiltInTrustedPublicKeys.Concat(config.RuleUpdates.AdditionalTrustedPublicKeys).Distinct().ToList();

    /// <summary>Plain-language explanation of the current update configuration.</summary>
    public string DescribeConfiguration()
    {
        var config = _config();
        var bundled = _repository.Active.Database.DisplayVersion;
        if (string.IsNullOrWhiteSpace(config.RuleUpdates.Endpoint))
        {
            return $"No trusted update source has been configured, so online updates are unavailable. The application uses its rule database {bundled} and works fully offline.";
        }

        if (TrustedKeys(config).Count == 0)
        {
            return "An update source is configured but no trusted signing key is, so downloaded updates cannot be verified and will not be installed.";
        }

        if (!config.RuleUpdates.Enabled)
        {
            return "Rule updates are disabled in the configuration.";
        }

        if (config.Privacy.OfflineMode)
        {
            return "Offline mode is on, so no update requests are made.";
        }

        return $"Updates are downloaded from {config.RuleUpdates.Endpoint} and must carry a valid signature from a trusted key.";
    }

    public RuleUpdateStatus ReadStatus()
    {
        try
        {
            return File.Exists(StatusFile)
                ? JsonSerializer.Deserialize<RuleUpdateStatus>(File.ReadAllText(StatusFile), CleanerJson.Default) ?? new RuleUpdateStatus()
                : new RuleUpdateStatus();
        }
        catch (Exception ex) when (ex is JsonException or IOException)
        {
            return new RuleUpdateStatus();
        }
    }

    public async Task<RuleUpdateStatus> CheckForUpdatesAsync(CancellationToken cancellationToken)
    {
        var config = _config();
        RuleUpdateStatus status;
        if (!config.RuleUpdates.Enabled || config.Privacy.OfflineMode || string.IsNullOrWhiteSpace(config.RuleUpdates.Endpoint) ||
            TrustedKeys(config).Count == 0)
        {
            status = new RuleUpdateStatus { LastCheckUtc = _time.GetUtcNow(), LastSucceeded = null, Message = DescribeConfiguration() };
            Save(status);
            return status;
        }

        var baseUri = new Uri(config.RuleUpdates.Endpoint.TrimEnd('/') + "/");
        var maxBytes = config.RuleUpdates.MaxDownloadKilobytes * 1024L;
        var timeout = TimeSpan.FromSeconds(config.RuleUpdates.TimeoutSeconds);

        var rules = await _http.GetAsync(NetworkPurpose.RuleDatabaseUpdate, new Uri(baseUri, "rules.json"), maxBytes, timeout, cancellationToken).ConfigureAwait(false);
        if (!rules.Succeeded || rules.Body is null)
        {
            status = Fail($"Downloading rules.json failed: {rules.Message}");
            return status;
        }

        var signature = await _http.GetAsync(NetworkPurpose.RuleDatabaseUpdate, new Uri(baseUri, "rules.json.sig"), 16 * 1024, timeout, cancellationToken).ConfigureAwait(false);
        if (!signature.Succeeded || signature.Body is null)
        {
            status = Fail($"Downloading rules.json.sig failed: {signature.Message}");
            return status;
        }

        var install = _repository.InstallUpdate(rules.Body, Encoding.UTF8.GetString(signature.Body));
        var alreadyCurrent = !install.Installed && install.Message.Contains("already installed", StringComparison.Ordinal);
        status = new RuleUpdateStatus
        {
            LastCheckUtc = _time.GetUtcNow(),
            LastSucceeded = install.Installed || alreadyCurrent,
            Message = install.Details.Count == 0 ? install.Message : install.Message + " " + string.Join(" ", install.Details.Take(5)),
        };
        _logger.LogInformation("Rule update check: {Message}", status.Message);
        Save(status);
        return status;

        RuleUpdateStatus Fail(string message)
        {
            var failed = new RuleUpdateStatus { LastCheckUtc = _time.GetUtcNow(), LastSucceeded = false, Message = message + " The current rules remain active." };
            _logger.LogWarning("Rule update failed: {Message}", message);
            Save(failed);
            return failed;
        }
    }

    private void Save(RuleUpdateStatus status)
    {
        try
        {
            AtomicFile.WriteAllText(StatusFile, JsonSerializer.Serialize(status, CleanerJson.Default));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _logger.LogWarning(ex, "Could not save rule update status");
        }
    }
}
