using System.Net;
using System.Text.Json;
using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Logging;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Privacy;
using CleanerPro.TestSupport;
using Microsoft.Extensions.Logging;

namespace CleanerPro.Core.Tests;

public sealed class InfrastructureTests : IDisposable
{
    private readonly TempDirectory _temp = new();

    public void Dispose() => _temp.Dispose();

    [Fact]
    public void HasherComputesKnownValues()
    {
        var file = _temp.WriteText("a.txt", "abc");
        var hashes = FileHasher.Compute(file, includeSha1: true);
        Assert.Equal("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", hashes.Sha256);
        Assert.Equal("a9993e364706816aba3e25717850c26c9cd0d89d", hashes.Sha1);
        Assert.Equal(3, hashes.Length);
    }

    [Fact]
    public void HarmlessTestFileHashMatchesTheBundledTestRule()
    {
        const string content = "MINECRAFT-CLEANER-PRO HARMLESS TEST FILE v1\nThis file contains no code. It only exists to confirm that detection, quarantine and restore work.\n";
        Assert.Equal("6fab04ffb2267b6330c4551365755c5dbb072ba7bc0b98d14fde7dc6d27cacae", FileHasher.Sha256Hex(System.Text.Encoding.UTF8.GetBytes(content)));
    }

    [Fact]
    public void AtomicWriteLeavesNoTemporaryFiles()
    {
        var path = _temp.Combine("data.json");
        AtomicFile.WriteAllText(path, "one");
        AtomicFile.WriteAllText(path, "two");
        Assert.Equal("two", File.ReadAllText(path));
        Assert.Single(Directory.GetFiles(_temp.Path));
    }

    [Fact]
    public void LoggerWritesStructuredJsonLines()
    {
        var directory = _temp.Combine("logs");
        using (var provider = new JsonFileLoggerProvider(new FileLoggerOptions { Directory = directory, MinimumLevel = LogLevel.Information }))
        {
            var logger = provider.CreateLogger("Test");
            logger.LogInformation("Scanned {Count} files", 42);
            logger.LogDebug("Filtered out");
        }

        var lines = File.ReadAllLines(Directory.GetFiles(directory).Single());
        Assert.Single(lines);
        using var document = JsonDocument.Parse(lines[0]);
        Assert.Equal("Scanned 42 files", document.RootElement.GetProperty("message").GetString());
        Assert.Equal("42", document.RootElement.GetProperty("Count").GetString());
    }

    [Fact]
    public void LogRetentionRemovesOldFiles()
    {
        var directory = _temp.CreateDirectory("logs");
        var old = Path.Combine(directory, "cleanerpro-20200101.log");
        File.WriteAllText(old, "old");
        File.SetLastWriteTimeUtc(old, DateTime.UtcNow.AddDays(-60));
        using var provider = new JsonFileLoggerProvider(new FileLoggerOptions { Directory = directory, RetentionDays = 14 });
        Assert.False(File.Exists(old));
    }

    [Fact]
    public void LogFilesRotateAtTheSizeLimit()
    {
        var directory = _temp.Combine("logs");
        using (var provider = new JsonFileLoggerProvider(new FileLoggerOptions { Directory = directory, MaxFileBytes = 2048 }))
        {
            var logger = provider.CreateLogger("Test");
            for (var i = 0; i < 100; i++)
            {
                logger.LogInformation("Message number {Index} with some padding to fill the file", i);
            }
        }

        var files = Directory.GetFiles(directory);
        Assert.True(files.Length > 1);
        Assert.All(files, f => Assert.True(new FileInfo(f).Length <= 2048 + 512));
    }

    [Fact]
    public void OperationLogIgnoresATornFinalLine()
    {
        var log = new OperationLog(_temp.Combine("ops.jsonl"));
        log.Append(new OperationRecord { Id = "1", Type = OperationType.Quarantine, TimestampUtc = DateTimeOffset.UtcNow, Succeeded = true, Message = "ok" });
        File.AppendAllText(log.FilePath, "{\"id\":\"2\",\"type\":");
        Assert.Single(log.ReadAll());
    }

    [Fact]
    public void ShellLauncherOnlyOpensExistingTextFiles()
    {
        var launcher = new ShellLauncher();
        Assert.False(launcher.OpenFile(_temp.Combine("missing.json")).Succeeded);
        var exe = _temp.WriteText("program.exe", "MZ");
        var result = launcher.OpenFile(exe);
        Assert.False(result.Succeeded);
        Assert.Contains("Only text and report files", result.Message);
    }

    // ---------------- privacy / network ----------------

