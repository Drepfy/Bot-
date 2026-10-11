using System.Net;
using System.Text.Json;
using CleanerPro.Configuration;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Matching;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure;
using CleanerPro.Privacy;
using CleanerPro.Quarantine;
using CleanerPro.Reporting;
using CleanerPro.Scanner;
using CleanerPro.Scanner.Discovery;
using CleanerPro.TestSupport;

namespace CleanerPro.Integration.Tests;

/// <summary>
/// Exercises the real services together on a synthetic Minecraft installation built from harmless fixtures:
/// discovery → scope → scan → quarantine → verification → reports → history → dashboard.
/// </summary>
public sealed class EndToEndTests : IDisposable
{
    private readonly TempDirectory _temp = new();
    private readonly AppPaths _paths;
    private readonly ConfigurationService _configuration;
    private readonly RuleRepository _rules;
    private readonly OperationLog _operations;
    private readonly HistoryStore _history;
    private readonly QuarantineService _quarantine;
    private readonly ScanEngine _engine;
    private readonly ScanScopeBuilder _scopes;
    private readonly InstallationDiscoveryService _discovery;
    private readonly LocationTemplateResolver _resolver;
    private readonly CountingHandler _network = new();
    private readonly string _game;

    public EndToEndTests()
    {
        _paths = new AppPaths(_temp.Combine("LocalAppData", "MinecraftCleanerPro"));
        _paths.EnsureCreated();
        var policy = TestPolicies.Create();
        _configuration = new ConfigurationService(_paths, policy);
        _configuration.Load();
        var config = _configuration.CloneCurrent();
        config.Scan.InspectStartupEntries = false;
        Assert.True(_configuration.Save(config, "test").Succeeded);

        _rules = new RuleRepository(_paths, () => RuleUpdateService.TrustedKeys(_configuration.Current), platform: "windows");
        _rules.Load();
        _operations = new OperationLog(_paths.OperationsLogFile);
        _history = new HistoryStore(_paths);
        _quarantine = new QuarantineService(() => EffectiveLocations.QuarantineDirectory(_configuration.Current, _paths), policy, _operations);
        _resolver = new LocationTemplateResolver(name => name switch
        {
            "LOCALAPPDATA" => _temp.Combine("LocalAppData"),
            "APPDATA" => _temp.Combine("Roaming"),
            "USERPROFILE" => _temp.Combine("Profile"),
            "WINDIR" => _temp.Combine("Windows"),
            _ => null,
        });
        _engine = new ScanEngine(() => _configuration.Current, () => _rules.Active.Database, new ScanResultCache(Path.Combine(_paths.CacheDirectory, "scan-cache.json")),
            resolver: _resolver, startupReader: () => ([], null), javaEnvironmentReader: () => ([], null));
        _scopes = new ScanScopeBuilder(() => _configuration.Current, () => _rules.Active.Database, _paths, _resolver, javaEnvironment: () => [], downloadLocations: () => []);
        _discovery = new InstallationDiscoveryService(new DiscoveryEnvironment(_temp.Combine("Roaming"), _temp.Combine("LocalAppData"), _temp.Combine("Profile")));

        _game = _temp.CreateDirectory("Roaming", ".minecraft");
        _temp.CreateDirectory("Roaming", ".minecraft", "versions", "fabric-loader-0.16.0-1.21.1");
        new JarBuilder().FabricMod("wurst", "Wurst Client").EmptyClasses("net/wurstclient/WurstInitializer.class").Text("wurst.mixins.json", "{}").WriteTo(Path.Combine(_game, "mods", "wurst-7.45.jar"));
        new JarBuilder().FabricMod("sodium").EmptyClasses("net/caffeinemc/mods/sodium/client/SodiumClientMod.class").WriteTo(Path.Combine(_game, "mods", "sodium.jar"));
        new JarBuilder().FabricMod("fabric-api").Nested("META-INF/jars/fabric-api-base.jar", new JarBuilder().FabricMod("fabric-api-base")).WriteTo(Path.Combine(_game, "mods", "fabric-api.jar"));
        new JarBuilder().FabricMod("baritone").Text("mixins.baritone.json", "{}").WriteTo(Path.Combine(_game, "mods", "baritone.jar"));
        new JarBuilder().FabricMod("coolmod").Bytes("net/example/InfectedMain.class", FractureiserFixtures.Sig1Class()).WriteTo(Path.Combine(_game, "mods", "coolmod-infected.jar"));
        _temp.WriteText("Roaming/.minecraft/wurst/enabled-hacks.json", "[\"Killaura\"]");
        _temp.WriteText("Roaming/.minecraft/options.txt", "fov:70");
    }

