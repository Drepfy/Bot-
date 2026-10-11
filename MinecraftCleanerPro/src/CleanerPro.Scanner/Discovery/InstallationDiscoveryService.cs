using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CleanerPro.Core;
using CleanerPro.Core.Models;

namespace CleanerPro.Scanner.Discovery;

/// <summary>Base folders used for discovery. Replaceable so discovery can be tested against temporary folders.</summary>
public sealed record DiscoveryEnvironment(string? RoamingAppData, string? LocalAppData, string? UserProfile)
{
    /// <summary>Roots of local fixed drives, searched (folder names only, a few levels deep) for unlisted game folders.</summary>
    public IReadOnlyList<string> FixedDrives { get; init; } = [];

    /// <summary>Folders never searched for unlisted installations (this application's own data, for example).</summary>
    public IReadOnlyList<string> SearchExclusions { get; init; } = [];

    public static DiscoveryEnvironment Current() => new(
        NullIfEmpty(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData, Environment.SpecialFolderOption.DoNotVerify)),
        NullIfEmpty(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData, Environment.SpecialFolderOption.DoNotVerify)),
        NullIfEmpty(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile, Environment.SpecialFolderOption.DoNotVerify)))
    {
        FixedDrives = LocalFixedDrives(),
    };

    private static List<string> LocalFixedDrives()
    {
        try
        {
            return DriveInfo.GetDrives().Where(d => d.DriveType == DriveType.Fixed && d.IsReady).Select(d => d.RootDirectory.FullName).ToList();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return [];
        }
    }

    private static string? NullIfEmpty(string value) => string.IsNullOrEmpty(value) ? null : value;
}

/// <summary>Limits for the search for game folders that no known launcher lists.</summary>
public sealed record UnlistedSearchOptions
{
    public int AppDataDepth { get; init; } = 4;

    public int UserProfileDepth { get; init; } = 4;

    public int DriveDepth { get; init; } = 3;

    public int MaxDirectories { get; init; } = 60_000;

    public TimeSpan TimeLimit { get; init; } = TimeSpan.FromSeconds(20);
}

/// <summary>
/// Finds Minecraft installations from launcher metadata and well-known default folders. Every location
/// that is checked is listed, and unreadable metadata is reported instead of guessed.
/// </summary>
public sealed class InstallationDiscoveryService
{
    private static readonly string[] GameQuickSubdirectories = ["mods", "config", "versions", "resourcepacks", "shaderpacks", "coremods"];
    private static readonly string[] GameDefaultExcluded = ["saves", "screenshots", "assets", "logs", "crash-reports"];
    private static readonly string[] RuntimeExcluded = ["jre", "runtime", "jdk", "cache", "Cache", "logs", "GPUCache", "Code Cache"];

    private readonly DiscoveryEnvironment _environment;
    private readonly TimeProvider _time;

    public InstallationDiscoveryService(DiscoveryEnvironment? environment = null, TimeProvider? time = null)
    {
        _environment = environment ?? DiscoveryEnvironment.Current();
        _time = time ?? TimeProvider.System;
    }

