using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Bytecode;

namespace CleanerPro.Detection.Rules;

public sealed class CompiledRule
{
    internal CompiledRule(RuleDefinition definition)
    {
        Definition = definition;
        Indicators = definition.Indicators.ToDictionary(i => i.Id, StringComparer.Ordinal);
    }

    public RuleDefinition Definition { get; }

    public string Id => Definition.Id;

    public IReadOnlyDictionary<string, IndicatorDefinition> Indicators { get; }
}

public readonly record struct IndicatorRef(CompiledRule Rule, IndicatorDefinition Indicator)
{
    public string Key => $"{Rule.Id}/{Indicator.Id}";
}

public sealed record KnownLocationIndicator(IndicatorRef Ref, string Template, string Expect);

/// <summary>A validated rule database with lookup indexes for fast matching.</summary>
public sealed class CompiledRuleDatabase
{
    private static readonly TimeSpan RegexTimeout = TimeSpan.FromMilliseconds(250);

    internal CompiledRuleDatabase(RuleDatabaseDocument document, IReadOnlyList<CompiledRule> rules, string sha256, int excludedByPlatform)
    {
        Document = document;
        Rules = rules;
        Sha256 = sha256;
        RulesExcludedByPlatform = excludedByPlatform;

        foreach (var rule in rules)
        {
            foreach (var indicator in rule.Definition.Indicators)
            {
                var reference = new IndicatorRef(rule, indicator);
                var value = indicator.Value ?? string.Empty;
                switch (indicator.Type)
                {
                    case IndicatorType.Sha256:
                        Add(BySha256, value.ToLowerInvariant(), reference);
                        break;
                    case IndicatorType.Sha1:
                        Add(BySha1, value.ToLowerInvariant(), reference);
                        break;
                    case IndicatorType.ModId:
                        Add(ByModId, value.ToLowerInvariant(), reference);
                        break;
                    case IndicatorType.ClassPackagePrefix:
                        Add(ByPackage, value, reference);
                        break;
                    case IndicatorType.ArchiveEntry:
                        Add(ByArchiveEntry, value, reference);
                        break;
                    case IndicatorType.FileName:
                        Add(ByFileName, value.ToLowerInvariant(), reference);
                        break;
                    case IndicatorType.RelativePath:
                        Add(ByRelativePath, value.ToLowerInvariant(), reference);
                        break;
                    case IndicatorType.DirectoryName:
                        Add(ByDirectoryName, value.ToLowerInvariant(), reference);
                        break;
                    case IndicatorType.ArchiveEntryPattern:
                        EntryPatterns.Add((reference, CreateRegex(value)));
                        break;
                    case IndicatorType.FileNamePattern:
                        FileNamePatterns.Add((reference, CreateRegex(value)));
                        break;
                    case IndicatorType.StartupCommandPattern:
                        StartupPatterns.Add((reference, CreateRegex(value)));
                        break;
                    case IndicatorType.KnownLocation:
                        KnownLocations.Add(new KnownLocationIndicator(reference, value, indicator.Expect ?? "Any"));
                        break;
                    case IndicatorType.ManifestAttribute:
                        ManifestAttributes.Add(reference);
                        break;
                    case IndicatorType.BytecodeSignature:
                        BytecodeSignatures.Add(CompileSignature(reference));
                        break;
                }
            }
        }
    }

    public RuleDatabaseDocument Document { get; }

    public IReadOnlyList<CompiledRule> Rules { get; }

    /// <summary>SHA-256 of the exact database bytes.</summary>
    public string Sha256 { get; }

    public int RulesExcludedByPlatform { get; }

    public long DatabaseVersion => Document.DatabaseVersion;

    public string DisplayVersion => Document.DisplayVersion;

    internal Dictionary<string, List<IndicatorRef>> BySha256 { get; } = new(StringComparer.Ordinal);

    internal Dictionary<string, List<IndicatorRef>> BySha1 { get; } = new(StringComparer.Ordinal);

    internal Dictionary<string, List<IndicatorRef>> ByModId { get; } = new(StringComparer.Ordinal);

    internal Dictionary<string, List<IndicatorRef>> ByPackage { get; } = new(StringComparer.Ordinal);

