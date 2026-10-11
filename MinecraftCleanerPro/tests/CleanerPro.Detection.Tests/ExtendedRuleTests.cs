using System.Text.Json.Nodes;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Matching;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure.Platform;

namespace CleanerPro.Detection.Tests;

/// <summary>
/// The clients, add-ons, impersonation checks and launch-option rules added in rule database 2026.10.11.2,
/// plus the engine features they rely on ("none" conditions and entrypoint indicators). All inputs are synthetic.
/// </summary>
public sealed class ExtendedRuleTests
{
    private static readonly CompiledRuleDatabase Database = RuleDatabaseLoader.Load(RuleRepository.ReadBundledBytes(), "windows").Database!;
    private static readonly IReadOnlySet<DetectionCategory> All = Enum.GetValues<DetectionCategory>().ToHashSet();

    private static ItemObservation Jar(string name, Action<ArchiveObservation> fill, bool incomplete = false)
    {
        var archive = new ArchiveObservation();
        fill(archive);
        var observation = new ItemObservation
        {
            Path = Path.Combine(Path.GetTempPath(), "mc", "mods", name),
            Name = name,
            Archive = archive,
            Sha256 = new string('b', 64),
        };
        if (incomplete)
        {
            observation.InspectionProblems.Add("Entry limit reached.");
        }

        return observation;
    }

    private static void Mod(ArchiveObservation archive, string id, params string[] entrypoints) =>
        archive.Mods.Add(new ModIdentity { Loader = ModLoader.Fabric, ModId = id, MetadataFile = "fabric.mod.json", Entrypoints = entrypoints });

    private static Finding? Classify(ItemObservation observation) =>
        new FindingClassifier().Classify(observation, new RuleMatcher(Database).Evaluate(observation, All), new ClassifierOptions()).Finding;

    [Theory]
    [InlineData("aoba", "net/aoba/Aoba.class", "CP-HC-0006")]
    [InlineData("jex", "me/dustin/jex/load/JexLoad.class", "CP-HC-0008")]
    [InlineData("anarchyclient", "net/blockhost/anarchyclient/AnarchyClient.class", "CP-HC-0009")]
    [InlineData("ares", "dev/tigr/ares/Ares.class", "CP-HC-0010")]
    [InlineData("kamiblue", "org/kamiblue/client/KamiMod.class", "CP-HC-0011")]
    [InlineData("salhack", "me/ionar/salhack/SalHack.class", "CP-HC-0014")]
    [InlineData("forgehax", "com/matt/forgehax/ForgeHax.class", "CP-HC-0015")]
    [InlineData("earthhack", "me/earth/earthhack/Earthhack.class", "CP-HC-0016")]
    [InlineData("seppukumod", "me/rigamortis/seppuku/Seppuku.class", "CP-HC-0017")]
    [InlineData("gamesense", "com/gamesense/client/GameSense.class", "CP-HC-0018")]
    [InlineData("fdpclient", "net/ccbluex/liquidbounce/FDPClient.class", "CP-HC-0019")]
    [InlineData("meteor-rejects", "anticope/rejects/MeteorRejectsAddon.class", "CP-ADDON-0002")]
    [InlineData("streak-addon", "pwn/noobs/trouserstreak/Trouser.class", "CP-ADDON-0004")]
    [InlineData("blackout", "kassuk/addon/blackout/BlackOut.class", "CP-ADDON-0009")]
    public void NewClientsAreKnownMatchesWithModIdAndPackage(string modId, string classEntry, string ruleId)
    {
        var finding = Classify(Jar("x.jar", a =>
        {
            Mod(a, modId);
            a.AddEntry(classEntry);
        }))!;

        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Contains(finding.RuleMatches, m => m.RuleId == ruleId && m.Classification == Classification.KnownMatch && m.Sources.Count > 0);
    }

    [Fact]
    public void ForgeCoreModManifestIsASecondIndependentIndicator()
    {
        var finding = Classify(Jar("renamed.jar", a =>
        {
            a.AddEntry("org/kamiblue/client/KamiMod.class");
            a.ManifestAttributes["FMLCorePlugin"] = "org.kamiblue.client.mixin.MixinLoaderForge";
        }))!;

        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Contains(finding.Evidence, e => e.Kind == IndicatorType.ManifestAttribute && e.RuleId == "CP-HC-0011");
    }