    public DiscoveryResult Discover(IEnumerable<string>? customDirectories = null)
    {
        var installations = new Dictionary<string, MinecraftInstallation>(PathKey.Comparer);
        var notes = new List<string>();
        var checkedLocations = new List<string>();

        void Add(MinecraftInstallation installation)
        {
            var key = PathKey.ToKey(installation.RootPath);
            if (!installations.ContainsKey(key))
            {
                installations[key] = installation;
            }
        }

        string? Check(string? baseFolder, params string[] parts)
        {
            if (baseFolder is null)
            {
                return null;
            }

            var path = Path.Combine([baseFolder, .. parts]);
            checkedLocations.Add(path);
            return Directory.Exists(path) ? path : null;
        }

        // Official launcher (and launchers that share the default .minecraft folder, such as TLauncher, SKLauncher and HMCL).
        if (Check(_environment.RoamingAppData, ".minecraft") is { } dotMinecraft)
        {
            DiscoverOfficial(dotMinecraft, Add, notes);
        }

        // Microsoft Store (MSIX) apps can have their AppData redirected into their package folder. Any package with a
        // redirected .minecraft folder is listed; package names are not guessed.
        if (Check(_environment.LocalAppData, "Packages") is { } packages)
        {
            foreach (var package in QuietDirectories(packages))
            {
                var redirected = Path.Combine(package, "LocalCache", "Roaming", ".minecraft");
                if (Directory.Exists(redirected) && LooksLikeGameFolder(redirected))
                {
                    checkedLocations.Add(redirected);
                    Add(CreateGameInstallation($"Microsoft Store app data: {Path.GetFileName(package)}", LauncherKind.OfficialLauncher, redirected,
                        "Redirected .minecraft folder inside a Microsoft Store app package", []));
                }
            }
        }

        // Prism Launcher and its MultiMC-format relatives.
        foreach (var (folder, kind, label) in new[] { ("PrismLauncher", LauncherKind.PrismLauncher, "Prism Launcher"), ("PolyMC", LauncherKind.MultiMC, "PolyMC"), ("MultiMC", LauncherKind.MultiMC, "MultiMC") })
        {
            if (Check(_environment.RoamingAppData, folder) is { } prism)
            {
                DiscoverMultiMcFormat(prism, kind, label, Add, notes);
            }
        }

        // Other launchers that use the MultiMC instance format (forks such as PollyMC, Fjord or UltimMC) are recognised
        // by their layout: a folder with "instances/<name>/instance.cfg". No launcher names are guessed.
        var multiMcFolders = new HashSet<string>(["PrismLauncher", "PolyMC", "MultiMC"], StringComparer.OrdinalIgnoreCase);
        foreach (var baseFolder in new[] { _environment.RoamingAppData, _environment.LocalAppData, _environment.UserProfile })
        {
            if (baseFolder is null || !Directory.Exists(baseFolder))
            {
                continue;
            }

            foreach (var candidate in QuietDirectories(baseFolder).Where(d => !multiMcFolders.Contains(Path.GetFileName(d))))
            {
                if (HasMultiMcInstances(candidate))
                {
                    checkedLocations.Add(candidate);
                    DiscoverMultiMcFormat(candidate, LauncherKind.MultiMcCompatible, $"{Path.GetFileName(candidate)} (MultiMC-format launcher)", Add, notes);
                }
            }
        }

        // Modrinth App (current and legacy data folders).
        foreach (var folder in new[] { "ModrinthApp", "com.modrinth.theseus" })
        {
            if (Check(_environment.RoamingAppData, folder, "profiles") is { } profiles)
            {
                DiscoverModrinth(profiles, Add, notes);
            }
        }

        // CurseForge app.
        if (Check(_environment.UserProfile, "curseforge", "minecraft", "Instances") is { } curseForge)
        {
            DiscoverCurseForge(curseForge, Add, notes);
        }

        // ATLauncher and GDLauncher keep one game directory per instance folder.
        foreach (var (baseFolder, parts, kind, label) in new (string?, string[], LauncherKind, string)[]
                 {
                     (_environment.RoamingAppData, ["ATLauncher", "instances"], LauncherKind.ATLauncher, "ATLauncher"),
                     (_environment.RoamingAppData, ["gdlauncher_next", "instances"], LauncherKind.GDLauncher, "GDLauncher"),
                     (_environment.RoamingAppData, ["gdlauncher_carbon", "data", "instances"], LauncherKind.GDLauncher, "GDLauncher"),
                 })
        {
            if (Check(baseFolder, parts) is { } instances)
            {
                foreach (var instance in SafeDirectories(instances, notes))
                {
                    var gameDir = Directory.Exists(Path.Combine(instance, "instance")) ? Path.Combine(instance, "instance") : instance;
                    Add(CreateGameInstallation($"{label}: {Path.GetFileName(instance)}", kind, gameDir, $"{label} instance folder", []));
                }
            }
        }

        // Technic Launcher keeps its data in %APPDATA%\.technic (OperatingSystem.getTechnicDirectory in its source).
        // Modpack game folders inside it are recognised by their layout rather than by an assumed sub-path.
        if (Check(_environment.RoamingAppData, ".technic") is { } technic)
        {
            foreach (var gameDir in GameFoldersUnder(technic, maxDepth: 3))
            {
                Add(CreateGameInstallation($"Technic Launcher: {Path.GetFileName(gameDir)}", LauncherKind.TechnicLauncher, gameDir, "Game folder inside the Technic Launcher data folder", []));
            }
        }

        // Clients with their own (closed-source) data folders. Their internal layout is not publicly documented,
        // so the whole folder is scanned except runtime/cache folders.
        foreach (var (baseFolder, folder, kind, label) in new (string?, string, LauncherKind, string)[]
                 {
                     (_environment.UserProfile, ".lunarclient", LauncherKind.LunarClient, "Lunar Client"),
                     (_environment.RoamingAppData, ".feather", LauncherKind.FeatherClient, "Feather Client"),
                     (_environment.RoamingAppData, "Badlion Client", LauncherKind.BadlionClient, "Badlion Client"),
                 })
        {
            if (Check(baseFolder, folder) is { } clientFolder)
            {
                Add(new MinecraftInstallation
                {
                    Id = CreateId(clientFolder),
                    Name = $"{label} data",
                    Launcher = kind,
                    RootPath = clientFolder,
                    DiscoveredBy = $"Default {label} data folder",
                    ModLoaders = [],
                    DefaultExcludedSubdirectories = RuntimeExcluded,
                    Notes = [$"{label} is closed source and its folder layout is not publicly documented. The folder is scanned as a whole (Quick Scan included), excluding runtime and cache folders."],
                    LastInspectedUtc = _time.GetUtcNow(),
                });
            }
        }

        foreach (var custom in customDirectories ?? [])
        {
            if (string.IsNullOrWhiteSpace(custom) || !Path.IsPathFullyQualified(custom))
            {
                notes.Add($"Custom directory '{custom}' is not an absolute path and was ignored.");
                continue;
            }

            checkedLocations.Add(custom);
            if (!Directory.Exists(custom))
            {
                notes.Add($"Custom directory '{custom}' does not exist.");
                continue;
            }

            Add(CreateGameInstallation($"Custom: {Path.GetFileName(PathKey.TrimTrailingSeparators(custom))}", LauncherKind.Custom, PathKey.NormalizeFullPath(custom), "Added by you in the configuration", []));
        }

        return new DiscoveryResult
        {
            Installations = installations.Values.OrderBy(i => i.Launcher).ThenBy(i => i.Name, StringComparer.OrdinalIgnoreCase).ToList(),
            Notes = notes,
            LocationsChecked = checkedLocations,
        };
    }

