using CleanerPro.Core.Models;
using CleanerPro.Scanner.Discovery;
using CleanerPro.Scanner.Enumeration;
using CleanerPro.TestSupport;

namespace CleanerPro.Scanner.Tests;

public sealed class EnumerationAndDiscoveryTests : IDisposable
{
    private readonly TempDirectory _temp = new();

    public void Dispose() => _temp.Dispose();

    private static ScanRoot Root(string path, bool recursive = true) => new() { Path = path, Kind = ScanRootKind.CustomDirectory, Reason = "test", Recursive = recursive };

    private static (List<EnumeratedItem> Items, List<SkippedItem> Skipped) Run(SafeFileEnumerator enumerator, ScanRoot root)
    {
        var skipped = new List<SkippedItem>();
        var items = enumerator.Enumerate(root, skipped.Add, () => { }, CancellationToken.None).ToList();
        return (items, skipped);
    }

    [Fact]
    public void EnumeratesFilesAndDirectoriesWithExclusions()
    {
        var root = _temp.CreateDirectory("game");
        _temp.WriteText("game/mods/a.jar", "a");
        _temp.WriteText("game/saves/world/level.dat", "w");
        _temp.WriteText("game/excluded/x.jar", "x");

        var enumerator = new SafeFileEnumerator(new EnumerationSettings
        {
            ExcludedDirectoryNames = ["saves"],
            ExcludedPaths = [_temp.Combine("game", "excluded")],
        });
        var (items, skipped) = Run(enumerator, Root(root));

        Assert.Contains(items, i => i.Path.EndsWith("a.jar", StringComparison.Ordinal));
        Assert.Contains(items, i => i.IsDirectory && i.Path.EndsWith("mods", StringComparison.Ordinal));
        Assert.DoesNotContain(items, i => i.Path.Contains("level.dat", StringComparison.Ordinal) || i.Path.EndsWith("x.jar", StringComparison.Ordinal));
        Assert.Equal(2, skipped.Count(s => s.Reason == SkipReason.Excluded));
    }

    [Fact]
    public void NonRecursiveRootsOnlyListDirectChildren()
    {
        var root = _temp.CreateDirectory("game");
        _temp.WriteText("game/top.json", "{}");
        _temp.WriteText("game/sub/deep.jar", "x");
        var (items, _) = Run(new SafeFileEnumerator(new EnumerationSettings()), Root(root, recursive: false));
        Assert.Contains(items, i => i.Path.EndsWith("top.json", StringComparison.Ordinal));
        Assert.Contains(items, i => i.IsDirectory && i.Path.EndsWith("sub", StringComparison.Ordinal));
        Assert.DoesNotContain(items, i => i.Path.EndsWith("deep.jar", StringComparison.Ordinal));
    }

    [Fact]
    public void DepthLimitIsEnforced()
    {
        var root = _temp.CreateDirectory("game");
        _temp.WriteText("game/a/b/c/d/deep.jar", "x");
        var (items, skipped) = Run(new SafeFileEnumerator(new EnumerationSettings { MaxDepth = 2 }), Root(root));
        Assert.DoesNotContain(items, i => i.Path.EndsWith("deep.jar", StringComparison.Ordinal));
        Assert.Contains(skipped, s => s.Reason == SkipReason.DepthLimit);
    }

    [Fact]
    public void SymbolicLinksAreNotFollowedByDefault()
    {
        var root = _temp.CreateDirectory("game");
        var outside = _temp.CreateDirectory("outside");
        _temp.WriteText("outside/private.jar", "x");
        if (!SymlinkSupport.TryCreateDirectoryLink(Path.Combine(root, "linked"), outside))
        {
            return;
        }

        var (items, skipped) = Run(new SafeFileEnumerator(new EnumerationSettings()), Root(root));
        Assert.DoesNotContain(items, i => i.Path.Contains("private.jar", StringComparison.Ordinal));
        Assert.Contains(skipped, s => s.Reason == SkipReason.ReparsePoint);
    }

