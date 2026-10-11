using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Matching;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Scanner.Discovery;
using CleanerPro.TestSupport;

namespace CleanerPro.Scanner.Tests;

public sealed class ScanEngineTests : IDisposable
{
    private static readonly CompiledRuleDatabase Database = RuleDatabaseLoader.Load(RuleRepository.ReadBundledBytes(), "windows").Database!;

    private readonly TempDirectory _temp = new();
    private readonly AppPaths _paths;
    private readonly AppConfiguration _config = ConfigurationService.CreateDefault();
    private readonly string _game;

    public ScanEngineTests()
    {
        _paths = new AppPaths(_temp.Combine("data"));
        _paths.EnsureCreated();
        _game = _temp.CreateDirectory("Roaming", ".minecraft");
        _config.Scan.InspectStartupEntries = false;
    }

    public void Dispose() => _temp.Dispose();

    private LocationTemplateResolver Resolver() => new(name => name switch
    {
        "LOCALAPPDATA" => _temp.Combine("Local"),
        "APPDATA" => _temp.Combine("Roaming"),
        "USERPROFILE" => _temp.Combine("Profile"),
        "WINDIR" => _temp.Combine("Windows"),
        _ => null,
    });

    private ScanEngine Engine(ScanResultCache? cache = null, Func<(IReadOnlyList<StartupEntry>, string?)>? startup = null) =>
        new(() => _config, () => Database, cache ?? new ScanResultCache(Path.Combine(_paths.CacheDirectory, "scan-cache.json")),
            resolver: Resolver(), startupReader: startup ?? (() => ([], null)), javaEnvironmentReader: () => ([], null));

    private ScanScope Scope(ScanMode mode = ScanMode.Full)
    {
        var discovery = new InstallationDiscoveryService(new DiscoveryEnvironment(_temp.Combine("Roaming"), _temp.Combine("Local"), _temp.Combine("Profile"))).Discover();
        return new ScanScopeBuilder(() => _config, () => Database, _paths, Resolver(), javaEnvironment: () => [], downloadLocations: () => []).Build(mode, discovery);
    }

    private void CreateFixtureInstallation()
    {
        new JarBuilder().FabricMod("wurst", "Wurst Client").EmptyClasses("net/wurstclient/WurstInitializer.class").Text("wurst.mixins.json", "{}").WriteTo(Path.Combine(_game, "mods", "wurst.jar"));
        new JarBuilder().FabricMod("sodium").EmptyClasses("net/caffeinemc/mods/sodium/client/SodiumClientMod.class").WriteTo(Path.Combine(_game, "mods", "sodium.jar"));
        new JarBuilder().FabricMod("plainmod").EmptyClasses("com/example/plain/Main.class").WriteTo(Path.Combine(_game, "mods", "plain.jar"));
        new JarBuilder().FabricMod("othermod").Bytes("net/example/InfectedMain.class", FractureiserFixtures.Sig1Class()).WriteTo(Path.Combine(_game, "mods", "infected.jar"));
        _temp.WriteText("Roaming/.minecraft/wurst/enabled-hacks.json", "[\"Killaura\"]");
        _temp.WriteText("Roaming/.minecraft/saves/world/level.dat", "world");
        _temp.WriteText("Roaming/.minecraft/options.txt", "fov:70");
    }

