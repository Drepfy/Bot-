namespace CleanerPro.Scanner.Inspection;

/// <summary>
/// Recognises ZIP/JAR archives by their first bytes, so renamed or "disabled" jars
/// (for example "client.jar.disabled" or a jar renamed to ".dat") are inspected like any other jar.
/// Only the first four bytes are read; files are opened read-only and shared with other programs.
/// </summary>
public static class ArchiveSniffer
{
    /// <summary>
    /// Formats that are not opened just to look for a ZIP signature: high-volume media and world data (for speed)
    /// and office documents, which are ZIP files themselves but have nothing to do with Minecraft (for privacy).
    /// A jar renamed to one of these extensions is therefore not detected by content (documented limitation).
    /// </summary>
    public static readonly IReadOnlySet<string> SkippedExtensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        ".png", ".jpg", ".jpeg", ".ogg", ".mp3", ".wav", ".mca", ".mcr",
        ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub",
    };

    /// <summary>True for a local-file header ("PK\x03\x04") or an empty archive ("PK\x05\x06").</summary>
    public static bool IsZipSignature(ReadOnlySpan<byte> header) =>
        header.Length >= 4 && header[0] == (byte)'P' && header[1] == (byte)'K' &&
        ((header[2] == 3 && header[3] == 4) || (header[2] == 5 && header[3] == 6));

    /// <summary>Reads the first bytes of the stream and restores its position.</summary>
    public static bool StartsWithZipSignature(Stream stream)
    {
        if (!stream.CanSeek || stream.Length < 4)
        {
            return false;
        }

        var position = stream.Position;
        try
        {
            stream.Seek(0, SeekOrigin.Begin);
            Span<byte> header = stackalloc byte[4];
            return stream.ReadAtLeast(header, 4, throwOnEndOfStream: false) == 4 && IsZipSignature(header);
        }
        finally
        {
            stream.Seek(position, SeekOrigin.Begin);
        }
    }

    /// <summary>Checks a file by path. Unreadable files simply return false (they are reported by the normal inspection).</summary>
    public static bool LooksLikeArchive(string path, long knownSize)
    {
        if (knownSize is > 0 and < 4 || SkippedExtensions.Contains(Path.GetExtension(path)))
        {
            return false;
        }

        try
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1, FileOptions.None);
            return StartsWithZipSignature(stream);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }
}
