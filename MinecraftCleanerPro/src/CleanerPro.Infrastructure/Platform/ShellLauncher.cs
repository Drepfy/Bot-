using System.ComponentModel;
using System.Diagnostics;

namespace CleanerPro.Infrastructure.Platform;

public interface IShellLauncher
{
    /// <summary>Opens a file with the user's default handler. Falls back to Notepad for text files without an association.</summary>
    ShellLaunchResult OpenFile(string path);

    /// <summary>Opens a folder in File Explorer.</summary>
    ShellLaunchResult OpenFolder(string path);

    /// <summary>Opens File Explorer with the given file selected.</summary>
    ShellLaunchResult RevealFile(string path);
}

public sealed record ShellLaunchResult(bool Succeeded, string Message);

/// <summary>Launches the Windows shell. Only ever opens paths that already exist; never runs scanned files.</summary>
public sealed class ShellLauncher : IShellLauncher
{
    private static readonly string[] TextExtensions = [".json", ".txt", ".log", ".jsonl", ".md"];

    public ShellLaunchResult OpenFile(string path)
    {
        if (!File.Exists(path))
        {
            return new ShellLaunchResult(false, $"The file '{path}' does not exist.");
        }

        // Safety: this launcher is only used for the application's own text files (configuration, reports, logs).
        var extension = Path.GetExtension(path);
        var isText = TextExtensions.Contains(extension, StringComparer.OrdinalIgnoreCase);
        if (!isText && !extension.Equals(".html", StringComparison.OrdinalIgnoreCase))
        {
            return new ShellLaunchResult(false, "Only text and report files can be opened from Minecraft Cleaner Pro.");
        }

        try
        {
            using var process = Process.Start(new ProcessStartInfo(path) { UseShellExecute = true, Verb = "open" });
            return new ShellLaunchResult(true, $"Opened '{path}' with the default application.");
        }
        catch (Win32Exception ex) when (isText && OperatingSystem.IsWindows())
        {
            // No file association for .json on this computer: fall back to Notepad, which ships with Windows.
            try
            {
                using var process = Process.Start(new ProcessStartInfo("notepad.exe") { UseShellExecute = false, ArgumentList = { path } });
                return new ShellLaunchResult(true, $"No default editor is associated with '{extension}' files, so the file was opened in Notepad.");
            }
            catch (Exception inner) when (inner is Win32Exception or InvalidOperationException)
            {
                return new ShellLaunchResult(false, $"Could not open the file: {ex.Message}; Notepad fallback failed: {inner.Message}");
            }
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidOperationException or PlatformNotSupportedException)
        {
            return new ShellLaunchResult(false, $"Could not open the file: {ex.Message}");
        }
    }

    public ShellLaunchResult OpenFolder(string path)
    {
        if (!Directory.Exists(path))
        {
            return new ShellLaunchResult(false, $"The folder '{path}' does not exist.");
        }

        try
        {
            using var process = Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
            return new ShellLaunchResult(true, $"Opened '{path}'.");
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidOperationException or PlatformNotSupportedException)
        {
            return new ShellLaunchResult(false, $"Could not open the folder: {ex.Message}");
        }
    }

    public ShellLaunchResult RevealFile(string path)
    {
        if (!OperatingSystem.IsWindows())
        {
            return OpenFolder(Path.GetDirectoryName(path) ?? path);
        }

        if (!File.Exists(path) && !Directory.Exists(path))
        {
            var parent = Path.GetDirectoryName(path);
            return parent is not null ? OpenFolder(parent) : new ShellLaunchResult(false, "The item no longer exists.");
        }

        try
        {
            using var process = Process.Start(new ProcessStartInfo("explorer.exe") { UseShellExecute = false, ArgumentList = { "/select,", path } });
            return new ShellLaunchResult(true, $"Showing '{path}' in File Explorer.");
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidOperationException)
        {
            return new ShellLaunchResult(false, $"Could not open File Explorer: {ex.Message}");
        }
    }
}
