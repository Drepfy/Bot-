using System.Text;
using System.Text.Json.Nodes;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Rules;

namespace CleanerPro.Detection.Tests;

public sealed class RuleDatabaseTests
{
    private static byte[] Bundled => RuleRepository.ReadBundledBytes();

    [Theory]
    [InlineData("windows")]
    [InlineData("linux")]
    public void BundledDatabaseLoadsWithoutErrors(string platform)
    {
        var outcome = RuleDatabaseLoader.Load(Bundled, platform);
        Assert.True(outcome.Succeeded, string.Join(Environment.NewLine, outcome.Errors));
        Assert.True(outcome.Database!.DatabaseVersion > 0);
        Assert.NotEmpty(outcome.Database.Rules);
    }

    [Fact]
    public void EveryNonHeuristicRuleCitesVerifiedSources()
    {
        var database = RuleDatabaseLoader.Load(Bundled, "windows").Database!;
        foreach (var rule in database.Rules.Select(r => r.Definition).Where(r => !r.Heuristic && r.Category != DetectionCategory.TestSignature))
        {
            Assert.NotEmpty(rule.Sources);
            Assert.All(rule.Sources, s => Assert.StartsWith("https://", s.Url));
            Assert.Matches(@"^\d{4}-\d{2}-\d{2}$", rule.VerifiedOn!);
            Assert.False(string.IsNullOrWhiteSpace(rule.ConfidenceRationale));
        }
    }

    [Fact]
    public void BundledDatabaseCoversTheDocumentedFamilies()
    {
        var families = RuleDatabaseLoader.Load(Bundled, "windows").Database!.Rules.Select(r => r.Definition.Family).ToList();
        foreach (var expected in new[] { "Wurst Client", "Meteor Client", "LiquidBounce", "BleachHack", "ThunderHack", "Sodium" })
        {
            Assert.Contains(expected, families);
        }

        Assert.Contains(families, f => f.StartsWith("fractureiser", StringComparison.Ordinal));
    }

    [Fact]
    public void HeuristicRulesNeverProduceKnownMatches()
    {
        var database = RuleDatabaseLoader.Load(Bundled, "windows").Database!;
        Assert.All(database.Rules.Where(r => r.Definition.Heuristic), r => Assert.Empty(r.Definition.Classification.KnownMatch));
    }

    [Fact]
    public void WindowsOnlyRulesAreExcludedElsewhere()
    {
        var linux = RuleDatabaseLoader.Load(Bundled, "linux").Database!;
        Assert.True(linux.RulesExcludedByPlatform > 0);
        Assert.DoesNotContain(linux.Rules, r => r.Definition.Platforms.Contains("windows"));
    }

    private static byte[] Mutate(Action<JsonObject> change)
    {
        var document = JsonNode.Parse(Bundled)!.AsObject();
        change(document);
        return Encoding.UTF8.GetBytes(document.ToJsonString());
    }

    /// <summary>The Wurst rule: a non-heuristic rule with sources and every classification level used by these tests.</summary>
    private static JsonObject FirstRule(JsonObject document) =>
        document["rules"]!.AsArray().Select(r => r!.AsObject()).First(r => (string?)r["id"] == "CP-HC-0001");

    [Fact]
    public void InvalidRegularExpressionsAreRejected()
    {
        var bytes = Mutate(d =>
        {
            var heuristic = d["rules"]!.AsArray().Select(r => r!.AsObject()).First(r => r["id"]!.GetValue<string>() == "CP-HEUR-0005");
            heuristic["indicators"]![0]!["value"] = "([unclosed";
        });
        var outcome = RuleDatabaseLoader.Load(bytes, "windows");
        Assert.False(outcome.Succeeded);
        Assert.Contains(outcome.Errors, e => e.Contains("invalid regular expression"));
    }

    [Fact]
    public void ConditionsMustReferenceExistingIndicators()
    {
        var bytes = Mutate(d => FirstRule(d)["classification"]!["knownMatch"]![0]!["all"] = new JsonArray("does-not-exist"));
        var outcome = RuleDatabaseLoader.Load(bytes, "windows");
        Assert.Contains(outcome.Errors, e => e.Contains("unknown indicator 'does-not-exist'"));
    }

    [Fact]
    public void RulesWithoutSourcesAreRejected()
    {
        var bytes = Mutate(d => FirstRule(d)["sources"] = new JsonArray());
        Assert.Contains(RuleDatabaseLoader.Load(bytes, "windows").Errors, e => e.Contains("must cite at least one source"));
    }

    [Fact]
    public void InvalidHashesAreRejected()
    {
        var bytes = Mutate(d =>
        {
            var rule = d["rules"]!.AsArray().Select(r => r!.AsObject()).First(r => r["id"]!.GetValue<string>() == "CP-MAL-0002");
            rule["indicators"]![0]!["value"] = "1234";
        });
        Assert.Contains(RuleDatabaseLoader.Load(bytes, "windows").Errors, e => e.Contains("not a SHA-1"));
    }

    [Fact]
    public void DuplicateRuleIdsAreRejected()
    {
        var bytes = Mutate(d => d["rules"]!.AsArray().Add(FirstRule(d).DeepClone()));
        Assert.Contains(RuleDatabaseLoader.Load(bytes, "windows").Errors, e => e.Contains("duplicate rule id"));
    }

    [Fact]
    public void LegitimacyRulesCannotFlagFiles()
    {
        var bytes = Mutate(d =>
        {
            var rule = d["rules"]!.AsArray().Select(r => r!.AsObject()).First(r => r["category"]!.GetValue<string>() == "LegitimateSoftware");
            rule["classification"]!["knownMatch"] = new JsonArray(new JsonObject { ["all"] = new JsonArray("mod-id") });
        });
        Assert.Contains(RuleDatabaseLoader.Load(bytes, "windows").Errors, e => e.Contains("legitimate-software rules may only use likelyLegitimate"));
    }

    [Fact]
    public void UnsupportedFormatIsRejected()
    {
        var bytes = Mutate(d => d["formatVersion"] = 7);
        Assert.False(RuleDatabaseLoader.Load(bytes, "windows").Succeeded);
    }

    [Fact]
    public void MalformedJsonIsRejected()
    {
        Assert.False(RuleDatabaseLoader.Load(Encoding.UTF8.GetBytes("{ not json"), "windows").Succeeded);
    }
}
