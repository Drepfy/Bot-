using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using CleanerPro.Configuration;
using CleanerPro.Core;

namespace CleanerPro.Privacy;

/// <summary>The only reasons the application may ever use the network.</summary>
public enum NetworkPurpose
{
    RuleDatabaseUpdate,
}

public sealed record NetworkDecision(bool Allowed, string Reason);

/// <summary>A single network request (or a blocked attempt), recorded locally for the user to audit.</summary>
public sealed record NetworkActivityRecord
{
    public required DateTimeOffset TimestampUtc { get; init; }

    public required NetworkPurpose Purpose { get; init; }

    public required string Method { get; init; }

    public required string Url { get; init; }

    public required bool Allowed { get; init; }

    public int? StatusCode { get; init; }

    public long BytesReceived { get; init; }

    public string? Detail { get; init; }
}

/// <summary>
/// Central gate for all network access. Offline mode (the default) blocks every request. Only HTTPS
/// requests to the configured rule-update endpoint are ever permitted.
/// </summary>
public sealed class NetworkAccessPolicy
{
    private readonly Func<AppConfiguration> _config;

    public NetworkAccessPolicy(Func<AppConfiguration> config)
    {
        _config = config;
    }

    public bool IsOffline => _config().Privacy.OfflineMode;

    public NetworkDecision Evaluate(NetworkPurpose purpose, Uri uri)
    {
        var config = _config();
        if (config.Privacy.OfflineMode)
        {
            return new NetworkDecision(false, "Offline mode is on. No network requests are made.");
        }

        if (uri.Scheme != Uri.UriSchemeHttps)
        {
            return new NetworkDecision(false, "Only HTTPS requests are permitted.");
        }

        switch (purpose)
        {
            case NetworkPurpose.RuleDatabaseUpdate:
                if (!config.RuleUpdates.Enabled)
                {
                    return new NetworkDecision(false, "Rule updates are disabled in the configuration.");
                }

                if (string.IsNullOrWhiteSpace(config.RuleUpdates.Endpoint) ||
                    !Uri.TryCreate(config.RuleUpdates.Endpoint, UriKind.Absolute, out var endpoint))
                {
                    return new NetworkDecision(false, "No trusted update source is configured.");
                }

                if (!string.Equals(endpoint.Host, uri.Host, StringComparison.OrdinalIgnoreCase) || endpoint.Port != uri.Port)
                {
                    return new NetworkDecision(false, "The request does not target the configured update source.");
                }

                return new NetworkDecision(true, "Rule update from the configured HTTPS source.");
            default:
                return new NetworkDecision(false, "Unknown network purpose.");
        }
    }
}

/// <summary>Append-only local record of network activity, shown on the Privacy page.</summary>
public sealed class NetworkActivityLog
{
    private readonly string _path;
    private readonly object _gate = new();

    public NetworkActivityLog(string path)
    {
        _path = path;
    }

    public string FilePath => _path;

    public void Append(NetworkActivityRecord record)
    {
        var line = JsonSerializer.Serialize(record, CleanerJson.Compact) + "\n";
        lock (_gate)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_path)!);
            File.AppendAllText(_path, line, Encoding.UTF8);
        }
    }

    public IReadOnlyList<NetworkActivityRecord> ReadAll()
    {
        lock (_gate)
        {
            if (!File.Exists(_path))
            {
                return [];
            }

            var list = new List<NetworkActivityRecord>();
            foreach (var line in File.ReadLines(_path))
            {
                try
                {
                    if (!string.IsNullOrWhiteSpace(line) && JsonSerializer.Deserialize<NetworkActivityRecord>(line, CleanerJson.Compact) is { } record)
                    {
                        list.Add(record);
                    }
                }
                catch (JsonException)
                {
                }
            }

            return list;
        }
    }

    public void Clear()
    {
        lock (_gate)
        {
            if (File.Exists(_path))
            {
                File.Delete(_path);
            }
        }
    }
}

public sealed record NetworkResponse(bool Succeeded, byte[]? Body, int? StatusCode, string Message);

