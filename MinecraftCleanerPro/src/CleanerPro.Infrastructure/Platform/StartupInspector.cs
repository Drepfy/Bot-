using System.Runtime.Versioning;
using Microsoft.Win32;

namespace CleanerPro.Infrastructure.Platform;

/// <summary>A program configured to start automatically for the current user.</summary>
public sealed record StartupEntry(string Source, string Name, string Command);

/// <summary>
/// Read-only inspection of per-user startup locations (HKCU Run key and the Startup folder).
/// Nothing is ever written to the registry.
/// </summary>
public static class StartupInspector
{
    public const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";

    public static IReadOnlyList<StartupEntry> ReadCurrentUserRunKey(out string? error)
    {
        error = null;
        if (!OperatingSystem.IsWindows())
        {
            error = "Startup registry inspection is only available on Windows.";
            return [];
        }

        return ReadRunKeyWindows(out error);
    }

    [SupportedOSPlatform("windows")]
    private static List<StartupEntry> ReadRunKeyWindows(out string? error)
    {
        error = null;
        var entries = new List<StartupEntry>();
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: false);
            if (key is null)
            {
                return entries;
            }

            foreach (var name in key.GetValueNames())
            {
                var value = key.GetValue(name, null, RegistryValueOptions.DoNotExpandEnvironmentNames)?.ToString();
                if (value is not null)
                {
                    entries.Add(new StartupEntry($@"HKCU\{RunKeyPath}", name, value));
                }
            }
        }
        catch (Exception ex) when (ex is System.Security.SecurityException or UnauthorizedAccessException or IOException)
        {
            error = $"Could not read the startup registry key: {ex.Message}";
        }

        return entries;
    }
}
