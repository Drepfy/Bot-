using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Matching;
using CleanerPro.Detection.Rules;

namespace CleanerPro.Scanner;

/// <summary>An existing item at a documented location, with the rule indicators that point to it.</summary>
public sealed record KnownLocationHit(string Path, bool IsDirectory, IReadOnlyList<string> IndicatorKeys, IReadOnlyList<string> Families);

public sealed record SystemArtifactResolution(
    IReadOnlyDictionary<string, KnownLocationHit> HitsByPathKey,
    IReadOnlyList<ScanRoot> Roots,
    IReadOnlyList<string> Notes);

/// <summary>
/// Resolves the rule database's documented locations (for example malware persistence folders) on this
/// computer. Read-only: existence checks only, without following links.
/// </summary>
public static class SystemArtifactResolver
{
    public static SystemArtifactResolution Resolve(CompiledRuleDatabase database, LocationTemplateResolver resolver, IReadOnlySet<DetectionCategory> enabledCategories)
    {
        var hits = new Dictionary<string, (string Path, bool IsDirectory, List<string> Keys, HashSet<string> Families)>(PathKey.Comparer);
        var roots = new Dictionary<string, ScanRoot>(PathKey.Comparer);
        var notes = new List<string>();

        foreach (var location in database.KnownLocations)
        {
            var definition = location.Ref.Rule.Definition;
            if (!enabledCategories.Contains(definition.Category))
            {
                continue;
            }

            var expanded = resolver.Expand(location.Template);
            if (expanded is null)
            {
                notes.Add($"Location {location.Template} ({definition.Family}) could not be resolved on this computer and was not checked.");
                continue;
            }

            FileAttributes attributes;
            try
            {
                attributes = File.GetAttributes(expanded);
            }
            catch (Exception ex) when (ex is FileNotFoundException or DirectoryNotFoundException)
            {
                continue; // Not present: nothing to report.
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                notes.Add($"Could not check '{expanded}' ({definition.Family}): {ex.Message}");
                continue;
            }

            var isDirectory = attributes.HasFlag(FileAttributes.Directory);
            if ((location.Expect == "File" && isDirectory) || (location.Expect == "Directory" && !isDirectory))
            {
                continue;
            }

            var key = PathKey.ToKey(expanded);
            if (!hits.TryGetValue(key, out var entry))
            {
                entry = (expanded, isDirectory, [], new HashSet<string>(StringComparer.Ordinal));
                hits[key] = entry;
            }

            entry.Keys.Add(location.Ref.Key);
            entry.Families.Add(definition.Family);

            if (attributes.HasFlag(FileAttributes.ReparsePoint))
            {
                notes.Add($"'{expanded}' is a link; it is reported but not followed.");
                continue;
            }

            roots.TryAdd(key, new ScanRoot
            {
                Path = expanded,
                Kind = ScanRootKind.SystemArtifactLocation,
                Reason = $"Documented location for {definition.Family}",
                Recursive = false,
                IsFile = !isDirectory,
            });
        }

        // Folders referenced by location-scoped file-name indicators (for example the Startup folder).
        foreach (var rule in database.Rules)
        {
            if (!enabledCategories.Contains(rule.Definition.Category))
            {
                continue;
            }

            foreach (var indicator in rule.Definition.Indicators.Where(i => i.LocationTemplate is not null))
            {
                var folder = resolver.Expand(indicator.LocationTemplate!);
                if (folder is null || !Directory.Exists(folder))
                {
                    continue;
                }

                roots.TryAdd(PathKey.ToKey(folder), new ScanRoot
                {
                    Path = folder,
                    Kind = ScanRootKind.SystemArtifactLocation,
                    Reason = $"Checked for files documented by {rule.Definition.Family} (only this folder, not subfolders)",
                    Recursive = false,
                });
            }
        }

        return new SystemArtifactResolution(
            hits.ToDictionary(h => h.Key, h => new KnownLocationHit(h.Value.Path, h.Value.IsDirectory, h.Value.Keys, h.Value.Families.ToList()), PathKey.Comparer),
            roots.Values.ToList(),
            notes);
    }
}