/// <summary>
/// The application's only HTTP client. Every request passes <see cref="NetworkAccessPolicy"/>, is logged
/// to <see cref="NetworkActivityLog"/>, sends no cookies or credentials, does not follow redirects and
/// enforces a maximum response size.
/// </summary>
public sealed class GuardedHttpClient : IDisposable
{
    private readonly NetworkAccessPolicy _policy;
    private readonly NetworkActivityLog _log;
    private readonly HttpClient _client;
    private readonly TimeProvider _time;

    public GuardedHttpClient(NetworkAccessPolicy policy, NetworkActivityLog log, HttpMessageHandler? handler = null, TimeProvider? time = null)
    {
        _policy = policy;
        _log = log;
        _time = time ?? TimeProvider.System;
        handler ??= new SocketsHttpHandler
        {
            UseCookies = false,
            AllowAutoRedirect = false,
            Credentials = null,
            AutomaticDecompression = DecompressionMethods.None,
        };
        _client = new HttpClient(handler, disposeHandler: true) { Timeout = Timeout.InfiniteTimeSpan };
        _client.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("MinecraftCleanerPro", AppInfo.Version));
    }

    public async Task<NetworkResponse> GetAsync(NetworkPurpose purpose, Uri uri, long maxBytes, TimeSpan timeout, CancellationToken cancellationToken)
    {
        var decision = _policy.Evaluate(purpose, uri);
        if (!decision.Allowed)
        {
            _log.Append(new NetworkActivityRecord
            {
                TimestampUtc = _time.GetUtcNow(), Purpose = purpose, Method = "GET", Url = uri.ToString(), Allowed = false, Detail = decision.Reason,
            });
            return new NetworkResponse(false, null, null, decision.Reason);
        }

        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutSource.CancelAfter(timeout);
        int? status = null;
        long received = 0;
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, uri);
            using var response = await _client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeoutSource.Token).ConfigureAwait(false);
            status = (int)response.StatusCode;
            if (!response.IsSuccessStatusCode)
            {
                return Finish(false, null, $"The server answered HTTP {status}.");
            }

            if (response.Content.Headers.ContentLength > maxBytes)
            {
                return Finish(false, null, $"The response is larger than the {maxBytes / 1024} KB limit.");
            }

            await using var stream = await response.Content.ReadAsStreamAsync(timeoutSource.Token).ConfigureAwait(false);
            using var buffer = new MemoryStream();
            var chunk = new byte[81920];
            int read;
            while ((read = await stream.ReadAsync(chunk, timeoutSource.Token).ConfigureAwait(false)) > 0)
            {
                received += read;
                if (received > maxBytes)
                {
                    return Finish(false, null, $"The response exceeded the {maxBytes / 1024} KB limit and was discarded.");
                }

                buffer.Write(chunk, 0, read);
            }

            return Finish(true, buffer.ToArray(), "Downloaded.");
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return Finish(false, null, "The request timed out.");
        }
        catch (HttpRequestException ex)
        {
            return Finish(false, null, $"The request failed: {ex.Message}");
        }

        NetworkResponse Finish(bool ok, byte[]? body, string message)
        {
            _log.Append(new NetworkActivityRecord
            {
                TimestampUtc = _time.GetUtcNow(), Purpose = purpose, Method = "GET", Url = uri.ToString(), Allowed = true,
                StatusCode = status, BytesReceived = received, Detail = message,
            });
            return new NetworkResponse(ok, body, status, message);
        }
    }

    public void Dispose() => _client.Dispose();
}

/// <summary>Plain-language description of the application's data handling, shown in the UI.</summary>
public static class PrivacyStatement
{
    public const string Summary =
        "Minecraft Cleaner Pro scans files on this computer and keeps every result, report and log on this computer. " +
        "It contains no telemetry, no analytics, no remote control and no credential, cookie or token collection. " +
        "Offline mode is on by default, which blocks all network access. " +
        "The only optional network feature is downloading a signed detection-rule database from an HTTPS address you configure. " +
        "That request is a plain HTTPS GET that sends the application name and version in the User-Agent header; " +
        "it contains no scan results, file names, paths, hardware identifiers or account information. " +
        "Every request and every blocked attempt is recorded in network-activity.jsonl so you can audit it.";
}