    private sealed class CountingHandler(Func<HttpRequestMessage, HttpResponseMessage>? respond = null) : HttpMessageHandler
    {
        public int Calls { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            return Task.FromResult(respond?.Invoke(request) ?? new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent([1, 2, 3]) });
        }
    }

    private static AppConfiguration OnlineConfig(string endpoint = "https://rules.example.org/feed")
    {
        var config = ConfigurationService.CreateDefault();
        config.Privacy.OfflineMode = false;
        config.RuleUpdates.Enabled = true;
        config.RuleUpdates.Endpoint = endpoint;
        return config;
    }

    [Fact]
    public async Task OfflineModeBlocksEveryRequestAndRecordsTheAttempt()
    {
        var handler = new CountingHandler();
        var log = new NetworkActivityLog(_temp.Combine("net.jsonl"));
        var config = ConfigurationService.CreateDefault();
        using var client = new GuardedHttpClient(new NetworkAccessPolicy(() => config), log, handler);

        var response = await client.GetAsync(NetworkPurpose.RuleDatabaseUpdate, new Uri("https://rules.example.org/feed/rules.json"), 1024, TimeSpan.FromSeconds(5), CancellationToken.None);

        Assert.False(response.Succeeded);
        Assert.Equal(0, handler.Calls);
        var record = Assert.Single(log.ReadAll());
        Assert.False(record.Allowed);
        Assert.Contains("Offline", record.Detail);
    }

    [Fact]
    public async Task OnlyTheConfiguredHttpsEndpointIsAllowed()
    {
        var handler = new CountingHandler();
        var log = new NetworkActivityLog(_temp.Combine("net.jsonl"));
        var config = OnlineConfig();
        using var client = new GuardedHttpClient(new NetworkAccessPolicy(() => config), log, handler);

        var other = await client.GetAsync(NetworkPurpose.RuleDatabaseUpdate, new Uri("https://evil.example.com/x"), 1024, TimeSpan.FromSeconds(5), CancellationToken.None);
        var http = await client.GetAsync(NetworkPurpose.RuleDatabaseUpdate, new Uri("http://rules.example.org/feed/rules.json"), 1024, TimeSpan.FromSeconds(5), CancellationToken.None);
        var ok = await client.GetAsync(NetworkPurpose.RuleDatabaseUpdate, new Uri("https://rules.example.org/feed/rules.json"), 1024, TimeSpan.FromSeconds(5), CancellationToken.None);

        Assert.False(other.Succeeded);
        Assert.False(http.Succeeded);
        Assert.True(ok.Succeeded);
        Assert.Equal(1, handler.Calls);
        Assert.Equal(3, log.ReadAll().Count);
    }

    [Fact]
    public async Task ResponsesLargerThanTheLimitAreDiscarded()
    {
        var handler = new CountingHandler(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(new byte[5000]) });
        var config = OnlineConfig();
        using var client = new GuardedHttpClient(new NetworkAccessPolicy(() => config), new NetworkActivityLog(_temp.Combine("n.jsonl")), handler);
        var response = await client.GetAsync(NetworkPurpose.RuleDatabaseUpdate, new Uri("https://rules.example.org/feed/rules.json"), 1000, TimeSpan.FromSeconds(5), CancellationToken.None);
        Assert.False(response.Succeeded);
        Assert.Null(response.Body);
    }

    [Fact]
    public async Task RequestsSendNoCookiesOrIdentifyingHeaders()
    {
        HttpRequestMessage? seen = null;
        var handler = new CountingHandler(request =>
        {
            seen = request;
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent([1]) };
        });
        var config = OnlineConfig();
        using var client = new GuardedHttpClient(new NetworkAccessPolicy(() => config), new NetworkActivityLog(_temp.Combine("n.jsonl")), handler);
        await client.GetAsync(NetworkPurpose.RuleDatabaseUpdate, new Uri("https://rules.example.org/feed/rules.json"), 1000, TimeSpan.FromSeconds(5), CancellationToken.None);

        Assert.NotNull(seen);
        Assert.Equal(HttpMethod.Get, seen!.Method);
        Assert.Null(seen.Content);
        Assert.False(seen.Headers.Contains("Cookie"));
        Assert.False(seen.Headers.Contains("Authorization"));
        Assert.Equal("MinecraftCleanerPro", seen.Headers.UserAgent.Single().Product!.Name);
    }

    [Fact]
    public void PrivacyStatementDoesNotOverclaim()
    {
        Assert.DoesNotContain("completely private", PrivacyStatement.Summary, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("network-activity.jsonl", PrivacyStatement.Summary);
    }
}
