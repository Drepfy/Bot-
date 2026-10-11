namespace CleanerPro.Core;

/// <summary>Path normalization and comparison helpers shared by every module.</summary>
public static class PathKey
{
    /// <summary>Windows and macOS file systems are case-insensitive by default.</summary>
    public static bool IsCaseInsensitivePlatform => OperatingSystem.IsWindows() || OperatingSystem.IsMacOS();

    public static StringComparison Comparison =>
        IsCaseInsensitivePlatform ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;

    public static StringComparer Comparer =>
        IsCaseInsensitivePlatform ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;

    /// <summary>Returns the full path without trailing separators (except for a root).</summary>
    public static string NormalizeFullPath(string path)
    {
        var full = Path.GetFullPath(path);
        return TrimTrailingSeparators(full);
    }

    /// <summary>A key suitable for de-duplicating paths on the current platform.</summary>
    public static string ToKey(string path)
    {
        var full = NormalizeFullPath(path);
        return IsCaseInsensitivePlatform ? full.ToUpperInvariant() : full;
    }

    public static string TrimTrailingSeparators(string path)
    {
        var root = Path.GetPathRoot(path) ?? string.Empty;
        var trimmed = path;
        while (trimmed.Length > root.Length &&
               (trimmed.EndsWith(Path.DirectorySeparatorChar) || trimmed.EndsWith(Path.AltDirectorySeparatorChar)))
        {
            trimmed = trimmed[..^1];
        }

        return trimmed;
    }

    /// <summary>True when <paramref name="candidate"/> equals <paramref name="root"/> or is located below it.</summary>
    public static bool IsSameOrWithin(string candidate, string root, StringComparison comparison)
    {
        var c = TrimTrailingSeparators(candidate);
        var r = TrimTrailingSeparators(root);
        if (string.Equals(c, r, comparison))
        {
            return true;
        }

        if (!c.StartsWith(r, comparison) || c.Length <= r.Length)
        {
            return false;
        }

        // The character right after the root must be a separator (unless the root itself ends with one, e.g. "C:\").
        var rootEndsWithSeparator = r.EndsWith(Path.DirectorySeparatorChar) || r.EndsWith(Path.AltDirectorySeparatorChar);
        var next = c[r.Length];
        return rootEndsWithSeparator || next == Path.DirectorySeparatorChar || next == Path.AltDirectorySeparatorChar;
    }

    public static bool IsSameOrWithin(string candidate, string root) => IsSameOrWithin(candidate, root, Comparison);
}