    private void DiscoverOfficial(string dotMinecraft, Action<MinecraftInstallation> add, List<string> notes)
    {
        add(CreateGameInstallation("Minecraft (default game directory)", LauncherKind.OfficialLauncher, dotMinecraft, "Default .minecraft folder", []));
        var profileFiles = new[] { "launcher_profiles.json", "launcher_profiles_microsoft_store.json" }.Select(f => Path.Combine(dotMinecraft, f)).Where(File.Exists).ToList();

        foreach (var profileFile in new[] { "launcher_profiles.json", "launcher_profiles_microsoft_store.json" })
        {
            var path = Path.Combine(dotMinecraft, profileFile);
            if (!File.Exists(path))
            {
                continue;
            }

            try
            {
                using var document = JsonDocument.Parse(File.ReadAllText(path), new JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip });
                if (!document.RootElement.TryGetProperty("profiles", out var profiles) || profiles.ValueKind != JsonValueKind.Object)
                {
                    notes.Add($"{profileFile} has no 'profiles' section; only the default game directory is used.");
                    continue;
                }

                foreach (var profile in profiles.EnumerateObject())
                {
                    var value = profile.Value;
                    if (value.ValueKind != JsonValueKind.Object || !value.TryGetProperty("gameDir", out var gameDirElement) ||
                        gameDirElement.ValueKind != JsonValueKind.String)
                    {
                        continue;
                    }

                    var gameDir = gameDirElement.GetString();
                    if (string.IsNullOrWhiteSpace(gameDir) || !Path.IsPathFullyQualified(gameDir))
                    {
                        notes.Add($"Launcher profile '{profile.Name}' has a game directory that is not an absolute path and was skipped.");
                        continue;
                    }

                    if (!Directory.Exists(gameDir))
                    {
                        notes.Add($"Launcher profile '{profile.Name}' points to '{gameDir}', which does not exist.");
                        continue;
                    }

                    var name = value.TryGetProperty("name", out var n) && n.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(n.GetString())
                        ? n.GetString()!
                        : profile.Name;
                    var versionId = value.TryGetProperty("lastVersionId", out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;
                    add(CreateGameInstallation($"Launcher profile: {name}", LauncherKind.OfficialLauncher, PathKey.NormalizeFullPath(gameDir),
                        $"gameDir in {profileFile}", LoadersFromVersionId(versionId), profileFiles));
                }
            }
            catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
            {
                notes.Add($"{profileFile} could not be read ({ex.Message}). Profiles with custom game directories may be missing; add them as custom directories if needed.");
            }
        }
    }