    public void Dispose() => _temp.Dispose();

    [Fact]
    public async Task DeleteAllApplicationDataRemovesEverythingTheAppStoredAndNothingElse()
    {
        var session = await _engine.RunAsync(_scopes.Build(ScanMode.Full, _discovery.Discover()), null, null, CancellationToken.None);
        _history.Save(session);
        var wurst = session.Findings.Single(f => f.Path.EndsWith("wurst-7.45.jar", StringComparison.Ordinal));
        Assert.True(_quarantine.Quarantine(new QuarantineRequest { Path = wurst.Path, ApprovedRoots = [_game], ExpectedSha256 = wurst.Sha256 }).Succeeded);
        var reports = new ReportService(() => _configuration.Current, _paths, _history, _operations);
        reports.Export(session, ReportFormat.Html, RedactionLevel.PersonalPaths);
        File.WriteAllText(Path.Combine(_paths.LogsDirectory, "app-20261011.log"), "log line");
        var config = _configuration.CloneCurrent();
        config.Scan.MaxDirectoryDepth = 9;
        Assert.True(_configuration.Save(config, "test").Succeeded);
        var cacheCleared = false;
        var networkCleared = false;
        var sodium = Path.Combine(_game, "mods", "sodium.jar");

        var eraser = new ApplicationDataEraser(_paths, _configuration, _history, reports, _operations, _quarantine,
            [("Scan cache", () => cacheCleared = true), ("Network activity log", () => networkCleared = true)]);
        Assert.Contains(eraser.Describe(), d => d.Contains("1 item(s)", StringComparison.Ordinal) && d.Contains("cannot be restored", StringComparison.Ordinal));

        var result = eraser.EraseAll();

        Assert.True(result.Succeeded, string.Join(" | ", result.Problems));
        Assert.Empty(_quarantine.ListEntries(includeRestored: true));
        Assert.Empty(_history.ListSummaries());
        Assert.Empty(Directory.GetFiles(reports.ReportsDirectory));
        Assert.Empty(_operations.ReadAll());
        Assert.Empty(Directory.GetFiles(_paths.LogsDirectory));
        Assert.Empty(Directory.GetFiles(_paths.ConfigBackupDirectory));
        Assert.Equal(new AppConfiguration().Scan.MaxDirectoryDepth, _configuration.Current.Scan.MaxDirectoryDepth);
        Assert.True(cacheCleared && networkCleared);
        Assert.True(File.Exists(sodium)); // Minecraft files are never touched.
    }

    private async Task<ScanSession> Scan(ScanMode mode = ScanMode.Quick)
    {
        var discovery = _discovery.Discover(_configuration.Current.Scan.CustomDirectories);
        var scope = _scopes.Build(mode, discovery);
        var session = await _engine.RunAsync(scope, null, null, CancellationToken.None);
        _history.Save(session);
        return session;
    }

