using CleanerPro.Core.Models;
using CleanerPro.Scanner.Discovery;
using CleanerPro.TestSupport;

namespace CleanerPro.Scanner.Tests;

/// <summary>Discovery of every supported launcher layout, MultiMC-format forks and unlisted game folders, using synthetic folders.</summary>
public sealed class LauncherDiscoveryTests : IDisposable
{
    private readonly TempDirectory _temp = new();

    public void Dispose() => _temp.Dispose();

    private InstallationDiscoveryService Discovery(params string[] drives) =>
        new(new DiscoveryEnvironment(_temp.Combine("Roaming"), _temp.Combine("Local"), _temp.Combine("Profile")) { FixedDrives = drives });

    private void GameFolder(params string[] parts)
    {
        _temp.CreateDirectory([.. parts, "mods"]);
        _temp.WriteText(Path.Combine([.. parts, "options.txt"]), "fov:70");
    }

    [Fact]
    public void DiscoversAtLauncherAndGdLauncherInstances()
    {
        _temp.CreateDirectory("Roaming", "ATLauncher", "instances", "SkyFactory", "mods");
        _temp.WriteText("Roaming/ATLauncher/instances/SkyFactory/instance.json", "{}");
        _temp.CreateDirectory("Roaming", "gdlauncher_next", "instances", "Vanilla+");
        _temp.CreateDirectory("Roaming", "gdlauncher_carbon", "data", "instances", "Pack", "instance");

        var result = Discovery().Discover();

        var atl = Assert.Single(result.Installations, i => i.Launcher == LauncherKind.ATLauncher);
        Assert.Contains(atl.LaunchSettingsFiles, f => f.EndsWith("instance.json", StringComparison.Ordinal));
        Assert.Equal(2, result.Installations.Count(i => i.Launcher == LauncherKind.GDLauncher));
        Assert.Contains(result.Installations, i => i.RootPath.EndsWith(Path.Combine("Pack", "instance"), StringComparison.Ordinal));
    }

    [Fact]
    public void DiscoversFeatherBadlionAndPolyMc()
    {
        _temp.CreateDirectory("Roaming", ".feather");
        _temp.CreateDirectory("Roaming", "Badlion Client");
        _temp.WriteText("Roaming/PolyMC/instances/Old/instance.cfg", "name=Old\n");
        _temp.CreateDirectory("Roaming", "PolyMC", "instances", "Old", "minecraft");

        var result = Discovery().Discover();
        Assert.Contains(result.Installations, i => i.Launcher == LauncherKind.FeatherClient);
        Assert.Contains(result.Installations, i => i.Launcher == LauncherKind.BadlionClient);
        Assert.Contains(result.Installations, i => i.Name == "PolyMC: Old");
    }

    [Fact]
    public void RecognisesMultiMcFormatForksByLayout()
    {
        _temp.WriteText("Roaming/PollyMC/pollymc.cfg", "JvmArgs=-Xmx4G\n");
        _temp.WriteText("Roaming/PollyMC/instances/Pack/instance.cfg", "name=Pack\n");
        _temp.CreateDirectory("Roaming", "PollyMC", "instances", "Pack", ".minecraft");

        var installation = Assert.Single(Discovery().Discover().Installations);
        Assert.Equal(LauncherKind.MultiMcCompatible, installation.Launcher);
        Assert.Equal("PollyMC (MultiMC-format launcher): Pack", installation.Name);
        Assert.Contains(installation.LaunchSettingsFiles, f => f.EndsWith("pollymc.cfg", StringComparison.Ordinal));
        Assert.Contains(installation.LaunchSettingsFiles, f => f.EndsWith("instance.cfg", StringComparison.Ordinal));
    }

    [Fact]
    public void DiscoversTechnicModpacksByLayout()
    {
        GameFolder("Roaming", ".technic", "modpacks", "tekkit");
        _temp.CreateDirectory("Roaming", ".technic", "cache");

        var installation = Assert.Single(Discovery().Discover().Installations);
        Assert.Equal(LauncherKind.TechnicLauncher, installation.Launcher);
        Assert.Equal("Technic Launcher: tekkit", installation.Name);
    }