    internal Dictionary<string, List<IndicatorRef>> ByArchiveEntry { get; } = new(StringComparer.Ordinal);

    internal Dictionary<string, List<IndicatorRef>> ByFileName { get; } = new(StringComparer.Ordinal);

    internal Dictionary<string, List<IndicatorRef>> ByRelativePath { get; } = new(StringComparer.Ordinal);

    internal Dictionary<string, List<IndicatorRef>> ByDirectoryName { get; } = new(StringComparer.Ordinal);

    internal List<(IndicatorRef Ref, Regex Regex)> EntryPatterns { get; } = [];

    internal List<(IndicatorRef Ref, Regex Regex)> FileNamePatterns { get; } = [];

    internal List<(IndicatorRef Ref, Regex Regex)> StartupPatterns { get; } = [];

    internal List<IndicatorRef> ManifestAttributes { get; } = [];

    public List<KnownLocationIndicator> KnownLocations { get; } = [];

    public List<CompiledBytecodeSignature> BytecodeSignatures { get; } = [];

    private static void Add(Dictionary<string, List<IndicatorRef>> index, string key, IndicatorRef reference)
    {
        if (!index.TryGetValue(key, out var list))
        {
            list = [];
            index[key] = list;
        }

        list.Add(reference);
    }

    internal static Regex CreateRegex(string pattern) =>
        new(pattern, RegexOptions.CultureInvariant | RegexOptions.Compiled, RegexTimeout);

    private static CompiledBytecodeSignature CompileSignature(IndicatorRef reference)
    {
        var definition = reference.Indicator.Bytecode!;
        var pattern = definition.Instructions.Select(i =>
        {
            JvmOpcodes.TryParse(i.Op, out var opcode);
            return new CompiledInstruction(opcode, i.Type, i.Owner, i.Name, i.Desc, i.Operand);
        }).ToList();
        return new CompiledBytecodeSignature(reference.Key, definition.Mode, pattern);
    }
}

public sealed record RuleLoadOutcome(CompiledRuleDatabase? Database, IReadOnlyList<string> Errors, IReadOnlyList<string> Warnings)
{
    public bool Succeeded => Database is not null && Errors.Count == 0;
}

/// <summary>Parses and strictly validates a rule database. Invalid databases are rejected as a whole.</summary>
public static partial class RuleDatabaseLoader
{
    public static string CurrentPlatform =>
        OperatingSystem.IsWindows() ? "windows" : OperatingSystem.IsMacOS() ? "macos" : "linux";

    public static RuleLoadOutcome Load(byte[] json, string? platform = null)
    {
        var errors = new List<string>();
        var warnings = new List<string>();
        RuleDatabaseDocument? document;
        try
        {
            document = JsonSerializer.Deserialize<RuleDatabaseDocument>(json, CleanerJson.Default);
        }
        catch (JsonException ex)
        {
            return new RuleLoadOutcome(null, [$"The rule database is not valid JSON or has a wrong value type at '{ex.Path}': {ex.Message}"], warnings);
        }

        if (document is null)
        {
            return new RuleLoadOutcome(null, ["The rule database is empty."], warnings);
        }

        Validate(document, errors, warnings);
        if (errors.Count > 0)
        {
            return new RuleLoadOutcome(null, errors, warnings);
        }

        platform ??= CurrentPlatform;
        var included = document.Rules
            .Where(r => r.Platforms.Count == 0 || r.Platforms.Contains(platform, StringComparer.OrdinalIgnoreCase))
            .Select(r => new CompiledRule(r))
            .ToList();
        var excluded = document.Rules.Count - included.Count;
        var sha = Convert.ToHexString(SHA256.HashData(json)).ToLowerInvariant();
        try
        {
            return new RuleLoadOutcome(new CompiledRuleDatabase(document, included, sha, excluded), errors, warnings);
        }
        catch (ArgumentException ex)
        {
            return new RuleLoadOutcome(null, [$"A rule pattern could not be compiled: {ex.Message}"], warnings);
        }
    }

