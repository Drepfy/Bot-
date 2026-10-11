using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using CleanerPro.Core;
using CleanerPro.Infrastructure.Platform;

namespace CleanerPro.Scanner;

/// <summary>A JVM option that loads extra code into the game (Java agent, native agent or boot class path).</summary>
public sealed record JvmAgentArgument(string Option, string Raw, string? TargetPath);

/// <summary>
/// Finds JVM options that load code into Minecraft from outside the mods folder: "-javaagent:", "-agentpath:",
/// "-agentlib:" and "-Xbootclasspath/a|p:". These are a common way to inject cheats (and some legitimate tools,
/// such as authentication helpers, use them too), so they are reported for review and the referenced files are scanned.
/// Settings files are only read, never changed.
/// </summary>
public static partial class LaunchSettingsInspector
{
    /// <summary>Settings files that hold JVM arguments, in a game directory or the folder above it.</summary>
    public static readonly IReadOnlyList<string> KnownSettingsFileNames =
    [
        "launcher_profiles.json",
        "launcher_profiles_microsoft_store.json",
        "instance.cfg",
        "minecraftinstance.json",
        "profile.json",
        "instance.json",
    ];

    private const long MaxSettingsFileBytes = 2 * 1024 * 1024;

    /// <summary>Extracts agent options from free text (a command line or a settings value).</summary>
    public static IReadOnlyList<JvmAgentArgument> FindAgentArguments(string text)
    {
        var results = new List<JvmAgentArgument>();
        foreach (Match match in AgentPattern().Matches(text))
        {
            var option = match.Groups["opt"].Value;
            var value = match.Groups["val"].Value.Trim().Trim('"', '\'');

            // INI-style settings escape backslashes; keep a leading UNC prefix intact.
            var prefix = value.StartsWith(@"\\", StringComparison.Ordinal) ? @"\\" : string.Empty;
            value = prefix + value[prefix.Length..].Replace(@"\\", @"\", StringComparison.Ordinal);
            results.Add(new JvmAgentArgument(option, $"{option}{match.Groups["sep"].Value}{value}", ExtractPath(option, value)));
        }

        return results;
    }

    /// <summary>
    /// Reads a settings file (JSON string values or INI lines) and returns the agent options it contains.
    /// Unreadable or oversized files return an empty list and a problem description.
    /// </summary>
    public static IReadOnlyList<JvmAgentArgument> InspectFile(string path, out string? problem)
    {
        problem = null;
        string text;
        try
        {
            var info = new FileInfo(path);
            if (!info.Exists)
            {
                return [];
            }

            if (info.Length > MaxSettingsFileBytes)
            {
                problem = $"'{path}' is larger than {MaxSettingsFileBytes / (1024 * 1024)} MB and was not read for JVM arguments.";
                return [];
            }

            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            using var reader = new StreamReader(stream, Encoding.UTF8, detectEncodingFromByteOrderMarks: true);
            text = reader.ReadToEnd();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            problem = $"'{path}' could not be read for JVM arguments: {ex.Message}";
            return [];
        }

        if (path.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
        {
            try
            {
                using var document = JsonDocument.Parse(text, new JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip, MaxDepth = 64 });
                var builder = new StringBuilder();
                CollectStrings(document.RootElement, builder);
                text = builder.ToString();
            }
            catch (JsonException)
            {
                // Fall back to the raw text: an agent option is still recognisable there.
            }
        }

        return FindAgentArguments(text);
    }

    /// <summary>Resolves an agent's file path; relative paths are tried against the given base folders.</summary>
    public static string? ResolveExistingFile(string? targetPath, IEnumerable<string> baseFolders)
    {
        if (string.IsNullOrWhiteSpace(targetPath) || targetPath.IndexOfAny(Path.GetInvalidPathChars()) >= 0)
        {
            return null;
        }

        try
        {
            if (Path.IsPathFullyQualified(targetPath))
            {
                return File.Exists(targetPath) ? PathKey.NormalizeFullPath(targetPath) : null;
            }

            foreach (var folder in baseFolders)
            {
                var candidate = Path.GetFullPath(Path.Combine(folder, targetPath));
                if (File.Exists(candidate))
                {
                    return PathKey.NormalizeFullPath(candidate);
                }
            }
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException or IOException)
        {
            return null;
        }

        return null;
    }

    /// <summary>Turns each agent option in a settings file into a startup-style entry for rule matching.</summary>
    public static IEnumerable<StartupEntry> ToEntries(string source, IReadOnlyList<JvmAgentArgument> arguments) =>
        arguments.Select((a, i) => new StartupEntry(source, arguments.Count == 1 ? "JVM argument" : $"JVM argument {i + 1}", a.Raw));

    private static string? ExtractPath(string option, string value)
    {
        if (option.Equals("-agentlib", StringComparison.OrdinalIgnoreCase))
        {
            return null; // A library name resolved from the Java library path, not a file path.
        }

        // "-javaagent:path.jar=options" / "-agentpath:lib.dll=options": the options start at the first '=' after the file name.
        var equals = value.IndexOf('=');
        var path = equals > 0 ? value[..equals] : value;
        if (option.StartsWith("-Xbootclasspath", StringComparison.OrdinalIgnoreCase))
        {
            path = path.Split(';')[0];
        }

        return path.Length == 0 ? null : path;
    }

    private static void CollectStrings(JsonElement element, StringBuilder builder)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.String:
                builder.Append(element.GetString()).Append('\n');
                break;
            case JsonValueKind.Array:
                foreach (var item in element.EnumerateArray())
                {
                    CollectStrings(item, builder);
                }

                break;
            case JsonValueKind.Object:
                foreach (var property in element.EnumerateObject())
                {
                    CollectStrings(property.Value, builder);
                }

                break;
        }
    }

    [GeneratedRegex(@"(?<![A-Za-z0-9])(?<opt>-javaagent|-agentpath|-agentlib|-Xbootclasspath/[ap])(?<sep>[:=])(?<val>""[^""\r\n]+""|'[^'\r\n]+'|[^\s""',\]]+)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, 250)]
    private static partial Regex AgentPattern();
}
