using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using CleanerPro.Configuration;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure;
using CleanerPro.Privacy;
using CleanerPro.TestSupport;

namespace CleanerPro.Detection.Tests;

public sealed class RuleUpdateTests : IDisposable
{
    private readonly TempDirectory _temp = new();
    private readonly AppPaths _paths;
    private readonly ECDsa _key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
    private readonly string _publicKey;
    private readonly ManualTimeProvider _time = new(new DateTimeOffset(2026, 10, 11, 12, 0, 0, TimeSpan.Zero));

    public RuleUpdateTests()
    {
        _paths = new AppPaths(_temp.Combine("data"));
        _paths.EnsureCreated();
        _publicKey = Convert.ToBase64String(_key.ExportSubjectPublicKeyInfo());
    }

    public void Dispose()
    {
        _key.Dispose();
        _temp.Dispose();
    }

    private RuleRepository Repository(params string[] keys)
    {
        var repository = new RuleRepository(_paths, () => keys, time: _time, platform: "windows");
        repository.Load();
        return repository;
    }

    private static byte[] UpdateBytes(long version, DateTimeOffset? expires)
    {
        var document = JsonNode.Parse(RuleRepository.ReadBundledBytes())!.AsObject();
        document["databaseVersion"] = version;
        document["displayVersion"] = $"test-{version}";
        document["expiresAt"] = expires?.ToString("O");
        return Encoding.UTF8.GetBytes(document.ToJsonString());
    }

    private string Sign(byte[] data) => RuleSignature.Sign(data, _key);

    [Fact]
    public void SignaturesVerifyOnlyWithTheTrustedKeyAndUnmodifiedData()
    {
        var data = Encoding.UTF8.GetBytes("rules");
        var signature = Sign(data);
        Assert.True(RuleSignature.Verify(data, signature, [_publicKey], out var fingerprint));
        Assert.NotNull(fingerprint);
        Assert.False(RuleSignature.Verify(Encoding.UTF8.GetBytes("rules!"), signature, [_publicKey], out _));

        using var other = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        Assert.False(RuleSignature.Verify(data, signature, [Convert.ToBase64String(other.ExportSubjectPublicKeyInfo())], out _));
        Assert.False(RuleSignature.Verify(data, "not base64!", [_publicKey], out _));
    }

    [Fact]
    public void BundledRulesAreUsedWhenNothingIsInstalled()
    {
        var repository = Repository(_publicKey);
        Assert.Equal(RuleSource.Bundled, repository.Active.Source);
    }

    [Fact]
    public void AValidSignedUpdateIsInstalledAndSurvivesRestart()
    {
        var bytes = UpdateBytes(9_000_000_001, _time.GetUtcNow().AddDays(30));
        var result = Repository(_publicKey).InstallUpdate(bytes, Sign(bytes));
        Assert.True(result.Installed, result.Message);

        var restarted = Repository(_publicKey);
        Assert.Equal(RuleSource.InstalledUpdate, restarted.Active.Source);
        Assert.Equal(9_000_000_001, restarted.Active.Database.DatabaseVersion);
    }

    [Fact]
    public void UpdatesSignedWithAnUntrustedKeyAreRejected()
    {
        var bytes = UpdateBytes(9_000_000_001, _time.GetUtcNow().AddDays(30));
        using var attacker = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var result = Repository(_publicKey).InstallUpdate(bytes, RuleSignature.Sign(bytes, attacker));
        Assert.False(result.Installed);
        Assert.False(File.Exists(Repository(_publicKey).InstalledRulesFile));
    }

    [Fact]
    public void UpdatesAreRejectedWithoutAnyTrustedKey()
    {
        var bytes = UpdateBytes(9_000_000_001, _time.GetUtcNow().AddDays(30));
        var result = Repository().InstallUpdate(bytes, Sign(bytes));
        Assert.False(result.Installed);
        Assert.Contains("No trusted signing key", result.Message);
    }

    [Fact]
    public void ExpiredAndNonExpiringUpdatesAreRejected()
    {
        var expired = UpdateBytes(9_000_000_001, _time.GetUtcNow().AddDays(-1));
        Assert.Contains("expired", Repository(_publicKey).InstallUpdate(expired, Sign(expired)).Message);

        var noExpiry = UpdateBytes(9_000_000_002, null);
        Assert.Contains("expiry", Repository(_publicKey).InstallUpdate(noExpiry, Sign(noExpiry)).Message);
    }

    [Fact]
    public void RollbackToAnOlderVersionIsRejected()
    {
        var repository = Repository(_publicKey);
        var newer = UpdateBytes(9_000_000_005, _time.GetUtcNow().AddDays(30));
        Assert.True(repository.InstallUpdate(newer, Sign(newer)).Installed);

        var older = UpdateBytes(9_000_000_003, _time.GetUtcNow().AddDays(30));
        var result = repository.InstallUpdate(older, Sign(older));
        Assert.False(result.Installed);
        Assert.Contains("rollback", result.Message);

        var same = repository.InstallUpdate(newer, Sign(newer));
        Assert.Contains("already installed", same.Message);

        var bundledVersion = UpdateBytes(1, _time.GetUtcNow().AddDays(30));
        Assert.False(repository.InstallUpdate(bundledVersion, Sign(bundledVersion)).Installed);
    }

