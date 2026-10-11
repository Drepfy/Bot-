using System.Text.RegularExpressions;

namespace CleanerPro.Detection.Matching;

/// <summary>Expands rule location templates such as %LOCALAPPDATA%\Microsoft Edge into absolute paths.</summary>
public sealed partial class LocationTemplateResolver
{
    private readonly Func<string, string?> _variables;

    public LocationTemplateResolver(Func<string, string?>? variables = null)
    {
        _variables = variables ?? DefaultVariable;
    }

    /// <summary>Returns the expanded absolute path, or null when a variable is not defined on this system.</summary>
    public string? Expand(string template)
    {
        var missing = false;
        var expanded = VariablePattern().Replace(template, match =>
        {
            var value = _variables(match.Groups[1].Value);
            if (string.IsNullOrEmpty(value))
            {
                missing = true;
                return string.Empty;
            }

            return value.TrimEnd('\\', '/');
        });

        if (missing)
        {
            return null;
        }

        expanded = expanded.Replace('\\', Path.DirectorySeparatorChar).Replace('/', Path.DirectorySeparatorChar);
        return Path.IsPathFullyQualified(expanded) ? Path.GetFullPath(expanded) : null;
    }

    private static string? DefaultVariable(string name)
    {
        var value = Environment.GetEnvironmentVariable(name);
        if (!string.IsNullOrEmpty(value))
        {
            return value;
        }

        return name.ToUpperInvariant() switch
        {
            "LOCALAPPDATA" => Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "APPDATA" => Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "USERPROFILE" => Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "WINDIR" => Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            _ => null,
        };
    }

    [GeneratedRegex("%([A-Za-z_][A-Za-z0-9_]*)%")]
    private static partial Regex VariablePattern();
}
