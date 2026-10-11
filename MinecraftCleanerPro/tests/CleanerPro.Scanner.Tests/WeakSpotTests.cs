using System.Text.Json;
using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Matching;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Scanner.Discovery;
using CleanerPro.Scanner.Inspection;
using CleanerPro.TestSupport;

namespace CleanerPro.Scanner.Tests;

/// <summary>
/// Ways a cheat could get past a file scanner: renamed or disabled jars, Java agents in launcher settings or in
/// JAVA_TOOL_OPTIONS, and copies left in Downloads. Every test uses synthetic files in a temporary folder.
/// </summary>
public sealed class WeakSpotTests : IDisposable
{
    private static readonly CompiledRuleDatabase Database = RuleDatabaseLoader.Load(RuleRepository.ReadBundledBytes(), "windows").Database!;

    private readonly TempDirectory _temp = new();
    private readonly AppPaths _paths;
    private readonly AppConfiguration _config = ConfigurationService.CreateDefault();
    private readonly string _game;

    public WeakSpotTests()
    {
        _paths = new AppPaths(_temp.Combine("data"));
        _paths.EnsureCreated();
        _game = _temp.CreateDirectory("Roaming", ".minecraft");
        _temp.WriteText("Roaming/.minecraft/options.txt", "fov:70");
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

    private static byte[] WurstJar() =>
        new JarBuilder().FabricMod("wurst", "Wurst Client").EmptyClasses("net/wurstclient/WurstInitializer.class").Text("wurst.mixins.json", "{}").Build();

    private ScanScope Scope(ScanMode mode, IReadOnlyList<StartupEntry>? environment = null, IReadOnlyList<DownloadLocation>? downloads = null)
    {
        var discovery = new InstallationDiscoveryService(new DiscoveryEnvironment(_temp.Combine("Roaming"), _temp.Combine("Local"), _temp.Combine("Profile"))).Discover();
        return new ScanScopeBuilder(() => _config, () => Database, _paths, Resolver(), () => environment ?? [], () => downloads ?? []).Build(mode, discovery);
    }

    private Task<ScanSession> Run(ScanScope scope, IReadOnlyList<StartupEntry>? environment = null) =>
        new ScanEngine(() => _config, () => Database, new ScanResultCache(Path.Combine(_paths.CacheDirectory, "scan-cache.json")),
            resolver: Resolver(), startupReader: () => ([], null), javaEnvironmentReader: () => (environment ?? [], null)).RunAsync(scope, null, null, CancellationToken.None);

    [Theory]
    [InlineData("wurst.jar.disabled")]
    [InlineData("cache.dat")]
    [InlineData("no-extension")]
    public async Task RenamedOrDisabledJarsAreInspectedByContent(string fileName)
    {
        _temp.WriteBytes($"Roaming/.minecraft/mods/{fileName}", WurstJar());

        var session = await Run(Scope(ScanMode.Quick));

        var finding = Assert.Single(session.Findings, f => f.Path.EndsWith(fileName, StringComparison.Ordinal));
        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Contains(finding.Evidence, e => e.Kind == IndicatorType.Metadata && e.Description.Contains("JAR/ZIP archive although its name"));
    }

    [Fact]
    public async Task ContentDetectionCanBeTurnedOff()
    {
        _config.Scan.DetectArchivesByContent = false;
        _temp.WriteBytes("Roaming/.minecraft/mods/wurst.jar.disabled", WurstJar());
        var session = await Run(Scope(ScanMode.Quick));
        Assert.DoesNotContain(session.Findings, f => f.Path.EndsWith("wurst.jar.disabled", StringComparison.Ordinal));
    }

    [Fact]
    public void MediaFilesAreNotOpenedToLookForArchives()
    {
        var png = _temp.WriteBytes("Roaming/.minecraft/x.png", WurstJar());
        var dat = _temp.WriteBytes("Roaming/.minecraft/x.dat", WurstJar());
        Assert.False(ArchiveSniffer.LooksLikeArchive(png, new FileInfo(png).Length));
        Assert.True(ArchiveSniffer.LooksLikeArchive(dat, new FileInfo(dat).Length));
        Assert.False(ArchiveSniffer.LooksLikeArchive(_temp.WriteText("Roaming/.minecraft/a.txt", "PK"), 2));
    }

    [Fact]
    public async Task JavaAgentInLauncherProfilesIsReportedAndTheAgentJarIsScanned()
    {
        var agent = _temp.WriteBytes("Tools/agent/injector.jar", WurstJar());
        var profiles = new { profiles = new { pvp = new { name = "PvP", javaArgs = $"-Xmx4G -javaagent:{agent}=silent -XX:+UseG1GC" } } };
        File.WriteAllText(Path.Combine(_game, "launcher_profiles.json"), JsonSerializer.Serialize(profiles));

        var scope = Scope(ScanMode.Quick);
        Assert.Contains(scope.Roots, r => r.Kind == ScanRootKind.ReferencedFile && r.IsFile && r.Path == agent);
        Assert.Contains(Path.Combine(_game, "launcher_profiles.json"), scope.LaunchSettingsFiles);

        var session = await Run(scope);

        var option = Assert.Single(session.Findings, f => f.RuleMatches.Any(m => m.RuleId == "CP-LOAD-0001"));
        Assert.Equal(Classification.NeedsReview, option.Classification);
        Assert.True(option.RequiresManualCleanup);
        Assert.Contains(option.Evidence, e => e.MatchedValue!.Contains("-javaagent:", StringComparison.Ordinal));

        var jar = Assert.Single(session.Findings, f => f.Path == agent);
        Assert.Equal(Classification.KnownMatch, jar.Classification);
        Assert.False(jar.RequiresManualCleanup);

        // The agent jar can be cleaned: its folder is approved, but not the whole scan scope.
        var approved = ScanScopeBuilder.CleanupApprovedRoots(scope);
        Assert.Contains(Path.GetDirectoryName(agent)!, approved);
        Assert.DoesNotContain(agent, approved);
    }

    [Fact]
    public async Task JavaAgentInPrismInstanceSettingsIsReported()
    {
        var instance = _temp.CreateDirectory("Roaming", "PrismLauncher", "instances", "PvP");
        _temp.CreateDirectory("Roaming", "PrismLauncher", "instances", "PvP", ".minecraft", "mods");
        var agent = _temp.WriteBytes("Elsewhere/a.jar", WurstJar());
        File.WriteAllText(Path.Combine(instance, "instance.cfg"), $"name=PvP\nOverrideJavaArgs=true\nJvmArgs=-javaagent:{agent.Replace(@"\", @"\\")}\n");

        var scope = Scope(ScanMode.Quick);
        Assert.Contains(Path.Combine(instance, "instance.cfg"), scope.LaunchSettingsFiles);
        var session = await Run(scope);

        Assert.Contains(session.Findings, f => f.RuleMatches.Any(m => m.RuleId == "CP-LOAD-0001") && f.Path.Contains("instance.cfg", StringComparison.Ordinal));
        Assert.Contains(session.Findings, f => f.Path == agent && f.Classification == Classification.KnownMatch);
    }

    [Fact]
    public async Task JavaToolOptionsWithAnAgentAreReportedForManualRemoval()
    {
        var agent = _temp.WriteBytes("Hidden/x.jar", WurstJar());
        IReadOnlyList<StartupEntry> environment = [new StartupEntry("User environment variable", "JAVA_TOOL_OPTIONS", $"-javaagent:{agent}")];

        var scope = Scope(ScanMode.Quick, environment);
        Assert.True(scope.IncludeJavaEnvironment);
        Assert.Contains(scope.Roots, r => r.Path == agent);

        var session = await Run(scope, environment);
        var variable = Assert.Single(session.Findings, f => f.Path.EndsWith("JAVA_TOOL_OPTIONS", StringComparison.Ordinal));
        Assert.True(variable.RequiresManualCleanup);
        Assert.Contains("Environment Variables", variable.ManualCleanupGuidance);
        Assert.Contains(session.Findings, f => f.Path == agent);
    }

    [Fact]
    public async Task FullScansCheckDownloadsForProgramsAndArchivesOnly()
    {
        var downloads = _temp.CreateDirectory("Profile", "Downloads");
        _temp.WriteBytes("Profile/Downloads/LiquidBounce-installer.exe", [0x4D, 0x5A, 0, 0]);
        _temp.WriteBytes("Profile/Downloads/stuff/wurst.jar", WurstJar());
        _temp.WriteBytes("Profile/Downloads/a/b/c/deep.jar", WurstJar());
        _temp.WriteText("Profile/Downloads/wurst-notes.txt", "not inspected");

        var scope = Scope(ScanMode.Full, downloads: [new DownloadLocation(downloads, "Downloads")]);
        var root = Assert.Single(scope.Roots, r => r.Kind == ScanRootKind.DownloadLocation);
        Assert.Equal(ScanScopeBuilder.DownloadLocationDepth, root.MaxDepth);
        Assert.DoesNotContain(Scope(ScanMode.Quick, downloads: [new DownloadLocation(downloads, "Downloads")]).Roots, r => r.Kind == ScanRootKind.DownloadLocation);

        var session = await Run(scope);
        Assert.Contains(session.Findings, f => f.Path.EndsWith("LiquidBounce-installer.exe", StringComparison.Ordinal) && f.Classification == Classification.NeedsReview);
        Assert.Contains(session.Findings, f => f.Path.EndsWith("wurst.jar", StringComparison.Ordinal) && f.Classification == Classification.KnownMatch);
        Assert.DoesNotContain(session.Findings, f => f.Path.EndsWith("deep.jar", StringComparison.Ordinal));
        Assert.DoesNotContain(session.Findings, f => f.Path.EndsWith("wurst-notes.txt", StringComparison.Ordinal));
    }

    [Theory]
    [InlineData("-Xmx2G -javaagent:C:\\a\\b.jar=opt", "-javaagent", "C:\\a\\b.jar")]
    [InlineData("-javaagent:\"C:\\Program Files\\x\\agent.jar\"", "-javaagent", "C:\\Program Files\\x\\agent.jar")]
    [InlineData("JvmArgs=-javaagent:C:\\\\Users\\\\me\\\\a.jar", "-javaagent", "C:\\Users\\me\\a.jar")]
    [InlineData("-agentpath:/opt/x.so=1", "-agentpath", "/opt/x.so")]
    [InlineData("-agentlib:jdwp=transport=dt_socket", "-agentlib", null)]
    [InlineData("-Xbootclasspath/a:C:\\x.jar;C:\\y.jar", "-Xbootclasspath/a", "C:\\x.jar")]
    public void AgentOptionsAreParsed(string text, string option, string? path)
    {
        var argument = Assert.Single(LaunchSettingsInspector.FindAgentArguments(text));
        Assert.Equal(option, argument.Option);
        Assert.Equal(path, argument.TargetPath);
    }

    [Fact]
    public void ArgumentsWithoutAgentsAreIgnored()
    {
        Assert.Empty(LaunchSettingsInspector.FindAgentArguments("-Xmx4G -XX:+UseG1GC -Dfile.encoding=UTF-8 -Dmy-javaagent=1"));
    }
}
