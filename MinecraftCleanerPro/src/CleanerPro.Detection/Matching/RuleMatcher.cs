using System.Text.RegularExpressions;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Rules;

namespace CleanerPro.Detection.Matching;

/// <summary>The result of evaluating one rule against one observation.</summary>
public sealed record RuleEvaluation(CompiledRule Rule, Classification Level, IReadOnlyList<string> MatchedIndicatorIds, IReadOnlyList<Evidence> Evidence);

/// <summary>Matches observations against the compiled rule database and evaluates each rule's conditions.</summary>
public sealed class RuleMatcher
{
    private readonly CompiledRuleDatabase _database;
    private readonly LocationTemplateResolver _locations;
    private readonly Dictionary<string, IndicatorRef> _byKey = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string?> _expandedTemplates = new(StringComparer.Ordinal);

    public RuleMatcher(CompiledRuleDatabase database, LocationTemplateResolver? locations = null)
    {
        _database = database;
        _locations = locations ?? new LocationTemplateResolver();
        foreach (var rule in database.Rules)
        {
            foreach (var indicator in rule.Definition.Indicators)
            {
                _byKey[$"{rule.Id}/{indicator.Id}"] = new IndicatorRef(rule, indicator);
                if (indicator.LocationTemplate is not null)
                {
                    _expandedTemplates[indicator.LocationTemplate] = _locations.Expand(indicator.LocationTemplate);
                }
            }
        }
    }

    public CompiledRuleDatabase Database => _database;

    public IReadOnlyList<RuleEvaluation> Evaluate(ItemObservation observation, IReadOnlySet<DetectionCategory> enabledCategories)
    {
        var hits = new Dictionary<CompiledRule, Dictionary<string, Evidence>>();

        void Hit(IndicatorRef reference, string description, string? matched, string? location = null)
        {
            if (!IsApplicable(reference.Rule, observation, enabledCategories))
            {
                return;
            }

            if (!hits.TryGetValue(reference.Rule, out var perRule))
            {
                perRule = new Dictionary<string, Evidence>(StringComparer.Ordinal);
                hits[reference.Rule] = perRule;
            }

            perRule.TryAdd(reference.Indicator.Id, new Evidence
            {
                Kind = reference.Indicator.Type,
                RuleId = reference.Rule.Id,
                IndicatorId = reference.Indicator.Id,
                Description = reference.Indicator.Description is { Length: > 0 } d ? $"{d} — {description}" : description,
                MatchedValue = matched,
                Location = location,
                Strength = reference.Indicator.Strength,
            });
        }

        var isFile = observation.StartupEntry is null && !observation.IsDirectory;

        if (isFile)
        {
            Lookup(_database.BySha256, observation.Sha256, r => Hit(r, "SHA-256 equals a documented indicator", observation.Sha256));
            Lookup(_database.BySha1, observation.Sha1, r => Hit(r, "SHA-1 equals a documented indicator", observation.Sha1));
            Lookup(_database.ByFileName, observation.Name.ToLowerInvariant(), r =>
            {
                if (IsInsideTemplateLocation(r, observation.Path))
                {
                    Hit(r, $"File name is '{observation.Name}'", observation.Name);
                }
            });
            foreach (var (reference, regex) in _database.FileNamePatterns)
            {
                if (SafeIsMatch(regex, observation.Name) && IsInsideTemplateLocation(reference, observation.Path))
                {
                    Hit(reference, $"File name '{observation.Name}' matches a naming pattern", observation.Name);
                }
            }
        }

        if (observation.RelativePath is { Length: > 0 } relative)
        {
            Lookup(_database.ByRelativePath, relative.ToLowerInvariant(), r => Hit(r, $"Located at '{relative}' inside the installation", relative));
        }

        if (observation.IsDirectory)
        {
            Lookup(_database.ByDirectoryName, observation.Name.ToLowerInvariant(), r =>
            {
                if (!r.Indicator.AtInstallationRoot || IsDirectlyInInstallationRoot(observation))
                {
                    Hit(r, $"Folder named '{observation.Name}'{(r.Indicator.AtInstallationRoot ? " in the game directory" : string.Empty)}", observation.Name);
                }
            });
        }

        foreach (var key in observation.KnownLocationHits)
        {
            if (_byKey.TryGetValue(key, out var reference))
            {
                Hit(reference, $"Exists at the documented location '{observation.Path}'", observation.Path);
            }
        }

        if (observation.Archive is { } archive)
        {
            MatchArchive(observation, archive, Hit);
        }

        if (observation.StartupEntry is { } startup)
        {
            foreach (var (reference, regex) in _database.StartupPatterns)
            {
                if (SafeIsMatch(regex, startup.Command))
                {
                    Hit(reference, $"Startup entry '{startup.Name}' runs: {startup.Command}", startup.Command, startup.Source);
                }
            }
        }

        var results = new List<RuleEvaluation>();
        foreach (var (rule, evidence) in hits)
        {
            var matchedIds = new HashSet<string>(evidence.Keys, StringComparer.Ordinal);
            var level = EvaluateLevel(rule.Definition.Classification, matchedIds);
            if (level is not null)
            {
                results.Add(new RuleEvaluation(rule, level.Value, matchedIds.Order(StringComparer.Ordinal).ToList(), evidence.Values.ToList()));
            }
        }

        return results.OrderBy(r => ClassificationOrder.Rank(r.Level)).ThenBy(r => r.Rule.Id, StringComparer.Ordinal).ToList();
    }