    private void DiscoverMultiMcFormat(string launcherFolder, LauncherKind kind, string label, Action<MinecraftInstallation> add, List<string> notes)
    {
        var instancesDir = Path.Combine(launcherFolder, "instances");

        // The launcher-wide settings file ("<launcher>.cfg") holds the global JvmArgs that every instance inherits.
        var globalSettings = QuietFiles(launcherFolder, "*.cfg").ToList();
        foreach (var configPath in globalSettings)
        {

            try
            {
                var value = ReadIniValue(File.ReadAllLines(configPath), "InstanceDir");
                if (!string.IsNullOrWhiteSpace(value))
                {
                    instancesDir = Path.IsPathFullyQualified(value) ? value : Path.Combine(launcherFolder, value);
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                notes.Add($"{label}: {Path.GetFileName(configPath)} could not be read ({ex.Message}); using the default instances folder.");
            }
        }

        if (!Directory.Exists(instancesDir))
        {
            return;
        }

        foreach (var instance in SafeDirectories(instancesDir, notes))
        {
            var instanceCfg = Path.Combine(instance, "instance.cfg");
            if (!File.Exists(instanceCfg))
            {
                continue;
            }

            var gameDir = new[] { ".minecraft", "minecraft" }.Select(d => Path.Combine(instance, d)).FirstOrDefault(Directory.Exists);
            if (gameDir is null)
            {
                notes.Add($"{label} instance '{Path.GetFileName(instance)}' has no game directory yet.");
                continue;
            }

            string name = Path.GetFileName(instance);
            try
            {
                name = ReadIniValue(File.ReadAllLines(instanceCfg), "name") ?? name;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                notes.Add($"{label}: instance.cfg for '{name}' could not be read ({ex.Message}).");
            }

            var loaders = new List<ModLoader>();
            string? minecraftVersion = null;
            var packFile = Path.Combine(instance, "mmc-pack.json");
            if (File.Exists(packFile))
            {
                try
                {
                    using var document = JsonDocument.Parse(File.ReadAllText(packFile));
                    if (document.RootElement.TryGetProperty("components", out var components) && components.ValueKind == JsonValueKind.Array)
                    {
                        foreach (var component in components.EnumerateArray())
                        {
                            var uid = component.TryGetProperty("uid", out var u) ? u.GetString() : null;
                            switch (uid)
                            {
                                case "net.fabricmc.fabric-loader": loaders.Add(ModLoader.Fabric); break;
                                case "org.quiltmc.quilt-loader": loaders.Add(ModLoader.Quilt); break;
                                case "net.minecraftforge": loaders.Add(ModLoader.Forge); break;
                                case "net.neoforged": loaders.Add(ModLoader.NeoForge); break;
                                case "com.mumfrey.liteloader": loaders.Add(ModLoader.LiteLoader); break;
                                case "net.minecraft":
                                    minecraftVersion = component.TryGetProperty("version", out var ver) ? ver.GetString() : null;
                                    break;
                            }
                        }
                    }
                }
                catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
                {
                    notes.Add($"{label}: mmc-pack.json for '{name}' could not be parsed ({ex.Message}); the mod loader is shown as unknown.");
                }
            }

            add(CreateGameInstallation($"{label}: {name}", kind, gameDir, $"{label} instance.cfg", loaders, globalSettings) with { MinecraftVersion = minecraftVersion });
        }
    }

    private void DiscoverModrinth(string profilesDir, Action<MinecraftInstallation> add, List<string> notes)
    {
        foreach (var profile in SafeDirectories(profilesDir, notes))
        {
            var loaders = new List<ModLoader>();
            var profileJson = Path.Combine(profile, "profile.json");
            if (File.Exists(profileJson))
            {
                try
                {
                    using var document = JsonDocument.Parse(File.ReadAllText(profileJson));
                    if (document.RootElement.TryGetProperty("metadata", out var metadata) &&
                        metadata.TryGetProperty("loader", out var loader) && loader.ValueKind == JsonValueKind.String)
                    {
                        loaders.AddRange(LoadersFromName(loader.GetString()));
                    }
                }
                catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
                {
                    notes.Add($"Modrinth App: profile.json for '{Path.GetFileName(profile)}' could not be parsed ({ex.Message}).");
                }
            }

            add(CreateGameInstallation($"Modrinth App: {Path.GetFileName(profile)}", LauncherKind.ModrinthApp, profile, "Modrinth App profiles folder", loaders));
        }
    }

    private void DiscoverCurseForge(string instancesDir, Action<MinecraftInstallation> add, List<string> notes)
    {
        foreach (var instance in SafeDirectories(instancesDir, notes))
        {
            var loaders = new List<ModLoader>();
            var name = Path.GetFileName(instance);
            var manifest = Path.Combine(instance, "minecraftinstance.json");
            if (File.Exists(manifest))
            {
                try
                {
                    using var document = JsonDocument.Parse(File.ReadAllText(manifest));
                    var root = document.RootElement;
                    if (root.TryGetProperty("name", out var n) && n.ValueKind == JsonValueKind.String)
                    {
                        name = n.GetString() ?? name;
                    }

                    if (root.TryGetProperty("baseModLoader", out var baseLoader) && baseLoader.ValueKind == JsonValueKind.Object &&
                        baseLoader.TryGetProperty("name", out var loaderName) && loaderName.ValueKind == JsonValueKind.String)
                    {
                        loaders.AddRange(LoadersFromName(loaderName.GetString()));
                    }
                }
                catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
                {
                    notes.Add($"CurseForge: minecraftinstance.json for '{name}' could not be parsed ({ex.Message}).");
                }
            }

            add(CreateGameInstallation($"CurseForge: {name}", LauncherKind.CurseForge, instance, "CurseForge Instances folder", loaders));
        }
    }

    private MinecraftInstallation CreateGameInstallation(string name, LauncherKind launcher, string gameDir, string discoveredBy, IReadOnlyList<ModLoader> knownLoaders,
        IEnumerable<string>? extraSettingsFiles = null)
    {
        var loaders = knownLoaders.Count > 0 ? knownLoaders.Distinct().ToList() : DetectLoaders(gameDir);
        var notes = new List<string>();
        if (loaders.Count == 0)
        {
            notes.Add("The mod loader could not be identified from launcher metadata or installed versions.");
        }

        return new MinecraftInstallation
        {
            Id = CreateId(gameDir),
            Name = name,
            Launcher = launcher,
            RootPath = PathKey.NormalizeFullPath(gameDir),
            ModLoaders = loaders,
            DiscoveredBy = discoveredBy,
            QuickScanSubdirectories = GameQuickSubdirectories,
            DefaultExcludedSubdirectories = GameDefaultExcluded,
            Notes = notes,
            LastInspectedUtc = _time.GetUtcNow(),
            LaunchSettingsFiles = FindLaunchSettings(gameDir, extraSettingsFiles),
        };
    }

    /// <summary>Known launcher settings files in the game directory and the folder above it (instance folders keep them there).</summary>
    internal static List<string> FindLaunchSettings(string gameDir, IEnumerable<string>? extra = null)
    {
        var files = new List<string>(extra ?? []);
        var parent = Path.GetDirectoryName(PathKey.TrimTrailingSeparators(gameDir));
        foreach (var folder in new[] { gameDir, parent })
        {
            if (folder is null)
            {
                continue;
            }

            foreach (var name in LaunchSettingsInspector.KnownSettingsFileNames)
            {
                var candidate = Path.Combine(folder, name);
                if (File.Exists(candidate))
                {
                    files.Add(PathKey.NormalizeFullPath(candidate));
                }
            }
        }

        return files.Distinct(PathKey.Comparer).ToList();
    }

    /// <summary>
    /// Searches the user profile, AppData and the top levels of local drives for Minecraft game folders that no known
    /// launcher lists. Only folder and file names are checked; nothing is opened. Folders already known are skipped.
    /// </summary>
    public DiscoveryResult SearchForUnlisted(IReadOnlyCollection<string> knownRoots, UnlistedSearchOptions? options = null, CancellationToken cancellationToken = default)
    {
        options ??= new UnlistedSearchOptions();
        var found = new Dictionary<string, MinecraftInstallation>(PathKey.Comparer);
        var notes = new List<string>();
        var known = knownRoots.Select(PathKey.NormalizeFullPath).ToList();
        var excluded = _environment.SearchExclusions.Where(Path.IsPathFullyQualified).Select(PathKey.NormalizeFullPath).ToList();
        var clock = System.Diagnostics.Stopwatch.StartNew();
        var visited = 0;
        var stoppedEarly = false;

        var roots = new List<(string Path, int Depth)>();
        foreach (var folder in new[] { _environment.RoamingAppData, _environment.LocalAppData })
        {
            if (folder is not null)
            {
                roots.Add((folder, options.AppDataDepth));
            }
        }

        if (_environment.UserProfile is { } profile)
        {
            roots.Add((profile, options.UserProfileDepth));
        }

        roots.AddRange(_environment.FixedDrives.Select(d => (d, options.DriveDepth)));

        // Everything under the user profile except AppData is covered by the profile root; AppData has its own roots.
        var appData = _environment.UserProfile is null ? null : Path.Combine(_environment.UserProfile, "AppData");

        foreach (var (rootPath, depthLimit) in roots)
        {
            if (!Directory.Exists(rootPath))
            {
                continue;
            }

            var stack = new Stack<(string Path, int Depth)>();
            stack.Push((rootPath, 0));
            while (stack.Count > 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (visited >= options.MaxDirectories || clock.Elapsed > options.TimeLimit)
                {
                    stoppedEarly = true;
                    break;
                }

                var (directory, depth) = stack.Pop();
                visited++;

                if (known.Any(k => PathKey.IsSameOrWithin(directory, k)) || excluded.Any(e => PathKey.IsSameOrWithin(directory, e)) ||
                    found.Keys.Any(f => PathKey.IsSameOrWithin(directory, f)))
                {
                    continue;
                }

                if (depth > 0 && HasMultiMcInstances(directory))
                {
                    // A portable MultiMC-format launcher: its instances are read from instance.cfg, so the folder is not searched further.
                    DiscoverMultiMcFormat(directory, LauncherKind.MultiMcCompatible, $"{Path.GetFileName(directory)} (MultiMC-format launcher)", i => found.TryAdd(i.RootPath, i), notes);
                    continue;
                }

                if (depth > 0 && LooksLikeGameFolder(directory))
                {
                    var installation = CreateGameInstallation($"Unlisted game folder: {DisplayName(directory)}", LauncherKind.Unlisted, directory,
                        "Folder search: the folder contains Minecraft's options.txt and game folders", []);
                    found.TryAdd(installation.RootPath, installation with
                    {
                        Notes = [.. installation.Notes, "No known launcher lists this folder. It may belong to a portable or less common launcher, or be a copy. Untick it if you do not want it scanned."],
                    });
                    continue;
                }

                if (depth >= depthLimit)
                {
                    continue;
                }

                foreach (var child in QuietDirectories(directory).Reverse())
                {
                    var name = Path.GetFileName(child);
                    if (SearchSkippedNames.Contains(name) || (appData is not null && string.Equals(PathKey.TrimTrailingSeparators(child), appData, PathKey.Comparison)))
                    {
                        continue;
                    }

                    stack.Push((child, depth + 1));
                }
            }

            if (stoppedEarly)
            {
                break;
            }
        }

        var installations = found.Values.Where(i => i.Launcher is LauncherKind.Unlisted or LauncherKind.MultiMcCompatible)
            .DistinctBy(i => PathKey.ToKey(i.RootPath)).ToList();
        notes.Add(stoppedEarly
            ? $"The folder search stopped after checking {visited} folders ({clock.Elapsed.TotalSeconds:0} s limit). Add any missing game folder yourself with 'Add folder…'."
            : $"The folder search checked {visited} folders and found {installations.Count} game folder(s) that no known launcher lists.");
        return new DiscoveryResult { Installations = installations, Notes = notes, LocationsChecked = roots.Select(r => r.Path).ToList() };
    }

    /// <summary>Folder names never descended into by the folder search (system, development and cache folders).</summary>
    private static readonly HashSet<string> SearchSkippedNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "Windows", "Program Files", "Program Files (x86)", "ProgramData", "$Recycle.Bin", "System Volume Information", "Recovery", "PerfLogs",
        "Users", "node_modules", ".git", ".svn", ".gradle", ".m2", ".nuget", ".cache", "Temp", "Packages", "Microsoft", "Google", "Mozilla",
        "Cache", "Caches", "GPUCache", "Code Cache", "saves", "screenshots", "assets", "libraries", "logs",
    };