    [Fact]
    public async Task CompleteCleanupWorkflow()
    {
        // 1. Discovery finds the installation and its loader.
        var installation = Assert.Single(_discovery.Discover().Installations);
        Assert.Contains(ModLoader.Fabric, installation.ModLoaders);

        // 2. Scan.
        var session = await Scan();
        Assert.Equal(ScanState.Completed, session.State);
        var wurst = Assert.Single(session.Findings, f => f.Path.EndsWith("wurst-7.45.jar", StringComparison.Ordinal));
        var infected = Assert.Single(session.Findings, f => f.Path.EndsWith("coolmod-infected.jar", StringComparison.Ordinal));
        var baritone = Assert.Single(session.Findings, f => f.Path.EndsWith("baritone.jar", StringComparison.Ordinal));
        Assert.Equal(Classification.KnownMatch, wurst.Classification);
        Assert.Equal(Classification.KnownMatch, infected.Classification);
        Assert.Equal(Classification.NeedsReview, baritone.Classification);
        Assert.DoesNotContain(session.Findings, f => f.Path.EndsWith("sodium.jar", StringComparison.Ordinal) || f.Path.EndsWith("fabric-api.jar", StringComparison.Ordinal));

        // 3. Quarantine the known matches (user-approved), leaving the review item alone.
        var approvedRoots = session.Scope.Roots.Select(r => r.InstallationRoot ?? r.Path).Distinct().ToList();
        foreach (var finding in new[] { wurst, infected })
        {
            var result = _quarantine.Quarantine(new QuarantineRequest
            {
                Path = finding.Path,
                ApprovedRoots = approvedRoots,
                ExpectedSha256 = finding.Sha256,
                ExpectedSize = finding.SizeBytes,
                FindingId = finding.Id,
                SessionId = session.Id,
                RuleIds = finding.RuleMatches.Select(m => m.RuleId).ToList(),
            });
            Assert.True(result.Succeeded, result.Message);
        }

        // 4. Post-cleanup verification rescans the affected folders and compares by path and hash.
        var verificationScope = _scopes.BuildVerification(session);
        var verification = await _engine.RunAsync(verificationScope, null, null, CancellationToken.None, session.Id);
        _history.Save(verification);
        var report = VerificationService.Compare(session, verification, _operations.ReadAll());
        _history.SaveVerification(report);

        Assert.Equal(VerificationOutcome.Quarantined, report.Items.Single(i => i.FindingId == wurst.Id).Outcome);
        Assert.Equal(VerificationOutcome.Quarantined, report.Items.Single(i => i.FindingId == infected.Id).Outcome);
        Assert.Equal(VerificationOutcome.StillPresent, report.Items.Single(i => i.FindingId == baritone.Id).Outcome);
        Assert.Contains(report.Notes, n => n.Contains("not proof"));

        // 5. Restore one item and verify again: it is reported as present, not as removed.
        var entry = _quarantine.ListEntries().Single(e => e.FindingId == wurst.Id);
        Assert.True(_quarantine.Restore(new RestoreRequest(entry.Id, RestoreMode.OriginalLocation)).Succeeded);
        var verification2 = await _engine.RunAsync(_scopes.BuildVerification(session), null, null, CancellationToken.None, session.Id);
        var report2 = VerificationService.Compare(session, verification2, _operations.ReadAll());
        Assert.Equal(VerificationOutcome.StillPresent, report2.Items.Single(i => i.FindingId == wurst.Id).Outcome);

        // 6. Permanent deletion of the remaining quarantined item, then the dashboard reflects real state.
        var plan = _quarantine.PrepareDeletion(_quarantine.ListEntries().Select(e => e.Id));
        Assert.Single(plan.Targets);
        Assert.True(_quarantine.ExecuteDeletion(plan, plan.Token).Executed);
        var report3 = VerificationService.Compare(session, verification2, _operations.ReadAll());
        Assert.Equal(VerificationOutcome.Deleted, report3.Items.Single(i => i.FindingId == infected.Id).Outcome);

        var dashboard = DashboardStatistics.Compute(_history, _quarantine, _rules.Active.Database.DisplayVersion);
        Assert.Equal(session.Id, dashboard.LastScan!.Id);
        Assert.Equal(session.Statistics.FilesInspected, dashboard.FilesInspected);
        Assert.Equal(0, dashboard.QuarantinedFiles);
        Assert.Equal(session.Findings.Count(f => f.Classification == Classification.KnownMatch), dashboard.ConfirmedMatches);
    }