    [Fact]
    public void FindsRedirectedMinecraftFoldersOfStoreApps()
    {
        GameFolder("Local", "Packages", "Some.Launcher_abc", "LocalCache", "Roaming", ".minecraft");
        _temp.CreateDirectory("Local", "Packages", "Other.App_xyz", "LocalCache");

        var installation = Assert.Single(Discovery().Discover().Installations);
        Assert.StartsWith("Microsoft Store app data: Some.Launcher_abc", installation.Name, StringComparison.Ordinal);
    }

    [Fact]
    public void OfficialProfilesShareTheLauncherProfilesFileForLaunchSettings()
    {
        var dotMinecraft = _temp.CreateDirectory("Roaming", ".minecraft");
        var custom = _temp.CreateDirectory("Games", "PvP");
        File.WriteAllText(Path.Combine(dotMinecraft, "launcher_profiles.json"),
            $$"""{ "profiles": { "a": { "name": "PvP", "gameDir": {{System.Text.Json.JsonSerializer.Serialize(custom)}} } } }""");

        var result = Discovery().Discover();
        Assert.All(result.Installations, i => Assert.Contains(i.LaunchSettingsFiles, f => f.EndsWith("launcher_profiles.json", StringComparison.Ordinal)));
    }

    [Fact]
    public void FolderSearchFindsPortableAndCopiedGameFolders()
    {
        GameFolder("Profile", "Desktop", "PCL", ".minecraft");
        GameFolder("Drive", "Games", "MyPack");
        _temp.WriteText("Drive/Games/NotAGame/options.txt", "this folder has no game folders next to it");
        _temp.WriteText("Drive/Portable/UltimMC/instances/Survival/instance.cfg", "name=Survival\n");
        _temp.CreateDirectory("Drive", "Portable", "UltimMC", "instances", "Survival", ".minecraft");
        var known = _temp.CreateDirectory("Roaming", ".minecraft", "mods");

        var service = Discovery(_temp.Combine("Drive"));
        var result = service.SearchForUnlisted([Path.GetDirectoryName(known)!]);

        Assert.Contains(result.Installations, i => i.Launcher == LauncherKind.Unlisted && i.RootPath.EndsWith(Path.Combine("PCL", ".minecraft"), StringComparison.Ordinal));
        Assert.Contains(result.Installations, i => i.Launcher == LauncherKind.Unlisted && i.RootPath.EndsWith("MyPack", StringComparison.Ordinal));
        Assert.Contains(result.Installations, i => i.Launcher == LauncherKind.MultiMcCompatible && i.Name == "UltimMC (MultiMC-format launcher): Survival");
        Assert.DoesNotContain(result.Installations, i => i.RootPath.EndsWith("NotAGame", StringComparison.Ordinal));
        Assert.DoesNotContain(result.Installations, i => i.RootPath.StartsWith(_temp.Combine("Roaming", ".minecraft"), StringComparison.Ordinal));
        Assert.All(result.Installations.Where(i => i.Launcher == LauncherKind.Unlisted), i => Assert.Contains(i.Notes, n => n.Contains("No known launcher")));
        Assert.Contains(result.Notes, n => n.Contains("folder search checked"));
    }

    [Fact]
    public void FolderSearchHonoursItsLimits()
    {
        for (var i = 0; i < 30; i++)
        {
            _temp.CreateDirectory("Drive", $"folder{i:00}", "a", "b");
        }

        var result = Discovery(_temp.Combine("Drive")).SearchForUnlisted([], new UnlistedSearchOptions { MaxDirectories = 10 });
        Assert.Contains(result.Notes, n => n.Contains("stopped after checking 10 folders"));
    }

    [Fact]
    public void FolderSearchSkipsSystemAndExcludedFolders()
    {
        GameFolder("Drive", "Windows", "Hidden", ".minecraft");
        GameFolder("Drive", "Excluded", ".minecraft");
        var service = new InstallationDiscoveryService(new DiscoveryEnvironment(null, null, null)
        {
            FixedDrives = [_temp.Combine("Drive")],
            SearchExclusions = [_temp.Combine("Drive", "Excluded")],
        });

        Assert.Empty(service.SearchForUnlisted([]).Installations);
    }
}