    [Fact]
    public void LinksAreFollowedOnlyIntoApprovedRootsWhenEnabled()
    {
        var root = _temp.CreateDirectory("game");
        var approved = _temp.CreateDirectory("approved");
        var unapproved = _temp.CreateDirectory("unapproved");
        _temp.WriteText("approved/ok.jar", "x");
        _temp.WriteText("unapproved/secret.jar", "x");
        if (!SymlinkSupport.TryCreateDirectoryLink(Path.Combine(root, "toApproved"), approved) ||
            !SymlinkSupport.TryCreateDirectoryLink(Path.Combine(root, "toOther"), unapproved))
        {
            return;
        }

        var enumerator = new SafeFileEnumerator(new EnumerationSettings { FollowDirectoryLinks = true, LinkTargetRoots = [root, approved] });
        var (items, _) = Run(enumerator, Root(root));
        Assert.Contains(items, i => i.Path.EndsWith("ok.jar", StringComparison.Ordinal));
        Assert.DoesNotContain(items, i => i.Path.EndsWith("secret.jar", StringComparison.Ordinal));
    }

    [Fact]
    public void PermissionFailuresAreReportedAndTheWalkContinues()
    {
        var root = _temp.CreateDirectory("game");
        _temp.WriteText("game/locked/a.jar", "x");
        _temp.WriteText("game/open/b.jar", "x");
        var locked = _temp.Combine("game", "locked");
        IEnumerable<FileSystemInfo> Lister(string path) =>
            string.Equals(path, locked, StringComparison.Ordinal)
                ? throw new UnauthorizedAccessException("Access to the path is denied.")
                : new DirectoryInfo(path).EnumerateFileSystemInfos();

        var (items, skipped) = Run(new SafeFileEnumerator(new EnumerationSettings(), Lister), Root(root));
        Assert.Contains(items, i => i.Path.EndsWith("b.jar", StringComparison.Ordinal));
        Assert.Contains(skipped, s => s.Reason == SkipReason.AccessDenied && s.Path == locked);
    }

    [Fact]
    public void MissingRootsAreReported()
    {
        var (items, skipped) = Run(new SafeFileEnumerator(new EnumerationSettings()), Root(_temp.Combine("missing")));
        Assert.Empty(items);
        Assert.Equal(SkipReason.NotFound, Assert.Single(skipped).Reason);
    }

    [Fact]
    public void CancellationStopsEnumeration()
    {
        var root = _temp.CreateDirectory("game");
        _temp.WriteText("game/a.jar", "x");
        using var cts = new CancellationTokenSource();
        cts.Cancel();
        Assert.Throws<OperationCanceledException>(() =>
            new SafeFileEnumerator(new EnumerationSettings()).Enumerate(Root(root), _ => { }, () => { }, cts.Token).ToList());
    }

    // ---------------- discovery ----------------

    private InstallationDiscoveryService Discovery() =>
        new(new DiscoveryEnvironment(_temp.Combine("Roaming"), _temp.Combine("Local"), _temp.Combine("Profile")));

    [Fact]
    public void DiscoversTheOfficialLauncherAndProfileGameDirectories()
    {
        var dotMinecraft = _temp.CreateDirectory("Roaming", ".minecraft");
        _temp.CreateDirectory("Roaming", ".minecraft", "versions", "fabric-loader-0.15.11-1.20.4");
        var custom = _temp.CreateDirectory("Games", "Survival");
        var profiles = $$"""
            { "profiles": {
                "a": { "name": "Survival", "gameDir": {{System.Text.Json.JsonSerializer.Serialize(custom)}}, "lastVersionId": "neoforge-21.1.1" },
                "b": { "name": "Broken", "gameDir": "relative/dir" },
                "c": { "name": "Gone", "gameDir": {{System.Text.Json.JsonSerializer.Serialize(_temp.Combine("Nope"))}} }
            } }
            """;
        File.WriteAllText(Path.Combine(dotMinecraft, "launcher_profiles.json"), profiles);

        var result = Discovery().Discover();

        var main = Assert.Single(result.Installations, i => i.RootPath == dotMinecraft);
        Assert.Contains(ModLoader.Fabric, main.ModLoaders);
        var survival = Assert.Single(result.Installations, i => i.RootPath == custom);
        Assert.Equal([ModLoader.NeoForge], survival.ModLoaders);
        Assert.Contains(result.Notes, n => n.Contains("not an absolute path"));
        Assert.Contains(result.Notes, n => n.Contains("does not exist"));
        Assert.NotEmpty(result.LocationsChecked);
    }

