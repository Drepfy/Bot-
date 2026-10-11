using System.Text.Json;
using System.Text.RegularExpressions;
using CleanerPro.Core.Models;

namespace CleanerPro.Scanner.Inspection;

/// <summary>
/// Reads mod identity from the metadata formats used by Fabric, Quilt, Forge, NeoForge and legacy Forge.
/// Malformed metadata is reported, never guessed.
/// </summary>
public static partial class ModMetadataParser
{
    private static readonly JsonDocumentOptions Options = new()
    {
        AllowTrailingCommas = true,
        CommentHandling = JsonCommentHandling.Skip,
        MaxDepth = 32,
    };

    public static ModIdentity? ParseFabric(string json, string metadataFile, out string? problem)
    {
        problem = null;
        try
        {
            using var document = JsonDocument.Parse(json, Options);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                problem = $"{metadataFile} is not a JSON object.";
                return null;
            }

            return new ModIdentity
            {
                Loader = ModLoader.Fabric,
                ModId = GetString(root, "id"),
                Name = GetString(root, "name"),
                Version = GetString(root, "version"),
                MetadataFile = metadataFile,
            };
        }
        catch (JsonException ex)
        {
            problem = $"{metadataFile} could not be parsed: {ex.Message}";
            return null;
        }
    }

    public static ModIdentity? ParseQuilt(string json, string metadataFile, out string? problem)
    {
        problem = null;
        try
        {
            using var document = JsonDocument.Parse(json, Options);
            if (!document.RootElement.TryGetProperty("quilt_loader", out var loader) || loader.ValueKind != JsonValueKind.Object)
            {
                problem = $"{metadataFile} has no quilt_loader section.";
                return null;
            }

            string? name = null;
            if (loader.TryGetProperty("metadata", out var metadata) && metadata.ValueKind == JsonValueKind.Object)
            {
                name = GetString(metadata, "name");
            }

            return new ModIdentity
            {
                Loader = ModLoader.Quilt,
                ModId = GetString(loader, "id"),
                Name = name,
                Version = GetString(loader, "version"),
                MetadataFile = metadataFile,
            };
        }
        catch (JsonException ex)
        {
            problem = $"{metadataFile} could not be parsed: {ex.Message}";
            return null;
        }
    }

    /// <summary>
    /// Extracts [[mods]] entries from mods.toml / neoforge.mods.toml. Only the simple
    /// key = "value" form used by mod metadata is supported; anything else is ignored.
    /// </summary>
    public static IReadOnlyList<ModIdentity> ParseModsToml(string toml, string metadataFile, ModLoader loader)
    {
        var results = new List<ModIdentity>();
        string? id = null, name = null, version = null;
        var inMods = false;

        void Flush()
        {
            if (inMods && id is not null)
            {
                results.Add(new ModIdentity { Loader = loader, ModId = id, Name = name, Version = version, MetadataFile = metadataFile });
            }

            id = name = version = null;
        }

        foreach (var rawLine in toml.Split('\n'))
        {
            var line = rawLine.Trim();
            if (line.StartsWith('#') || line.Length == 0)
            {
                continue;
            }

            if (line.StartsWith('['))
            {
                Flush();
                inMods = line.StartsWith("[[mods]]", StringComparison.Ordinal);
                continue;
            }

            if (!inMods)
            {
                continue;
            }

            var match = TomlString().Match(line);
            if (!match.Success)
            {
                continue;
            }

            switch (match.Groups[1].Value)
            {
                case "modId":
                    id = match.Groups[2].Value;
                    break;
                case "displayName":
                    name = match.Groups[2].Value;
                    break;
                case "version":
                    version = match.Groups[2].Value;
                    break;
            }
        }

        Flush();
        return results;
    }

    /// <summary>Legacy Forge mcmod.info: a JSON array, or an object with a modList array.</summary>
    public static IReadOnlyList<ModIdentity> ParseMcmodInfo(string json, string metadataFile, out string? problem)
    {
        problem = null;
        var results = new List<ModIdentity>();
        try
        {
            using var document = JsonDocument.Parse(json, Options);
            var root = document.RootElement;
            var list = root.ValueKind == JsonValueKind.Array
                ? root
                : root.ValueKind == JsonValueKind.Object && root.TryGetProperty("modList", out var modList) ? modList : default;
            if (list.ValueKind != JsonValueKind.Array)
            {
                problem = $"{metadataFile} has an unexpected structure.";
                return results;
            }

            foreach (var item in list.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.Object)
                {
                    results.Add(new ModIdentity
                    {
                        Loader = ModLoader.Forge,
                        ModId = GetString(item, "modid"),
                        Name = GetString(item, "name"),
                        Version = GetString(item, "version"),
                        MetadataFile = metadataFile,
                    });
                }
            }
        }
        catch (JsonException ex)
        {
            problem = $"{metadataFile} could not be parsed: {ex.Message}";
        }

        return results;
    }

    /// <summary>Main section of META-INF/MANIFEST.MF, including continuation lines.</summary>
    public static Dictionary<string, string> ParseManifest(string manifest)
    {
        var attributes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        string? lastKey = null;
        foreach (var rawLine in manifest.Replace("\r\n", "\n").Split('\n'))
        {
            if (rawLine.Length == 0)
            {
                break; // End of the main section.
            }

            if (rawLine.StartsWith(' ') && lastKey is not null)
            {
                attributes[lastKey] += rawLine[1..];
                continue;
            }

            var colon = rawLine.IndexOf(':');
            if (colon <= 0)
            {
                continue;
            }

            lastKey = rawLine[..colon].Trim();
            attributes[lastKey] = rawLine[(colon + 1)..].Trim();
        }

        return attributes;
    }

    private static string? GetString(JsonElement element, string property) =>
        element.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    [GeneratedRegex("^([A-Za-z]+)\\s*=\\s*[\"']([^\"']*)[\"']")]
    private static partial Regex TomlString();
}