    private static void Validate(RuleDatabaseDocument document, List<string> errors, List<string> warnings)
    {
        if (document.FormatVersion != RuleDatabaseDocument.SupportedFormatVersion)
        {
            errors.Add($"Unsupported rule database format {document.FormatVersion} (expected {RuleDatabaseDocument.SupportedFormatVersion}).");
            return;
        }

        if (document.DatabaseVersion <= 0)
        {
            errors.Add("databaseVersion must be a positive number.");
        }

        if (string.IsNullOrWhiteSpace(document.DisplayVersion))
        {
            errors.Add("displayVersion is required.");
        }

        if (document.Rules is null || document.Rules.Count == 0)
        {
            errors.Add("The database contains no rules.");
            return;
        }

        var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var rule in document.Rules)
        {
            var prefix = $"Rule '{rule?.Id}'";
            if (rule is null)
            {
                errors.Add("A rule entry is null.");
                continue;
            }

            if (!RuleIdPattern().IsMatch(rule.Id ?? string.Empty))
            {
                errors.Add($"{prefix}: id must match {RuleIdPattern()}.");
            }
            else if (!ids.Add(rule.Id!))
            {
                errors.Add($"{prefix}: duplicate rule id.");
            }

            if (rule.Version < 1)
            {
                errors.Add($"{prefix}: version must be 1 or higher.");
            }

            if (string.IsNullOrWhiteSpace(rule.Family))
            {
                errors.Add($"{prefix}: family is required.");
            }

            if (rule.AppliesTo is null || rule.AppliesTo.Count == 0)
            {
                errors.Add($"{prefix}: appliesTo must list at least one target.");
            }

            if (string.IsNullOrWhiteSpace(rule.ConfidenceRationale))
            {
                errors.Add($"{prefix}: confidenceRationale is required so every finding can be explained.");
            }

            var needsSources = !rule.Heuristic && rule.Category != DetectionCategory.TestSignature;
            if (needsSources)
            {
                if (rule.Sources is null || rule.Sources.Count == 0)
                {
                    errors.Add($"{prefix}: non-heuristic rules must cite at least one source.");
                }
                else if (rule.Sources.Any(s => s is null || string.IsNullOrWhiteSpace(s.Title) || !Uri.TryCreate(s.Url, UriKind.Absolute, out var u) || u.Scheme != Uri.UriSchemeHttps))
                {
                    errors.Add($"{prefix}: every source needs a title and an https URL.");
                }

                if (!DateOnly.TryParseExact(rule.VerifiedOn, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _))
                {
                    errors.Add($"{prefix}: verifiedOn must be a yyyy-MM-dd date.");
                }
            }

            if (rule.Indicators is null || rule.Indicators.Count == 0)
            {
                errors.Add($"{prefix}: at least one indicator is required.");
                continue;
            }

            var indicatorIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (var indicator in rule.Indicators)
            {
                if (indicator is null)
                {
                    errors.Add($"{prefix}: an indicator is null.");
                    continue;
                }

                if (!IndicatorIdPattern().IsMatch(indicator.Id ?? string.Empty) || !indicatorIds.Add(indicator.Id!))
                {
                    errors.Add($"{prefix}: indicator id '{indicator.Id}' is invalid or duplicated.");
                }

                ValidateIndicator(prefix, rule, indicator, errors);
            }

            ValidateClassification(prefix, rule, indicatorIds, errors);
        }
    }

    private static void ValidateIndicator(string prefix, RuleDefinition rule, IndicatorDefinition indicator, List<string> errors)
    {
        var where = $"{prefix}, indicator '{indicator.Id}'";
        var value = indicator.Value ?? string.Empty;

        void RequireTarget(params RuleTarget[] targets)
        {
            if (!targets.Any(t => rule.AppliesTo.Contains(t)))
            {
                errors.Add($"{where}: {indicator.Type} indicators require appliesTo to include {string.Join(" or ", targets)}.");
            }
        }

        switch (indicator.Type)
        {
            case IndicatorType.Sha256:
                if (!HexPattern().IsMatch(value) || value.Length != 64)
                {
                    errors.Add($"{where}: not a SHA-256 value.");
                }

                RequireTarget(RuleTarget.File, RuleTarget.Archive);
                break;
            case IndicatorType.Sha1:
                if (!HexPattern().IsMatch(value) || value.Length != 40)
                {
                    errors.Add($"{where}: not a SHA-1 value.");
                }

                RequireTarget(RuleTarget.File, RuleTarget.Archive);
                break;
            case IndicatorType.ModId:
                if (!ModIdPattern().IsMatch(value))
                {
                    errors.Add($"{where}: invalid mod id.");
                }

                RequireTarget(RuleTarget.Archive);
                break;
            case IndicatorType.ClassPackagePrefix:
                if (value.Length < 3 || !value.EndsWith('/') || value.StartsWith('/') || value.Contains('.') || value.Contains('\\'))
                {
                    errors.Add($"{where}: package prefixes use '/' separators and must end with '/'.");
                }

                RequireTarget(RuleTarget.Archive);
                break;
            case IndicatorType.ArchiveEntry:
                if (value.Length == 0 || value.StartsWith('/') || value.Contains('\\') || value.Contains(".."))
                {
                    errors.Add($"{where}: invalid archive entry name.");
                }

                RequireTarget(RuleTarget.Archive);
                break;
            case IndicatorType.ArchiveEntryPattern:
            case IndicatorType.FileNamePattern:
            case IndicatorType.StartupCommandPattern:
                if (value.Length == 0 || value.Length > 512)
                {
                    errors.Add($"{where}: pattern must be 1-512 characters.");
                }
                else
                {
                    try
                    {
                        _ = new Regex(value, RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250));
                    }
                    catch (ArgumentException ex)
                    {
                        errors.Add($"{where}: invalid regular expression: {ex.Message}");
                    }
                }

                if (indicator.Type == IndicatorType.ArchiveEntryPattern)
                {
                    RequireTarget(RuleTarget.Archive);
                }
                else if (indicator.Type == IndicatorType.StartupCommandPattern)
                {
                    RequireTarget(RuleTarget.StartupEntry);
                }

                break;
            case IndicatorType.FileName:
            case IndicatorType.DirectoryName:
                if (value.Length == 0 || value.IndexOfAny(['/', '\\', '*', '?']) >= 0)
                {
                    errors.Add($"{where}: names must not contain separators or wildcards.");
                }

                if (indicator.Type == IndicatorType.DirectoryName)
                {
                    RequireTarget(RuleTarget.Directory);
                }

                break;
            case IndicatorType.RelativePath:
                if (value.Length == 0 || value.StartsWith('/') || value.Contains('\\') || value.Contains(".."))
                {
                    errors.Add($"{where}: relative paths use '/' separators and must not contain '..'.");
                }

                break;
            case IndicatorType.KnownLocation:
                if (!IsValidTemplate(value))
                {
                    errors.Add($"{where}: known locations must start with an environment variable such as %LOCALAPPDATA% and must not contain '..'.");
                }

                if (indicator.Expect is not null && indicator.Expect is not ("File" or "Directory" or "Any"))
                {
                    errors.Add($"{where}: expect must be File, Directory or Any.");
                }

                break;
            case IndicatorType.ManifestAttribute:
                if (string.IsNullOrWhiteSpace(indicator.Attribute) || value.Length == 0)
                {
                    errors.Add($"{where}: manifest indicators need an attribute and a value.");
                }

                RequireTarget(RuleTarget.Archive);
                break;
            case IndicatorType.BytecodeSignature:
                ValidateBytecode(where, indicator.Bytecode, errors);
                RequireTarget(RuleTarget.Archive);
                break;
            default:
                errors.Add($"{where}: indicator type {indicator.Type} cannot be used in rules.");
                break;
        }

        if (indicator.LocationTemplate is not null && !IsValidTemplate(indicator.LocationTemplate))
        {
            errors.Add($"{where}: locationTemplate must start with an environment variable and must not contain '..'.");
        }
    }

    private static void ValidateBytecode(string where, BytecodeSignatureDefinition? bytecode, List<string> errors)
    {
        if (bytecode?.Instructions is null || bytecode.Instructions.Count == 0 || bytecode.Instructions.Count > 256)
        {
            errors.Add($"{where}: bytecode signatures need 1-256 instructions.");
            return;
        }

        foreach (var instruction in bytecode.Instructions)
        {
            if (instruction is null || !JvmOpcodes.TryParse(instruction.Op, out var opcode))
            {
                errors.Add($"{where}: unknown opcode '{instruction?.Op}'.");
                continue;
            }

            var isInvoke = opcode is JvmOpcodes.Invokevirtual or JvmOpcodes.Invokespecial or JvmOpcodes.Invokestatic or JvmOpcodes.Invokeinterface;
            if (isInvoke && (instruction.Owner is null || instruction.Name is null || instruction.Desc is null))
            {
                errors.Add($"{where}: {instruction.Op} needs owner, name and desc.");
            }

            if (opcode == JvmOpcodes.New && instruction.Type is null)
            {
                errors.Add($"{where}: NEW needs a type.");
            }
        }
    }

    private static void ValidateClassification(string prefix, RuleDefinition rule, HashSet<string> indicatorIds, List<string> errors)
    {
        var classification = rule.Classification;
        if (classification is null)
        {
            errors.Add($"{prefix}: classification is required.");
            return;
        }

        var levels = new (string Name, List<ConditionDefinition>? Conditions)[]
        {
            ("knownMatch", classification.KnownMatch),
            ("highConfidenceSuspicion", classification.HighConfidenceSuspicion),
            ("needsReview", classification.NeedsReview),
            ("likelyLegitimate", classification.LikelyLegitimate),
        };

        if (levels.All(l => l.Conditions is null || l.Conditions.Count == 0))
        {
            errors.Add($"{prefix}: at least one classification condition is required.");
        }

        var isLegitimacyRule = rule.Category == DetectionCategory.LegitimateSoftware;
        if (isLegitimacyRule && levels.Take(3).Any(l => l.Conditions is { Count: > 0 }))
        {
            errors.Add($"{prefix}: legitimate-software rules may only use likelyLegitimate conditions.");
        }

        if (!isLegitimacyRule && classification.LikelyLegitimate is { Count: > 0 })
        {
            errors.Add($"{prefix}: only LegitimateSoftware rules may use likelyLegitimate conditions.");
        }

        if (rule.Heuristic && classification.KnownMatch is { Count: > 0 })
        {
            errors.Add($"{prefix}: heuristic rules cannot produce a Known match.");
        }

        foreach (var (name, conditions) in levels)
        {
            foreach (var condition in conditions ?? [])
            {
                if (condition is null || (condition.All is null && condition.Any is null && condition.Counts is null))
                {
                    errors.Add($"{prefix}: an empty {name} condition is not allowed.");
                    continue;
                }

                var referenced = (condition.All ?? []).Concat(condition.Any ?? []).Concat((condition.Counts ?? []).SelectMany(c => c?.Of ?? []));
                foreach (var id in referenced)
                {
                    if (!indicatorIds.Contains(id))
                    {
                        errors.Add($"{prefix}: {name} references unknown indicator '{id}'.");
                    }
                }

                foreach (var count in condition.Counts ?? [])
                {
                    if (count is null || count.AtLeast < 1 || count.Of is null || count.AtLeast > count.Of.Count)
                    {
                        errors.Add($"{prefix}: {name} has an invalid count condition.");
                    }
                }
            }
        }
    }

    private static bool IsValidTemplate(string? template) =>
        !string.IsNullOrWhiteSpace(template) && TemplatePattern().IsMatch(template) && !template.Contains("..");

    [GeneratedRegex("^[A-Z0-9][A-Z0-9-]{2,63}$")]
    private static partial Regex RuleIdPattern();

    [GeneratedRegex("^[a-z0-9][a-z0-9-]{0,63}$")]
    private static partial Regex IndicatorIdPattern();

    [GeneratedRegex("^[A-Fa-f0-9]+$")]
    private static partial Regex HexPattern();

    [GeneratedRegex("^[a-z0-9_.-]{1,64}$")]
    private static partial Regex ModIdPattern();

    [GeneratedRegex(@"^%[A-Z_][A-Z0-9_]*%([\\/][^\\/:*?""<>|]+)*$", RegexOptions.IgnoreCase)]
    private static partial Regex TemplatePattern();
}