    [Fact]
    public void UnparseableLauncherMetadataIsReported()
    {
        var dotMinecraft = _temp.CreateDirectory("Roaming", ".minecraft");
        File.WriteAllText(Path.Combine(dotMinecraft, "launcher_profiles.json"), "{ broken");
        var result = Discovery().Discover();
        Assert.Contains(result.Notes, n => n.Contains("launcher_profiles.json could not be read"));
        Assert.Single(result.Installations);
    }

    [Fact]
    public void DiscoversPrismInstancesWithLoaders()
    {
        _temp.WriteText("Roaming/PrismLauncher/instances/PvP/instance.cfg", "name=PvP Pack\n");
        _temp.CreateDirectory("Roaming", "PrismLauncher", "instances", "PvP", ".minecraft", "mods");
        _temp.WriteText("Roaming/PrismLauncher/instances/PvP/mmc-pack.json",
            """{ "components": [ { "uid": "net.minecraft", "version": "1.20.4" }, { "uid": "net.fabricmc.fabric-loader" } ] }""");

        var installation = Assert.Single(Discovery().Discover().Installations);
        Assert.Equal("Prism Launcher: PvP Pack", installation.Name);
        Assert.Equal(LauncherKind.PrismLauncher, installation.Launcher);
        Assert.Equal([ModLoader.Fabric], installation.ModLoaders);
        Assert.Equal("1.20.4", installation.MinecraftVersion);
        Assert.EndsWith(".minecraft", installation.RootPath, StringComparison.Ordinal);
    }

    [Fact]
    public void PrismCustomInstanceFolderIsHonoured()
    {
        var instances = _temp.CreateDirectory("Elsewhere", "Instances");
        _temp.WriteText("Roaming/PrismLauncher/prismlauncher.cfg", $"InstanceDir={instances}\n");
        _temp.WriteText("Elsewhere/Instances/One/instance.cfg", "name=One\n");
        _temp.CreateDirectory("Elsewhere", "Instances", "One", "minecraft");
        Assert.Single(Discovery().Discover().Installations, i => i.Name == "Prism Launcher: One");
    }

    [Fact]
    public void DiscoversModrinthCurseForgeAndClientFolders()
    {
        _temp.CreateDirectory("Roaming", "ModrinthApp", "profiles", "Fabulously Optimized");
        _temp.WriteText("Profile/curseforge/minecraft/Instances/RLCraft/minecraftinstance.json", """{ "name": "RLCraft", "baseModLoader": { "name": "forge-14.23.5.2860" } }""");
        _temp.CreateDirectory("Profile", ".lunarclient");

        var result = Discovery().Discover();
        Assert.Contains(result.Installations, i => i.Launcher == LauncherKind.ModrinthApp);
        Assert.Contains(result.Installations, i => i.Launcher == LauncherKind.CurseForge && i.ModLoaders.Contains(ModLoader.Forge));
        var lunar = Assert.Single(result.Installations, i => i.Launcher == LauncherKind.LunarClient);
        Assert.Empty(lunar.QuickScanSubdirectories);
        Assert.NotEmpty(lunar.Notes);
    }

    [Fact]
    public void CustomDirectoriesAreAddedAndValidated()
    {
        var custom = _temp.CreateDirectory("MyPack");
        var result = Discovery().Discover([custom, _temp.Combine("Missing"), "relative"]);
        Assert.Single(result.Installations, i => i.Launcher == LauncherKind.Custom);
        Assert.Contains(result.Notes, n => n.Contains("does not exist"));
        Assert.Contains(result.Notes, n => n.Contains("not an absolute path"));
    }

    [Fact]
    public void NothingIsFoundOnACleanSystem()
    {
        var result = Discovery().Discover();
        Assert.Empty(result.Installations);
    }

    [Fact]
    public void InstallationIdsAreStable()
    {
        Assert.Equal(InstallationDiscoveryService.CreateId(_temp.Combine("x")), InstallationDiscoveryService.CreateId(_temp.Combine("x")));
    }
}
