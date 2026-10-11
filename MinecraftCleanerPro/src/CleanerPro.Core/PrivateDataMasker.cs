namespace CleanerPro.Core;

/// <summary>A piece of text that is either ordinary or private (for example the Windows user name inside a path).</summary>
public readonly record struct TextSegment(string Text, bool IsPrivate);

/// <summary>
/// Finds personal information in text shown on screen (the Windows user name, the user-profile folder name and the
/// computer name) so the interface can cover it with a black bar. Matches are whole words only: a user name "al"
/// is found in "C:\Users\al\" but not in "install".
/// </summary>
public sealed class PrivateDataMasker
{
    private readonly string[] _tokens;

    public PrivateDataMasker(IEnumerable<string?> privateValues)
    {
        _tokens = privateValues
            .Where(v => !string.IsNullOrWhiteSpace(v) && v.Trim().Length >= 2)
            .Select(v => v!.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderByDescending(v => v.Length) // Longest first, so "John Smith" wins over "John".
            .ToArray();
    }

    /// <summary>The user name, the user-profile folder name (which can differ) and the computer name of this session.</summary>
    public static PrivateDataMasker ForCurrentUser()
    {
        string? profileFolder = null;
        try
        {
            var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile, Environment.SpecialFolderOption.DoNotVerify);
            profileFolder = string.IsNullOrEmpty(profile) ? null : Path.GetFileName(PathKey.TrimTrailingSeparators(profile));
        }
        catch (Exception ex) when (ex is PlatformNotSupportedException or ArgumentException)
        {
        }

        return new PrivateDataMasker([SafeGet(() => Environment.UserName), profileFolder, SafeGet(() => Environment.MachineName)]);
    }

    public bool HasPrivateValues => _tokens.Length > 0;

    public bool ContainsPrivateData(string? text) => text is not null && Split(text).Any(s => s.IsPrivate);

    /// <summary>Splits text into ordinary and private segments, in order; joining them gives the original text.</summary>
    public IReadOnlyList<TextSegment> Split(string? text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return [];
        }

        var segments = new List<TextSegment>();
        var plainStart = 0;
        var index = 0;
        while (index < text.Length)
        {
            var match = _tokens.FirstOrDefault(token => IsWholeWordAt(text, index, token));
            if (match is null)
            {
                index++;
                continue;
            }

            if (index > plainStart)
            {
                segments.Add(new TextSegment(text[plainStart..index], false));
            }

            segments.Add(new TextSegment(text.Substring(index, match.Length), true));
            index += match.Length;
            plainStart = index;
        }

        if (plainStart < text.Length)
        {
            segments.Add(new TextSegment(text[plainStart..], false));
        }

        return segments;
    }

    /// <summary>Replaces private values with a fixed mask, for places that cannot draw black bars (for example plain text views).</summary>
    public string Mask(string? text, string mask = "████")
    {
        if (string.IsNullOrEmpty(text))
        {
            return text ?? string.Empty;
        }

        return string.Concat(Split(text).Select(s => s.IsPrivate ? mask : s.Text));
    }

    private static bool IsWholeWordAt(string text, int index, string token)
    {
        if (index + token.Length > text.Length || string.Compare(text, index, token, 0, token.Length, StringComparison.OrdinalIgnoreCase) != 0)
        {
            return false;
        }

        var before = index == 0 || !char.IsLetterOrDigit(text[index - 1]);
        var afterIndex = index + token.Length;
        var after = afterIndex >= text.Length || !char.IsLetterOrDigit(text[afterIndex]);
        return before && after;
    }

    private static string? SafeGet(Func<string> read)
    {
        try
        {
            return read();
        }
        catch (Exception ex) when (ex is InvalidOperationException or PlatformNotSupportedException)
        {
            return null;
        }
    }
}