    [Fact]
    public async Task FullScanFindsRealFilesAndClassifiesThemWithEvidence()
    {
        CreateFixtureInstallation();
        var progress = new List<ScanProgress>();
        var session = await Engine().RunAsync(Scope(), new SynchronousProgress(progress.Add), null, CancellationToken.None);

        Assert.Equal(ScanState.Completed, session.State);
        var wurst = Assert.Single(session.Findings, f => f.Path.EndsWith("wurst.jar", StringComparison.Ordinal));
        Assert.Equal(Classification.KnownMatch, wurst.Classification);
        Assert.NotNull(wurst.Sha256);
        Assert.Equal(Classification.KnownMatch, Assert.Single(session.Findings, f => f.Path.EndsWith("infected.jar", StringComparison.Ordinal)).Classification);
        Assert.Equal(Classification.KnownMatch, Assert.Single(session.Findings, f => f.Path.EndsWith("enabled-hacks.json", StringComparison.Ordinal)).Classification);
        Assert.Contains(session.Findings, f => f.IsDirectory && f.Path.EndsWith("wurst", StringComparison.Ordinal));
        Assert.DoesNotContain(session.Findings, f => f.Path.EndsWith("sodium.jar", StringComparison.Ordinal) || f.Path.EndsWith("plain.jar", StringComparison.Ordinal));
        Assert.DoesNotContain(session.Findings, f => f.Path.Contains("level.dat", StringComparison.Ordinal));

        Assert.True(session.Statistics.FilesInspected >= 6);
        Assert.Equal(session.Findings.Count, session.Statistics.UniqueFilesFlagged);
        Assert.True(session.Statistics.ArchivesInspected >= 4);
        Assert.NotEmpty(session.Limitations);
        Assert.Equal(Database.DisplayVersion, session.RulesVersion);
        Assert.NotEmpty(progress);
        Assert.Equal(ScanStage.Completed, progress[^1].Stage);
    }

    [Fact]
    public async Task OverlappingRootsDoNotCountFilesTwice()
    {
        CreateFixtureInstallation();
        var scope = new ScanScope
        {
            Mode = ScanMode.Custom,
            Roots =
            [
                new ScanRoot { Path = _game, Kind = ScanRootKind.CustomDirectory, Reason = "a", InstallationRoot = _game },
                new ScanRoot { Path = Path.Combine(_game, "mods"), Kind = ScanRootKind.CustomDirectory, Reason = "b", InstallationRoot = _game },
            ],
        };
        var session = await Engine().RunAsync(scope, null, null, CancellationToken.None);
        Assert.Single(session.Findings, f => f.Path.EndsWith("wurst.jar", StringComparison.Ordinal));
        Assert.Equal(session.Statistics.FilesDiscovered, session.Statistics.FilesInspected + session.Statistics.FilesSkipped);
    }

    [Fact]
    public async Task UnchangedCleanFilesAreReusedOnTheNextScan()
    {
        CreateFixtureInstallation();
        var cache = new ScanResultCache(Path.Combine(_paths.CacheDirectory, "scan-cache.json"));
        var first = await Engine(cache).RunAsync(Scope(), null, null, CancellationToken.None);
        var second = await Engine(cache).RunAsync(Scope(), null, null, CancellationToken.None);

        Assert.Equal(0, first.Statistics.CacheHits);
        Assert.True(second.Statistics.CacheHits >= 2); // sodium.jar, plain.jar, options.txt …
        Assert.Equal(first.Findings.Count, second.Findings.Count);

        _config.Detection.ReuseVerifiedResults = false;
        var third = await Engine(cache).RunAsync(Scope(), null, null, CancellationToken.None);
        Assert.Equal(0, third.Statistics.CacheHits);
    }

    [Fact]
    public void CacheKeysRoundTripExactly()
    {
        // Regression: Windows path keys are upper-case ("C:\\USERS\\…"); a key naming policy once changed them on save.
        var file = Path.Combine(_paths.CacheDirectory, "roundtrip.json");
        var cache = new ScanResultCache(file);
        var when = new DateTimeOffset(2026, 10, 11, 0, 0, 0, TimeSpan.Zero);
        cache.MarkClean(@"C:\USERS\PLAYER\APPDATA\ROAMING\.MINECRAFT\MODS\A.JAR", 10, when, new string('a', 64), "ctx");
        cache.Save();

        var reloaded = new ScanResultCache(file);
        reloaded.Load();
        Assert.True(reloaded.IsVerifiedClean(@"C:\USERS\PLAYER\APPDATA\ROAMING\.MINECRAFT\MODS\A.JAR", 10, when, "ctx"));
        Assert.False(reloaded.IsVerifiedClean(@"C:\USERS\PLAYER\APPDATA\ROAMING\.MINECRAFT\MODS\A.JAR", 11, when, "ctx"));
        Assert.False(reloaded.IsVerifiedClean(@"C:\USERS\PLAYER\APPDATA\ROAMING\.MINECRAFT\MODS\A.JAR", 10, when, "other-rules"));
    }