    /// <summary>
    /// A game folder is named ".minecraft" (and contains game files), or contains Minecraft's options.txt together with at
    /// least one of the folders the game creates (mods, versions, saves, resourcepacks).
    /// </summary>
    internal static bool LooksLikeGameFolder(string directory)
    {
        try
        {
            var gameFolders = new[] { "mods", "versions", "saves", "resourcepacks" };
            var hasOptions = File.Exists(Path.Combine(directory, "options.txt"));
            if (string.Equals(Path.GetFileName(PathKey.TrimTrailingSeparators(directory)), ".minecraft", StringComparison.OrdinalIgnoreCase))
            {
                return hasOptions || gameFolders.Any(f => Directory.Exists(Path.Combine(directory, f)));
            }

            return hasOptions && gameFolders.Any(f => Directory.Exists(Path.Combine(directory, f)));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    /// <summary>Game folders below a launcher's data folder, found by layout (not descending into a game folder once found).</summary>
    private static List<string> GameFoldersUnder(string root, int maxDepth)
    {
        var result = new List<string>();
        var stack = new Stack<(string Path, int Depth)>();
        stack.Push((root, 0));
        while (stack.Count > 0 && result.Count < 500)
        {
            var (directory, depth) = stack.Pop();
            if (depth > 0 && LooksLikeGameFolder(directory))
            {
                result.Add(PathKey.NormalizeFullPath(directory));
                continue;
            }

            if (depth < maxDepth)
            {
                foreach (var child in QuietDirectories(directory).Where(d => !SearchSkippedNames.Contains(Path.GetFileName(d))))
                {
                    stack.Push((child, depth + 1));
                }
            }
        }

        return result.Order(StringComparer.OrdinalIgnoreCase).ToList();
    }

    private static bool HasMultiMcInstances(string folder)
    {
        var instances = Path.Combine(folder, "instances");
        if (!Directory.Exists(instances))
        {
            return false;
        }

        return QuietDirectories(instances).Take(500).Any(i => File.Exists(Path.Combine(i, "instance.cfg")));
    }

    private static string DisplayName(string directory)
    {
        var trimmed = PathKey.TrimTrailingSeparators(directory);
        var name = Path.GetFileName(trimmed);
        var parent = Path.GetFileName(Path.GetDirectoryName(trimmed) ?? string.Empty);
        return string.IsNullOrEmpty(parent) ? name : $"{parent}\\{name}";
    }

    /// <summary>Lists sub-directories, skipping links and anything unreadable, without adding notes.</summary>
    private static IEnumerable<string> QuietDirectories(string path)
    {
        try
        {
            return new DirectoryInfo(path).EnumerateDirectories("*", new EnumerationOptions { IgnoreInaccessible = true, AttributesToSkip = FileAttributes.ReparsePoint })
                .Select(d => d.FullName).Order(StringComparer.OrdinalIgnoreCase).ToList();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            return [];
        }
    }

    private static IEnumerable<string> QuietFiles(string path, string pattern)
    {
        try
        {
            return Directory.EnumerateFiles(path, pattern, new EnumerationOptions { IgnoreInaccessible = true }).Order(StringComparer.OrdinalIgnoreCase).ToList();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return [];
        }
    }

    /// <summary>Infers installed loaders from version folder names and library folders.</summary>
    internal static List<ModLoader> DetectLoaders(string gameDir)
    {
        var loaders = new HashSet<ModLoader>();
        try
        {
            var versions = Path.Combine(gameDir, "versions");
            if (Directory.Exists(versions))
            {
                foreach (var version in Directory.EnumerateDirectories(versions))
                {
                    loaders.UnionWith(LoadersFromVersionId(Path.GetFileName(version)));
                }
            }

            if (Directory.Exists(Path.Combine(gameDir, "libraries", "net", "fabricmc", "fabric-loader")))
            {
                loaders.Add(ModLoader.Fabric);
            }

            if (Directory.Exists(Path.Combine(gameDir, "libraries", "org", "quiltmc", "quilt-loader")))
            {
                loaders.Add(ModLoader.Quilt);
            }

            if (Directory.Exists(Path.Combine(gameDir, "libraries", "net", "neoforged")))
            {
                loaders.Add(ModLoader.NeoForge);
            }

            if (Directory.Exists(Path.Combine(gameDir, "libraries", "net", "minecraftforge", "forge")))
            {
                loaders.Add(ModLoader.Forge);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // Loader detection is informational only.
        }

        return loaders.Order().ToList();
    }

    internal static List<ModLoader> LoadersFromVersionId(string? versionId)
    {
        if (string.IsNullOrWhiteSpace(versionId))
        {
            return [];
        }

        var id = versionId.ToLowerInvariant();
        if (id.Contains("neoforge"))
        {
            return [ModLoader.NeoForge];
        }

        if (id.Contains("fabric-loader"))
        {
            return [ModLoader.Fabric];
        }

        if (id.Contains("quilt-loader"))
        {
            return [ModLoader.Quilt];
        }

        if (id.Contains("forge"))
        {
            return [ModLoader.Forge];
        }

        return [];
    }

    private static List<ModLoader> LoadersFromName(string? name)
    {
        var lower = name?.ToLowerInvariant() ?? string.Empty;
        if (lower.StartsWith("neoforge", StringComparison.Ordinal))
        {
            return [ModLoader.NeoForge];
        }

        if (lower.StartsWith("forge", StringComparison.Ordinal))
        {
            return [ModLoader.Forge];
        }

        if (lower.StartsWith("fabric", StringComparison.Ordinal))
        {
            return [ModLoader.Fabric];
        }

        if (lower.StartsWith("quilt", StringComparison.Ordinal))
        {
            return [ModLoader.Quilt];
        }

        return lower is "vanilla" or "" ? [] : [ModLoader.Other];
    }

    private static string? ReadIniValue(IEnumerable<string> lines, string key)
    {
        foreach (var line in lines)
        {
            var index = line.IndexOf('=');
            if (index > 0 && string.Equals(line[..index].Trim(), key, StringComparison.OrdinalIgnoreCase))
            {
                return line[(index + 1)..].Trim();
            }
        }

        return null;
    }

    private static IEnumerable<string> SafeDirectories(string path, List<string> notes)
    {
        try
        {
            return Directory.EnumerateDirectories(path).Where(d =>
            {
                try
                {
                    var info = new DirectoryInfo(d);
                    return !info.Attributes.HasFlag(FileAttributes.ReparsePoint) && info.LinkTarget is null;
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    return false;
                }
            }).Order(StringComparer.OrdinalIgnoreCase).ToList();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            notes.Add($"'{path}' could not be listed: {ex.Message}");
            return [];
        }
    }

    public static string CreateId(string path)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(PathKey.ToKey(path)));
        return "inst-" + Convert.ToHexString(bytes, 0, 6).ToLowerInvariant();
    }
}