    private void MatchArchive(ItemObservation observation, ArchiveObservation archive, Action<IndicatorRef, string, string?, string?> hit)
    {
        foreach (var mod in archive.Mods)
        {
            if (mod.ModId is null)
            {
                continue;
            }

            Lookup(_database.ByModId, mod.ModId.ToLowerInvariant(), r =>
            {
                if (r.Indicator.Loader is null || r.Indicator.Loader == mod.Loader)
                {
                    hit(r, $"{mod.MetadataFile ?? "Mod metadata"} declares mod id \"{mod.ModId}\"{(mod.Name is null ? string.Empty : $" (name \"{mod.Name}\")")}", mod.ModId, mod.MetadataFile);
                }
            });
        }

        foreach (var package in archive.ClassPackages)
        {
            Lookup(_database.ByPackage, package, r => hit(r, $"Contains Java classes in package '{package.TrimEnd('/').Replace('/', '.')}'", package, null));
        }

        foreach (var (entry, references) in _database.ByArchiveEntry)
        {
            if (archive.Entries.Contains(entry))
            {
                foreach (var reference in references)
                {
                    hit(reference, $"Contains the archive entry '{entry}'", entry, entry);
                }
            }
        }

        if (_database.EntryPatterns.Count > 0)
        {
            foreach (var entry in archive.Entries)
            {
                foreach (var (reference, regex) in _database.EntryPatterns)
                {
                    if (SafeIsMatch(regex, entry))
                    {
                        hit(reference, $"Contains '{entry}'", entry, entry);
                    }
                }
            }
        }

        foreach (var reference in _database.ManifestAttributes)
        {
            if (archive.ManifestAttributes.TryGetValue(reference.Indicator.Attribute!, out var value) &&
                value.StartsWith(reference.Indicator.Value!, StringComparison.Ordinal))
            {
                hit(reference, $"JAR manifest attribute {reference.Indicator.Attribute} is '{value}'", value, "META-INF/MANIFEST.MF");
            }
        }

        foreach (var (key, location) in archive.BytecodeHits)
        {
            if (_byKey.TryGetValue(key, out var reference))
            {
                hit(reference, $"Class '{location}' contains the documented bytecode sequence", key, location);
            }
        }
    }

    private static bool IsApplicable(CompiledRule rule, ItemObservation observation, IReadOnlySet<DetectionCategory> enabledCategories)
    {
        var definition = rule.Definition;
        if (!enabledCategories.Contains(definition.Category))
        {
            return false;
        }

        if (observation.StartupEntry is not null)
        {
            return definition.AppliesTo.Contains(RuleTarget.StartupEntry);
        }

        if (observation.IsDirectory)
        {
            return definition.AppliesTo.Contains(RuleTarget.Directory);
        }

        var targetOk = definition.AppliesTo.Contains(RuleTarget.File) ||
                       (observation.Archive is not null && definition.AppliesTo.Contains(RuleTarget.Archive));
        if (!targetOk)
        {
            return false;
        }

        return definition.FileExtensions.Count == 0 ||
               definition.FileExtensions.Contains(observation.Extension, StringComparer.OrdinalIgnoreCase);
    }

    private bool IsInsideTemplateLocation(IndicatorRef reference, string path)
    {
        var template = reference.Indicator.LocationTemplate;
        if (template is null)
        {
            return true;
        }

        if (!_expandedTemplates.TryGetValue(template, out var expanded) || expanded is null)
        {
            return false;
        }

        var parent = Path.GetDirectoryName(path);
        return parent is not null && string.Equals(PathKey.TrimTrailingSeparators(parent), PathKey.TrimTrailingSeparators(expanded), PathKey.Comparison);
    }

    private static bool IsDirectlyInInstallationRoot(ItemObservation observation)
    {
        if (observation.InstallationRoot is null)
        {
            return false;
        }

        var parent = Path.GetDirectoryName(observation.Path);
        return parent is not null && string.Equals(PathKey.TrimTrailingSeparators(parent), PathKey.TrimTrailingSeparators(observation.InstallationRoot), PathKey.Comparison);
    }

    private static void Lookup(Dictionary<string, List<IndicatorRef>> index, string? key, Action<IndicatorRef> action)
    {
        if (key is not null && index.TryGetValue(key, out var references))
        {
            foreach (var reference in references)
            {
                action(reference);
            }
        }
    }

    private static bool SafeIsMatch(Regex regex, string input)
    {
        try
        {
            return regex.IsMatch(input);
        }
        catch (RegexMatchTimeoutException)
        {
            return false;
        }
    }

    internal static Classification? EvaluateLevel(ClassificationDefinition classification, IReadOnlySet<string> matched)
    {
        if (Any(classification.KnownMatch, matched))
        {
            return Classification.KnownMatch;
        }

        if (Any(classification.HighConfidenceSuspicion, matched))
        {
            return Classification.HighConfidenceSuspicion;
        }

        if (Any(classification.NeedsReview, matched))
        {
            return Classification.NeedsReview;
        }

        if (Any(classification.LikelyLegitimate, matched))
        {
            return Classification.LikelyLegitimate;
        }

        return null;
    }

    private static bool Any(List<ConditionDefinition>? conditions, IReadOnlySet<string> matched) =>
        conditions is not null && conditions.Any(c => Satisfied(c, matched));

    internal static bool Satisfied(ConditionDefinition condition, IReadOnlySet<string> matched)
    {
        if (condition.All is not null && !condition.All.All(matched.Contains))
        {
            return false;
        }

        if (condition.Any is not null && !condition.Any.Any(matched.Contains))
        {
            return false;
        }

        if (condition.Counts is not null && !condition.Counts.All(c => c.Of.Count(matched.Contains) >= c.AtLeast))
        {
            return false;
        }

        return condition.All is not null || condition.Any is not null || condition.Counts is not null;
    }
}