    [Fact]
    public void LegacyLiquidBounceIsMatchedByItsCoreModAndForgeMixins()
    {
        var finding = Classify(Jar("lb.jar", a =>
        {
            a.AddEntry("net/ccbluex/liquidbounce/LiquidBounce.class");
            a.AddEntry("liquidbounce.forge.mixins.json");
            a.ManifestAttributes["FMLCorePlugin"] = "net.ccbluex.liquidbounce.injection.forge.MixinLoader";
        }))!;

        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Contains(finding.RuleMatches, m => m.RuleId == "CP-HC-0003" && m.RuleVersion == 2);
    }

    [Fact]
    public void ArgonDisguisedAsImmediatelyFastIsAKnownMatch()
    {
        var finding = Classify(Jar("immediatelyfast-1.2.11.jar", a =>
        {
            Mod(a, "immediatelyfast", "main");
            a.AddEntry("dev/lvstrng/argon/Main.class");
        }))!;

        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Contains(finding.RuleMatches, m => m.RuleId == "CP-HC-0007");
        Assert.Contains(finding.RuleMatches, m => m.RuleId == "CP-IMP-0005"); // The impersonation check fires as well.
    }

    [Fact]
    public void AnyMeteorAddonIsFoundByItsEntrypoint()
    {
        var finding = Classify(Jar("unknown-addon.jar", a =>
        {
            Mod(a, "some-new-addon", "meteor");
            a.AddEntry("com/example/addon/Addon.class");
        }))!;

        Assert.Equal(Classification.HighConfidenceSuspicion, finding.Classification);
        Assert.Contains(finding.Evidence, e => e.Kind == IndicatorType.ModEntrypoint && e.MatchedValue == "meteor");
    }

    [Fact]
    public void RusherHackPluginsAreFoundByTheirManifest()
    {
        var finding = Classify(Jar("plugin.jar", a => a.AddEntry("rusherhack-plugin.json")))!;
        Assert.Equal(Classification.HighConfidenceSuspicion, finding.Classification);
        Assert.Contains(finding.RuleMatches, m => m.RuleId == "CP-ADDON-0011");
    }

    [Theory]
    [InlineData("sodium", "CP-IMP-0001")]
    [InlineData("iris", "CP-IMP-0002")]
    [InlineData("lithium", "CP-IMP-0003")]
    [InlineData("modmenu", "CP-IMP-0004")]
    [InlineData("immediatelyfast", "CP-IMP-0005")]
    public void AJarClaimingAPopularModWithoutItsCodeIsAnImpersonation(string modId, string ruleId)
    {
        var finding = Classify(Jar($"{modId}.jar", a =>
        {
            Mod(a, modId);
            a.AddEntry("a/b/Hidden.class");
        }))!;

        Assert.Equal(Classification.HighConfidenceSuspicion, finding.Classification);
        Assert.Contains(finding.RuleMatches, m => m.RuleId == ruleId);
    }

    [Theory]
    [InlineData("sodium", "net/caffeinemc/mods/sodium/client/SodiumClientMod.class")]
    [InlineData("sodium", "me/jellysquid/mods/sodium/client/SodiumClientMod.class")]
    [InlineData("iris", "net/coderbot/iris/Iris.class")]
    [InlineData("modmenu", "io/github/prospector/modmenu/ModMenu.class")]
    [InlineData("immediatelyfast", "net/raphimc/immediatelyfast/ImmediatelyFast.class")]
    public void RealModsInAnyOfficialPackageAreNotImpersonations(string modId, string classEntry)
    {
        var observation = Jar($"{modId}.jar", a =>
        {
            Mod(a, modId);
            a.AddEntry(classEntry);
        });

        Assert.Null(Classify(observation)); // Likely legitimate items are not listed by default.
        Assert.Contains(new RuleMatcher(Database).Evaluate(observation, All), e => e.Level == Classification.LikelyLegitimate);
    }

    [Fact]
    public void MissingPackagesProveNothingWhenTheJarWasNotFullyRead()
    {
        var observation = Jar("sodium.jar", a => Mod(a, "sodium"), incomplete: true);
        Assert.DoesNotContain(new RuleMatcher(Database).Evaluate(observation, All), e => e.Rule.Id == "CP-IMP-0001");
    }

    [Theory]
    [InlineData("future-client-1.20.jar", true)]
    [InlineData("rise_client.exe", true)]
    [InlineData("vape-lite.exe", true)]
    [InlineData("LiquidBounce-b73.jar", true)]
    [InlineData("rusherhack-loader.jar", true)]
    [InlineData("Raven-B4.jar", true)]
    [InlineData("future.jar", false)]
    [InlineData("sunrise-shaders.zip", false)]
    [InlineData("impactor.jar", false)]
    public void ClientNamesInFileNamesAreOnlyReportedForReview(string fileName, bool expected)
    {
        var observation = new ItemObservation { Path = Path.Combine(Path.GetTempPath(), "Downloads", fileName), Name = fileName, Sha256 = new string('c', 64) };
        var evaluations = new RuleMatcher(Database).Evaluate(observation, All).Where(e => e.Rule.Id == "CP-HEUR-0005").ToList();
        Assert.Equal(expected, evaluations.Count == 1);
        Assert.All(evaluations, e => Assert.Equal(Classification.NeedsReview, e.Level));
    }