    [Fact]
    public async Task FilesAboveTheSizeLimitAreSkippedButNamesAreStillChecked()
    {
        _config.Scan.MaxFileSizeMegabytes = 1;
        _temp.WriteBytes("Roaming/.minecraft/mods/wurst-big.jar", new byte[2 * 1024 * 1024]);
        var session = await Engine().RunAsync(Scope(), null, null, CancellationToken.None);
        Assert.Contains(session.Skipped, s => s.Reason == SkipReason.TooLarge);
        var finding = Assert.Single(session.Findings);
        Assert.Equal(Classification.Unverified, finding.Classification);
    }

    [Fact]
    public async Task CorruptArchivesAreReportedWithoutStoppingTheScan()
    {
        _temp.WriteText("Roaming/.minecraft/mods/broken.jar", "this is not a zip");
        new JarBuilder().FabricMod("wurst").EmptyClasses("net/wurstclient/A.class").WriteTo(Path.Combine(_game, "mods", "w.jar"));
        var session = await Engine().RunAsync(Scope(), null, null, CancellationToken.None);
        Assert.Equal(ScanState.Completed, session.State);
        Assert.Contains(session.Skipped, s => s.Reason == SkipReason.CorruptArchive && s.Path.EndsWith("broken.jar", StringComparison.Ordinal));
        Assert.Single(session.Findings, f => f.Path.EndsWith("w.jar", StringComparison.Ordinal));
    }

    [Fact]
    public async Task CancellationProducesACancelledSessionWithPartialResults()
    {
        for (var i = 0; i < 50; i++)
        {
            _temp.WriteText($"Roaming/.minecraft/config/file{i}.json", "{}");
        }

        using var cts = new CancellationTokenSource();
        using var pause = new PauseController();
        pause.Pause(); // hold the pipeline so cancellation happens mid-scan, deterministically
        var task = Engine().RunAsync(Scope(), null, pause, cts.Token);
        await Task.Delay(200);
        cts.Cancel();
        var session = await task.WaitAsync(TimeSpan.FromSeconds(30));

        Assert.Equal(ScanState.Cancelled, session.State);
        Assert.Contains(session.Notes, n => n.Contains("cancelled", StringComparison.OrdinalIgnoreCase));
        Assert.NotNull(session.CompletedAtUtc);
        Assert.True(session.Statistics.FilesInspected < 50);
    }

    [Fact]
    public async Task CancellingARunningScanStopsPromptly()
    {
        for (var i = 0; i < 400; i++)
        {
            new JarBuilder().FabricMod($"mod{i}").EmptyClasses($"com/example/m{i}/Main.class").WriteTo(Path.Combine(_game, "mods", $"m{i}.jar"));
        }

        _config.Performance.LowResourceMode = true; // one worker and a pause between files
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(150));
        var watch = System.Diagnostics.Stopwatch.StartNew();
        var session = await Engine().RunAsync(Scope(), null, null, cts.Token).WaitAsync(TimeSpan.FromSeconds(30));
        watch.Stop();

        Assert.True(session.State is ScanState.Cancelled or ScanState.Completed);
        if (session.State == ScanState.Cancelled)
        {
            Assert.True(session.Statistics.FilesInspected < 400);
        }