    [Fact]
    public void TamperingWithTheInstalledUpdateFallsBackToBundledRules()
    {
        var repository = Repository(_publicKey);
        var bytes = UpdateBytes(9_000_000_001, _time.GetUtcNow().AddDays(30));
        repository.InstallUpdate(bytes, Sign(bytes));

        var tampered = File.ReadAllText(repository.InstalledRulesFile).Replace("Wurst Client", "Wurst Clientx");
        File.WriteAllText(repository.InstalledRulesFile, tampered);

        var reloaded = Repository(_publicKey);
        Assert.Equal(RuleSource.Bundled, reloaded.Active.Source);
        Assert.Contains(reloaded.Active.Warnings, w => w.Contains("signature verification"));
    }

    [Fact]
    public void AnInstalledUpdateThatExpiresFallsBackToBundledRules()
    {
        var bytes = UpdateBytes(9_000_000_001, _time.GetUtcNow().AddDays(1));
        Repository(_publicKey).InstallUpdate(bytes, Sign(bytes));
        _time.Advance(TimeSpan.FromDays(2));
        var reloaded = Repository(_publicKey);
        Assert.Equal(RuleSource.Bundled, reloaded.Active.Source);
        Assert.Contains(reloaded.Active.Warnings, w => w.Contains("expired"));
    }

    private sealed class FeedHandler(Dictionary<string, byte[]> files) : HttpMessageHandler
    {
        public int Calls { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            var name = request.RequestUri!.Segments[^1];
            return Task.FromResult(files.TryGetValue(name, out var body)
                ? new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(body) }
                : new HttpResponseMessage(HttpStatusCode.NotFound));
        }
    }

    private (RuleUpdateService Service, FeedHandler Handler, RuleRepository Repository) UpdateService(AppConfiguration config, Dictionary<string, byte[]> files)
    {
        var handler = new FeedHandler(files);
        var repository = new RuleRepository(_paths, () => RuleUpdateService.TrustedKeys(config), time: _time, platform: "windows");
        repository.Load();
        var http = new GuardedHttpClient(new NetworkAccessPolicy(() => config), new NetworkActivityLog(_paths.NetworkActivityLogFile), handler, _time);
        return (new RuleUpdateService(repository, http, () => config, _paths, time: _time), handler, repository);
    }

    [Fact]
    public async Task NoTrustedSourceMeansNoRequestAndAClearExplanation()
    {
        var config = ConfigurationService.CreateDefault();
        var (service, handler, _) = UpdateService(config, []);
        var status = await service.CheckForUpdatesAsync(CancellationToken.None);
        Assert.Equal(0, handler.Calls);
        Assert.Contains("No trusted update source has been configured", status.Message);
    }

    [Fact]
    public async Task OfflineModeBlocksUpdateChecksEvenWhenConfigured()
    {
        var config = ConfigurationService.CreateDefault();
        config.RuleUpdates.Enabled = true;
        config.RuleUpdates.Endpoint = "https://rules.example.org/feed";
        config.RuleUpdates.AdditionalTrustedPublicKeys = [_publicKey];
        var (service, handler, _) = UpdateService(config, []);
        var status = await service.CheckForUpdatesAsync(CancellationToken.None);
        Assert.Equal(0, handler.Calls);
        Assert.Contains("Offline mode", status.Message);
    }

    [Fact]
    public async Task ConfiguredFeedInstallsASignedUpdate()
    {
        var bytes = UpdateBytes(9_000_000_010, _time.GetUtcNow().AddDays(30));
        var config = ConfigurationService.CreateDefault();
        config.Privacy.OfflineMode = false;
        config.RuleUpdates.Enabled = true;
        config.RuleUpdates.Endpoint = "https://rules.example.org/feed";
        config.RuleUpdates.AdditionalTrustedPublicKeys = [_publicKey];
        var (service, handler, repository) = UpdateService(config, new() { ["rules.json"] = bytes, ["rules.json.sig"] = Encoding.UTF8.GetBytes(Sign(bytes)) });

        var status = await service.CheckForUpdatesAsync(CancellationToken.None);

        Assert.True(status.LastSucceeded, status.Message);
        Assert.Equal(2, handler.Calls);
        Assert.Equal(9_000_000_010, repository.Active.Database.DatabaseVersion);
        Assert.Equal(status.Message, service.ReadStatus().Message);
    }

    [Fact]
    public async Task ATamperedDownloadIsRejected()
    {
        var bytes = UpdateBytes(9_000_000_010, _time.GetUtcNow().AddDays(30));
        var signature = Sign(bytes);
        bytes[^3] ^= 1;
        var config = ConfigurationService.CreateDefault();
        config.Privacy.OfflineMode = false;
        config.RuleUpdates.Enabled = true;
        config.RuleUpdates.Endpoint = "https://rules.example.org/feed";
        config.RuleUpdates.AdditionalTrustedPublicKeys = [_publicKey];
        var (service, _, repository) = UpdateService(config, new() { ["rules.json"] = bytes, ["rules.json.sig"] = Encoding.UTF8.GetBytes(signature) });

        var status = await service.CheckForUpdatesAsync(CancellationToken.None);

        Assert.False(status.LastSucceeded);
        Assert.Equal(RuleSource.Bundled, repository.Active.Source);
    }
}