    [Fact]
    public async Task ReportsReflectActualDataInAllFormats()
    {
        var session = await Scan();
        var finding = session.Findings.First(f => f.Classification == Classification.KnownMatch);
        _quarantine.Quarantine(new QuarantineRequest { Path = finding.Path, ApprovedRoots = [_game], ExpectedSha256 = finding.Sha256, FindingId = finding.Id, SessionId = session.Id });

        var reports = new ReportService(() => _configuration.Current, _paths, _history, _operations);
        var redactor = new PathRedactor(RedactionLevel.PersonalPaths, [(_temp.Path, "%TESTROOT%")]);
        var document = ReportBuilder.Build(session, _operations.ReadAll(), null, redactor, _configuration.Current.Privacy);

        var json = ReportExporter.Render(document, ReportFormat.Json);
        var text = ReportExporter.Render(document, ReportFormat.Txt);
        var html = ReportExporter.Render(document, ReportFormat.Html);

        Assert.DoesNotContain(_temp.Path, json);
        Assert.DoesNotContain(_temp.Path, text);
        Assert.DoesNotContain(_temp.Path, html);
        Assert.Contains("%TESTROOT%", text);

        using var parsed = JsonDocument.Parse(json);
        Assert.Equal(session.Findings.Count, parsed.RootElement.GetProperty("findings").GetArrayLength());
        Assert.Equal(session.Statistics.FilesInspected, parsed.RootElement.GetProperty("statistics").GetProperty("filesInspected").GetInt64());
        Assert.Equal(session.RulesVersion, parsed.RootElement.GetProperty("rulesVersion").GetString());
        Assert.Contains(parsed.RootElement.GetProperty("operations").EnumerateArray(), o => o.GetProperty("type").GetString() == "Quarantine");

        Assert.Contains("CLASSIFICATION BREAKDOWN", text);
        Assert.Contains("Known match", text);
        Assert.Contains("LIMITATIONS", text);
        Assert.Contains($"Unique items flagged:                 {session.Statistics.UniqueFilesFlagged}", text);

        Assert.StartsWith("<!DOCTYPE html>", html);
        Assert.DoesNotContain("<script", html, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("Content-Security-Policy", html);

        var exported = reports.Export(session, ReportFormat.Html, RedactionLevel.PersonalPaths);
        Assert.True(File.Exists(exported));
        Assert.Contains(reports.ListReports(), r => r.FullName == exported);
        Assert.Equal(1, reports.DeleteAllReports());
    }

    [Fact]
    public void HtmlReportsEncodeUntrustedText()
    {
        var session = new ScanSession
        {
            Id = "s1", Mode = ScanMode.Custom, StartedAtUtc = DateTimeOffset.UtcNow, AppVersion = "1", RulesVersion = "r",
            Scope = new ScanScope { Mode = ScanMode.Custom },
            Findings =
            {
                new Finding
                {
                    Id = "f", Path = "/tmp/<script>alert(1)</script>.jar", Classification = Classification.NeedsReview, Confidence = DetectionConfidence.Low,
                    Severity = ThreatSeverity.Low, Reputation = FileReputation.Unknown, RecommendedAction = RecommendedAction.ManualReview, ConfidenceRationale = "<b>x</b>",
                },
            },
        };
        var html = ReportExporter.Render(ReportBuilder.Build(session, [], null, new PathRedactor(RedactionLevel.None), new PrivacySettings()), ReportFormat.Html);
        Assert.DoesNotContain("<script>", html);
        Assert.Contains("&lt;script&gt;", html);
    }

    [Fact]
    public async Task FileNamesOnlyRedactionHidesFolders()
    {
        var session = await Scan();
        var document = ReportBuilder.Build(session, [], null, new PathRedactor(RedactionLevel.FileNamesOnly), new PrivacySettings());
        var text = ReportExporter.Render(document, ReportFormat.Txt);
        Assert.DoesNotContain(_game, text);
        Assert.Contains("wurst-7.45.jar", text);
    }

    [Fact]
    public async Task HistoryCanBeListedAndDeleted()
    {
        var first = await Scan();
        var second = await Scan(ScanMode.Full);
        var summaries = _history.ListSummaries();
        Assert.Equal(2, summaries.Count);
        Assert.Equal(second.Id, summaries[0].Id);
        Assert.Equal(first.Findings.Count(f => f.Classification == Classification.KnownMatch), summaries[1].KnownMatches);
        Assert.NotNull(_history.Load(first.Id));

        Assert.True(_history.Delete(first.Id));
        Assert.Null(_history.Load(first.Id));
        Assert.Equal(1, _history.DeleteAll());
        Assert.Empty(_history.ListSummaries());
        Assert.Null(_history.Load("../../etc/passwd"));
    }

    [Fact]
    public async Task OfflineScanningMakesNoNetworkRequests()
    {
        var log = new NetworkActivityLog(_paths.NetworkActivityLogFile);
        using var http = new GuardedHttpClient(new NetworkAccessPolicy(() => _configuration.Current), log, _network);
        var updater = new RuleUpdateService(_rules, http, () => _configuration.Current, _paths);

        var session = await Scan(ScanMode.Full);
        var status = await updater.CheckForUpdatesAsync(CancellationToken.None);

        Assert.Equal(ScanState.Completed, session.State);
        Assert.NotEmpty(session.Findings);
        Assert.Equal(0, _network.Calls);
        Assert.Contains("No trusted update source", status.Message);
        Assert.True(_configuration.Current.Privacy.OfflineMode);
    }

    [Fact]
    public async Task ShutdownDuringAScanIsHandledCleanly()
    {
        for (var i = 0; i < 200; i++)
        {
            new JarBuilder().FabricMod($"m{i}").EmptyClasses($"com/m{i}/Main.class").WriteTo(Path.Combine(_game, "mods", $"m{i}.jar"));
        }

        using var appShutdown = new CancellationTokenSource();
        using var pause = new PauseController();
        var scope = _scopes.Build(ScanMode.Full, _discovery.Discover());
        var running = _engine.RunAsync(scope, null, pause, appShutdown.Token);
        pause.Pause();
        await Task.Delay(100);
        appShutdown.Cancel(); // the application is closing
        var session = await running.WaitAsync(TimeSpan.FromSeconds(30));
        _history.Save(session);

        Assert.Equal(ScanState.Cancelled, session.State);
        Assert.Equal(ScanState.Cancelled, _history.Load(session.Id)!.State);
        Assert.True(File.Exists(Path.Combine(_game, "mods", "wurst-7.45.jar"))); // nothing modified by a scan
    }

    [Fact]
    public async Task ScansNeverModifyFiles()
    {
        var before = Directory.EnumerateFiles(_game, "*", SearchOption.AllDirectories)
            .ToDictionary(f => f, f => (FileHasher.Compute(f, false).Sha256, File.GetLastWriteTimeUtc(f)));
        await Scan(ScanMode.Full);
        var after = Directory.EnumerateFiles(_game, "*", SearchOption.AllDirectories)
            .ToDictionary(f => f, f => (FileHasher.Compute(f, false).Sha256, File.GetLastWriteTimeUtc(f)));
        Assert.Equal(before, after);
    }

    [Fact]
    public async Task HarmlessSelfTestFileIsDetectedQuarantinedAndRestored()
    {
        var folder = _temp.CreateDirectory("selftest");
        var file = Path.Combine(folder, "cleanerpro-harmless-test.txt");
        File.WriteAllText(file, "MINECRAFT-CLEANER-PRO HARMLESS TEST FILE v1\nThis file contains no code. It only exists to confirm that detection, quarantine and restore work.\n");

        var scope = _scopes.Build(ScanMode.Custom, _discovery.Discover(), [folder]);
        var session = await _engine.RunAsync(scope, null, null, CancellationToken.None);
        var finding = Assert.Single(session.Findings);
        Assert.Equal(Classification.KnownMatch, finding.Classification);

        var result = _quarantine.Quarantine(new QuarantineRequest { Path = file, ApprovedRoots = [folder], ExpectedSha256 = finding.Sha256 });
        Assert.True(result.Succeeded, result.Message);
        Assert.True(_quarantine.Restore(new RestoreRequest(result.Entry!.Id, RestoreMode.OriginalLocation)).Succeeded);
        Assert.Equal(finding.Sha256, FileHasher.Compute(file, false).Sha256);
    }

    [Fact]
    public void ApplicationDataIsNeverPartOfTheScanScope()
    {
        var config = _configuration.CloneCurrent();
        config.Scan.CustomDirectories = [_temp.Path];
        _configuration.Save(config, "test");
        var scope = _scopes.Build(ScanMode.Full, _discovery.Discover(_configuration.Current.Scan.CustomDirectories));
        Assert.Contains(scope.ExcludedPaths, p => PathKey.IsSameOrWithin(_paths.DataRoot, p) || p == _paths.DataRoot);
    }

    private sealed class CountingHandler : HttpMessageHandler
    {
        public int Calls { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
        }
    }
}