    [Theory]
    [InlineData("-Xmx4G -javaagent:C:\\Tools\\agent.jar -XX:+UseG1GC", true)]
    [InlineData("-agentpath:C:\\inject.dll=opt", true)]
    [InlineData("-Xbootclasspath/a:C:\\x.jar", true)]
    [InlineData("-Xmx4G -XX:+UseG1GC", false)]
    public void JavaAgentOptionsInLaunchSettingsNeedReviewAndManualCleanup(string arguments, bool expected)
    {
        var entry = new StartupEntry(@"C:\Users\me\AppData\Roaming\.minecraft\launcher_profiles.json", "JVM argument", arguments);
        var observation = new ItemObservation { Path = $@"{entry.Source}\{entry.Name}", Name = entry.Name, IsSystemArtifact = true, StartupEntry = entry };
        var finding = Classify(observation);

        if (!expected)
        {
            Assert.Null(finding);
            return;
        }

        Assert.NotNull(finding);
        Assert.Equal(Classification.NeedsReview, finding.Classification);
        Assert.Contains(finding.RuleMatches, m => m.RuleId == "CP-LOAD-0001");
        Assert.True(finding.RequiresManualCleanup);
        Assert.Contains("launcher settings file", finding.ManualCleanupGuidance);
    }

    [Fact]
    public void EnvironmentVariableFindingsExplainHowToRemoveThem()
    {
        var entry = new StartupEntry("User environment variable", "JAVA_TOOL_OPTIONS", "-javaagent:C:\\x\\cheat.jar");
        var finding = Classify(new ItemObservation { Path = $@"{entry.Source}\{entry.Name}", Name = entry.Name, IsSystemArtifact = true, StartupEntry = entry })!;
        Assert.True(finding.RequiresManualCleanup);
        Assert.Contains("Environment Variables", finding.ManualCleanupGuidance);
    }

    [Fact]
    public void NoneConditionsAreSatisfiedOnlyWhenTheIndicatorsAreAbsent()
    {
        var condition = new ConditionDefinition { All = ["a"], None = ["b"] };
        Assert.True(RuleMatcher.Satisfied(condition, new HashSet<string> { "a" }));
        Assert.False(RuleMatcher.Satisfied(condition, new HashSet<string> { "a", "b" }));
        Assert.False(RuleMatcher.Satisfied(condition, new HashSet<string> { "a" }, absenceIsMeaningful: false));
    }

    [Fact]
    public void NoneOnlyAndKnownMatchNoneConditionsAreRejected()
    {
        var bytes = Mutate(rule =>
        {
            rule["classification"]!["highConfidenceSuspicion"] = new JsonArray(new JsonObject { ["none"] = new JsonArray("package") });
            rule["classification"]!["knownMatch"]![0]!["none"] = new JsonArray("mixins");
        });
        var errors = RuleDatabaseLoader.Load(bytes, "windows").Errors;
        Assert.Contains(errors, e => e.Contains("'none' needs all, any or counts"));
        Assert.Contains(errors, e => e.Contains("knownMatch conditions cannot rely on missing indicators"));
    }

    [Fact]
    public void EveryNewRuleCitesAPrimarySource()
    {
        foreach (var rule in Database.Rules.Where(r => r.Id.StartsWith("CP-HC-", StringComparison.Ordinal) || r.Id.StartsWith("CP-ADDON-", StringComparison.Ordinal) ||
                                                       r.Id.StartsWith("CP-IMP-", StringComparison.Ordinal) || r.Id.StartsWith("CP-LOAD-", StringComparison.Ordinal)))
        {
            Assert.NotEmpty(rule.Definition.Sources);
            Assert.All(rule.Definition.Sources, s => Assert.StartsWith("https://github.com/", s.Url));
            Assert.Equal("2026-10-11", rule.Definition.VerifiedOn);
        }
    }

    private static byte[] Mutate(Action<JsonObject> change)
    {
        var document = JsonNode.Parse(RuleRepository.ReadBundledBytes())!.AsObject();
        var rule = document["rules"]!.AsArray().Select(r => r!.AsObject()).First(r => (string?)r["id"] == "CP-HC-0001");
        change(rule);
        return System.Text.Encoding.UTF8.GetBytes(document.ToJsonString());
    }
}