        Assert.True(watch.Elapsed < TimeSpan.FromSeconds(10));
    }

    [Fact]
    public async Task PauseHoldsTheScanUntilResumed()
    {
        CreateFixtureInstallation();
        using var pause = new PauseController();
        pause.Pause();
        var task = Engine().RunAsync(Scope(), null, pause, CancellationToken.None);
        await Task.Delay(400);
        Assert.False(task.IsCompleted);
        pause.Resume();
        var session = await task.WaitAsync(TimeSpan.FromSeconds(30));
        Assert.Equal(ScanState.Completed, session.State);
    }

    [Fact]
    public async Task ResourceLimitsAreRespected()
    {
        CreateFixtureInstallation();
        _config.Performance.LowResourceMode = true;
        _config.Performance.MaxQueuedFiles = 16;
        _config.Performance.MaxMemoryMegabytes = 64;
        var session = await Engine().RunAsync(Scope(), null, null, CancellationToken.None);
        Assert.Equal(ScanState.Completed, session.State);
        Assert.Contains(session.Findings, f => f.Path.EndsWith("wurst.jar", StringComparison.Ordinal));
    }

    [Fact]
    public async Task DocumentedSystemLocationsAreChecked()
    {
        var edge = _temp.CreateDirectory("Local", "Microsoft Edge");
        File.WriteAllText(Path.Combine(edge, "libWebGL64.jar"), "placeholder");
        File.WriteAllText(Path.Combine(edge, ".ref"), "1");

        var scope = Scope(ScanMode.Quick);
        Assert.Contains(scope.Roots, r => r.Kind == ScanRootKind.SystemArtifactLocation && r.Path == edge);
        var session = await Engine().RunAsync(scope, null, null, CancellationToken.None);

        var folder = Assert.Single(session.Findings, f => f.Path == edge);
        Assert.True(folder.IsDirectory && folder.IsSystemArtifact);
        Assert.Equal(Classification.HighConfidenceSuspicion, folder.Classification);
        Assert.Equal(Classification.KnownMatch, Assert.Single(session.Findings, f => f.Path.EndsWith("libWebGL64.jar", StringComparison.Ordinal)).Classification);
    }

    [Fact]
    public async Task StartupEntriesAreInspectedReadOnly()
    {
        _config.Scan.InspectStartupEntries = true;
        var scope = Scope(ScanMode.Quick) with { IncludeStartupInspection = true };
        var entries = new List<StartupEntry>
        {
            new(@"HKCU\Run", "Microsoft Edge", @"javaw -jar ""C:\Users\x\AppData\Local\Microsoft Edge\libWebGL64.jar"""),
            new(@"HKCU\Run", "Discord", @"C:\Users\x\AppData\Local\Discord\Update.exe --processStart Discord.exe"),
        };
        var session = await Engine(startup: () => (entries, null)).RunAsync(scope, null, null, CancellationToken.None);
        var finding = Assert.Single(session.Findings);
        Assert.EndsWith("Microsoft Edge", finding.Path, StringComparison.Ordinal);
        Assert.Contains(session.Notes, n => n.Contains("2 per-user startup entries"));
    }

    [Fact]
    public void QuickScopeIsExplicitAndExcludesApplicationData()
    {
        CreateFixtureInstallation();
        var scope = Scope(ScanMode.Quick);
        Assert.Contains(scope.Roots, r => r.Path == _game && !r.Recursive);
        Assert.Contains(scope.Roots, r => r.Path == Path.Combine(_game, "mods") && r.Recursive);
        Assert.Contains(scope.Roots, r => r.Path == Path.Combine(_game, "wurst")); // derived from rule leftovers
        Assert.Contains(_paths.DataRoot, scope.ExcludedPaths);
        Assert.All(scope.Roots, r => Assert.False(string.IsNullOrWhiteSpace(r.Reason)));
    }

    [Fact]
    public void DisabledInstallationsAreNotScanned()
    {
        CreateFixtureInstallation();
        _config.Scan.DisabledInstallationIds = [InstallationDiscoveryService.CreateId(_game)];
        Assert.DoesNotContain(Scope(ScanMode.Full).Roots, r => r.Path == _game);
    }

    private sealed class SynchronousProgress(Action<ScanProgress> handler) : IProgress<ScanProgress>
    {
        private readonly object _gate = new();

        public void Report(ScanProgress value)
        {
            lock (_gate)
            {
                handler(value);
            }
        }
    }
}
