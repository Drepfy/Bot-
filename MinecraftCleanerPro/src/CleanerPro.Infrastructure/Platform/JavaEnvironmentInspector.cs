using System.Runtime.Versioning;
using Microsoft.Win32;

namespace CleanerPro.Infrastructure.Platform;

/// <summary>
/// Read-only inspection of the environment variables that every Java program reads at start-up
/// (JAVA_TOOL_OPTIONS, _JAVA_OPTIONS and JDK_JAVA_OPTIONS). A "-javaagent" placed there is loaded into
/// Minecraft regardless of the launcher, which makes it a way to inject cheats that never touches the mods folder.
/// Nothing is ever written.
/// </summary>
public static class JavaEnvironmentInspector
{
    public static readonly IReadOnlyList<string> VariableNames = ["JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"];

    private const string MachineEnvironmentKey = @"SYSTEM\CurrentControlSet\Control\Session Manager\Environment";

    /// <summary>Returns one entry per variable that is set, from the user and machine registry and the current process.</summary>
    public static IReadOnlyList<StartupEntry> Read(out string? error)
    {
        error = null;
        var entries = new List<StartupEntry>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        void Add(string source, string name, string? value)
        {
            if (!string.IsNullOrWhiteSpace(value) && seen.Add($"{name}={value}"))
            {
                entries.Add(new StartupEntry(source, name, value));
            }
        }

        if (OperatingSystem.IsWindows())
        {
            error = ReadRegistry(Registry.CurrentUser, "Environment", "User environment variable", Add);
            var machineError = ReadRegistry(Registry.LocalMachine, MachineEnvironmentKey, "System environment variable", Add);
            error ??= machineError;
        }

        foreach (var name in VariableNames)
        {
            Add("Environment of this program", name, Environment.GetEnvironmentVariable(name));
        }

        return entries;
    }

    [SupportedOSPlatform("windows")]
    private static string? ReadRegistry(RegistryKey hive, string path, string source, Action<string, string, string?> add)
    {
        try
        {
            using var key = hive.OpenSubKey(path, writable: false);
            if (key is null)
            {
                return null;
            }

            foreach (var name in VariableNames)
            {
                add(source, name, key.GetValue(name, null, RegistryValueOptions.DoNotExpandEnvironmentNames)?.ToString());
            }

            return null;
        }
        catch (Exception ex) when (ex is System.Security.SecurityException or UnauthorizedAccessException or IOException)
        {
            return $"Could not read Java environment variables from {source.ToLowerInvariant()}s: {ex.Message}";
        }
    }
}
