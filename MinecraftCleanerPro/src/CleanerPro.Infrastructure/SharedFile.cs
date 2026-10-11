using System.Text;

namespace CleanerPro.Infrastructure;

/// <summary>
/// Reads files that belong to other programs (launcher settings, mods) without getting in their way: the file is
/// opened read-only and shared for reading, writing and deletion, so a launcher that saves its settings, or a game
/// that is updating a file, is never blocked by this application. File.ReadAllText would block other writers.
/// </summary>
public static class SharedFile
{
    public static FileStream OpenRead(string path, int bufferSize = 4096, FileOptions options = FileOptions.None) =>
        new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, bufferSize, options);

    public static string ReadAllText(string path)
    {
        using var stream = OpenRead(path);
        using var reader = new StreamReader(stream, Encoding.UTF8, detectEncodingFromByteOrderMarks: true);
        return reader.ReadToEnd();
    }

    public static string[] ReadAllLines(string path) =>
        ReadAllText(path).Split('\n').Select(l => l.TrimEnd('\r')).ToArray();
}
