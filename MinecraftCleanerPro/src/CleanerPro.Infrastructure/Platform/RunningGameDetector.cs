using System.Diagnostics;

namespace CleanerPro.Infrastructure.Platform;

/// <summary>
/// Read-only check for a running Minecraft game or launcher, so cleanup can warn the user to close it first instead of
/// fighting over files that are in use. Only process names are read; nothing is ever closed, injected or changed.
/// </summary>
public static class RunningGameDetector
{
    private static readonly (string ProcessName, string Display)[] Known =
    [
        ("javaw", "javaw (Minecraft Java Edition or another Java program)"),
        ("java", "java (Minecraft Java Edition or another Java program)"),
        ("Minecraft", "Minecraft Launcher"),
        ("MinecraftLauncher", "Minecraft Launcher"),
        ("PrismLauncher", "Prism Launcher"),
        ("MultiMC", "MultiMC"),
        ("PolyMC", "PolyMC"),
        ("ModrinthApp", "Modrinth App"),
        ("Modrinth App", "Modrinth App"),
        ("CurseForge", "CurseForge"),
        ("GDLauncher", "GDLauncher"),
        ("Lunar Client", "Lunar Client"),
        ("Feather Launcher", "Feather Client"),
        ("Badlion Client", "Badlion Client"),
    ];

    /// <summary>Names of running games or launchers, for a warning. Empty when none is found or processes cannot be listed.</summary>
    public static IReadOnlyList<string> FindRunning()
    {
        try
        {
            var names = Process.GetProcesses().Select(p =>
            {
                using (p)
                {
                    return p.ProcessName;
                }
            }).ToList();
            return Describe(names);
        }
        catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception or PlatformNotSupportedException)
        {
            return [];
        }
    }

    public static IReadOnlyList<string> Describe(IEnumerable<string> processNames)
    {
        var running = new HashSet<string>(processNames, StringComparer.OrdinalIgnoreCase);
        return Known.Where(k => running.Contains(k.ProcessName)).Select(k => k.Display).Distinct().ToList();
    }

    /// <summary>A sentence for confirmation dialogs, or an empty string when nothing relevant is running.</summary>
    public static string Warning(IReadOnlyList<string> running) => running.Count == 0
        ? string.Empty
        : $"\n\nStill running: {string.Join(", ", running)}. Close Minecraft and its launcher first; files that are in use cannot be moved and the game may recreate them.";
}
