using CleanerPro.Core.Models;
using CleanerPro.Detection.Matching;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure.Platform;

namespace CleanerPro.Detection.Tests;

/// <summary>Rule matching and evidence-based classification against the bundled rules, using synthetic observations.</summary>
public sealed class ClassificationTests
{
    private static readonly CompiledRuleDatabase Database = RuleDatabaseLoader.Load(RuleRepository.ReadBundledBytes(), "windows").Database!;
    private static readonly IReadOnlySet<DetectionCategory> All = Enum.GetValues<DetectionCategory>().ToHashSet();

    private static ItemObservation Jar(string name, Action<ArchiveObservation> fill, string? sha256 = null)
    {
        var archive = new ArchiveObservation();
        fill(archive);
        return new ItemObservation
        {
            Path = Path.Combine(Path.GetTempPath(), "mc", "mods", name),
            Name = name,
            Archive = archive,
            Sha256 = sha256 ?? new string('a', 64),
        };
    }

    private static void Mod(ArchiveObservation archive, string id, ModLoader loader = ModLoader.Fabric) =>
        archive.Mods.Add(new ModIdentity { Loader = loader, ModId = id, MetadataFile = "fabric.mod.json" });

    private static ClassificationOutcome Classify(ItemObservation observation, ClassifierOptions? options = null)
    {
        var evaluations = new RuleMatcher(Database).Evaluate(observation, All);
        return new FindingClassifier().Classify(observation, evaluations, options ?? new ClassifierOptions());
    }

    [Fact]
    public void ModIdAndPackageTogetherAreAKnownMatch()
    {
        var finding = Classify(Jar("client.jar", a =>
        {
            Mod(a, "wurst");
            a.AddEntry("net/wurstclient/WurstInitializer.class");
        })).Finding!;

        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Equal(DetectionConfidence.High, finding.Confidence);
        Assert.Equal(ThreatSeverity.Medium, finding.Severity);
        Assert.Equal(FileReputation.KnownCheat, finding.Reputation);
        Assert.Equal(RecommendedAction.Quarantine, finding.RecommendedAction);
        Assert.Contains(finding.RuleMatches, m => m.RuleId == "CP-HC-0001" && m.Sources.Count > 0);
        Assert.Contains(finding.Evidence, e => e.Kind == IndicatorType.ModId && e.MatchedValue == "wurst");
        Assert.Contains("CP-HC-0001", finding.ConfidenceRationale);
        Assert.Contains(finding.Limitations, l => l.Contains("cannot prove"));
    }

    [Fact]
    public void PackageAloneIsAHighConfidenceSuspicion()
    {
        var finding = Classify(Jar("renamed.jar", a => a.AddEntry("meteordevelopment/meteorclient/MeteorClient.class"))).Finding!;
        Assert.Equal(Classification.HighConfidenceSuspicion, finding.Classification);
    }

    [Fact]
    public void ModIdAloneOnlyNeedsReviewAndKeepsSeverityLow()
    {
        var finding = Classify(Jar("x.jar", a => Mod(a, "liquidbounce"))).Finding!;
        Assert.Equal(Classification.NeedsReview, finding.Classification);
        Assert.True(finding.Severity <= ThreatSeverity.Low);
        Assert.Equal(RecommendedAction.ManualReview, finding.RecommendedAction);
        Assert.Equal(DetectionConfidence.Low, finding.Confidence);
    }

    [Fact]
    public void AFileNameAloneNeverProducesAHighThreat()
    {
        var observation = new ItemObservation { Path = "/tmp/mods/wurst-client.jar", Name = "wurst-client.jar", Sha256 = new string('b', 64) };
        var finding = Classify(observation).Finding!;
        Assert.Equal(Classification.NeedsReview, finding.Classification);
        Assert.True(finding.Severity <= ThreatSeverity.Low);
        Assert.NotEqual(RecommendedAction.Quarantine, finding.RecommendedAction);
    }

    [Fact]
    public void UnknownFilesAreNotFindings()
    {
        var outcome = Classify(Jar("someothermod.jar", a =>
        {
            Mod(a, "someothermod");
            a.AddEntry("com/example/someothermod/Main.class");
        }));
        Assert.Null(outcome.Finding);
    }

    [Fact]
    public void LegitimatePerformanceModsAreNotFlagged()
    {
        var outcome = Classify(Jar("sodium-fabric.jar", a =>
        {
            Mod(a, "sodium");
            a.AddEntry("net/caffeinemc/mods/sodium/client/SodiumClientMod.class");
        }));
        Assert.Null(outcome.Finding); // Likely legitimate items are hidden unless the user asks to see them.
    }

    [Fact]
    public void LegitimateModsCanBeListedWhenRequested()
    {
        var finding = Classify(Jar("iris.jar", a =>
        {
            Mod(a, "iris");
            a.AddEntry("net/irisshaders/iris/Iris.class");
        }), new ClassifierOptions { ReportLikelyLegitimate = true }).Finding!;
        Assert.Equal(Classification.LikelyLegitimate, finding.Classification);
        Assert.Equal(RecommendedAction.NoAction, finding.RecommendedAction);
        Assert.Equal(ThreatSeverity.None, finding.Severity);
    }

    [Fact]
    public void LegitimacyEvidenceOverridesGenericHeuristics()
    {
        // A legitimate mod that happens to have module-like class names.
        var outcome = Classify(Jar("lithium.jar", a =>
        {
            Mod(a, "lithium");
            a.AddEntry("net/caffeinemc/mods/lithium/Lithium.class");
            a.AddEntry("net/caffeinemc/mods/lithium/features/Velocity.class");
            a.AddEntry("net/caffeinemc/mods/lithium/features/Reach.class");
        }));
        Assert.Null(outcome.Finding);
        Assert.True(outcome.SuppressedAsLegitimate);
    }

    [Fact]
    public void LegitimacyEvidenceNeverOverridesSpecificRules()
    {
        var finding = Classify(Jar("sodium.jar", a =>
        {
            Mod(a, "sodium");
            a.AddEntry("net/caffeinemc/mods/sodium/Fake.class");
            a.AddEntry("net/wurstclient/WurstInitializer.class");
            a.AddEntry("wurst.mixins.json");
        })).Finding!;
        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Contains(finding.Limitations, l => l.Contains("legitimate software"));
    }

    [Fact]
    public void GenericModuleLayoutNeedsSeveralDistinctModules()
    {
        Assert.Null(Classify(Jar("one.jar", a => a.AddEntry("com/x/modules/combat/KillAura.class"))).Finding);

        var finding = Classify(Jar("ghost.jar", a =>
        {
            a.AddEntry("com/x/modules/combat/KillAura.class");
            a.AddEntry("com/x/modules/combat/Velocity.class");
            a.AddEntry("com/x/modules/combat/AimAssist.class");
            a.AddEntry("com/x/modules/combat/Reach.class");
        })).Finding!;
        Assert.Equal(Classification.HighConfidenceSuspicion, finding.Classification);
        Assert.Contains(finding.RuleMatches, m => m.RuleId == "CP-HEUR-0001");
    }

    // Class layouts verified in the official repositories (see the rule sources), with the package roots replaced.
    [Theory]
    [InlineData("x/systems/modules/combat/KillAura.class", "x/systems/modules/combat/Velocity.class")]
    [InlineData("x/hacks/KillauraHack.class", "x/hacks/ReachHack.class")]
    [InlineData("x/module/mods/Killaura.class", "x/module/mods/Velocity.class")]
    [InlineData("x/features/modules/combat/Aura.class", "x/features/modules/combat/Velocity.class")]
    [InlineData("x/features/module/modules/combat/killaura/ModuleKillAura$Target.class", "x/features/module/modules/combat/velocity/ModuleVelocity.class")]
    public void ModulePatternsMatchTheVerifiedClientLayouts(string killAura, string second)
    {
        var observation = Jar("layout.jar", a =>
        {
            a.AddEntry(killAura);
            a.AddEntry(second);
        });
        var evaluation = Assert.Single(new RuleMatcher(Database).Evaluate(observation, All), e => e.Rule.Id == "CP-HEUR-0001");
        Assert.Equal(Classification.NeedsReview, evaluation.Level);
        Assert.Contains("killaura", evaluation.MatchedIndicatorIds);
    }

    [Fact]
    public void DuplicateRuleMatchesProduceOneFinding()
    {
        var outcome = Classify(Jar("bleach.jar", a =>
        {
            Mod(a, "bleachhack");
            a.AddEntry("org/bleachhack/BleachHack.class");
            a.AddEntry("bleachhack.mixins.json");
        }));
        var finding = outcome.Finding!;
        Assert.Single(finding.RuleMatches, m => m.RuleId == "CP-HC-0004");
        Assert.Equal(3, finding.Evidence.Count(e => e.RuleId == "CP-HC-0004"));
    }

    [Fact]
    public void BaritoneIsOnlyEverReportedForReview()
    {
        var finding = Classify(Jar("baritone.jar", a =>
        {
            Mod(a, "baritone");
            a.AddEntry("mixins.baritone.json");
        })).Finding!;
        Assert.Equal(Classification.NeedsReview, finding.Classification);
        Assert.Equal(DetectionCategory.GameplayAutomation, finding.RuleMatches.Single().Category);
    }

    [Fact]
    public void IncompleteInspectionTurnsWeakEvidenceIntoUnverified()
    {
        var observation = Jar("x.jar", a => Mod(a, "thunderhack"));
        observation.InspectionProblems.Add("The archive has more than 50000 entries.");
        var finding = Classify(observation).Finding!;
        Assert.Equal(Classification.Unverified, finding.Classification);
        Assert.Contains(finding.Limitations, l => l.Contains("could not be fully inspected"));
    }

    [Fact]
    public void TrustedExclusionsSuppressCheatsButNeverMalware()
    {
        var hash = new string('c', 64);
        var options = new ClassifierOptions { TrustedExclusions = [new TrustedExclusionEntry(hash, null, "reviewed")] };

        var cheat = Classify(Jar("w.jar", a =>
        {
            Mod(a, "wurst");
            a.AddEntry("net/wurstclient/A.class");
        }, hash), options);
        Assert.Null(cheat.Finding);
        Assert.True(cheat.SuppressedByTrustedExclusion);

        var malware = Jar("infected.jar", a => a.AddEntry("dev/neko/nekoclient/Client.class"), hash);
        Assert.Equal(Classification.KnownMatch, Classify(malware, options).Finding!.Classification);
    }

    [Fact]
    public void MalwareBytecodeHitIsVerifiedAndCritical()
    {
        var observation = Jar("infected.jar", a => a.BytecodeHits["CP-MAL-0001/sig1"] = "net/example/Main.class");
        var finding = Classify(observation).Finding!;
        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Equal(DetectionConfidence.Verified, finding.Confidence);
        Assert.Equal(ThreatSeverity.Critical, finding.Severity);
        Assert.Equal(FileReputation.KnownMalicious, finding.Reputation);
        Assert.Equal(RecommendedAction.QuarantineAndCheckSystem, finding.RecommendedAction);
    }

    [Fact]
    public void PublishedStage2HashIsAKnownMatch()
    {
        var observation = new ItemObservation { Path = "/tmp/lib.jar", Name = "lib.jar", Sha1 = "52d08736543a240b0cbbbf2da03691ae525bb119", Sha256 = new string('d', 64) };
        Assert.Equal(Classification.KnownMatch, Classify(observation).Finding!.Classification);
    }

    [Fact]
    public void HarmlessTestFileIsDetected()
    {
        var observation = new ItemObservation
        {
            Path = "/tmp/cleanerpro-harmless-test.txt",
            Name = "cleanerpro-harmless-test.txt",
            Sha256 = "6fab04ffb2267b6330c4551365755c5dbb072ba7bc0b98d14fde7dc6d27cacae",
        };
        var finding = Classify(observation).Finding!;
        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Equal(DetectionCategory.TestSignature, finding.RuleMatches.Single().Category);
    }

    [Fact]
    public void ConfigurationLeftoversUseRelativePaths()
    {
        var root = Path.Combine(Path.GetTempPath(), "mc");
        var observation = new ItemObservation
        {
            Path = Path.Combine(root, "wurst", "enabled-hacks.json"),
            Name = "enabled-hacks.json",
            InstallationRoot = root,
            RelativePath = "wurst/enabled-hacks.json",
            Sha256 = new string('e', 64),
        };
        var finding = Classify(observation).Finding!;
        Assert.Equal(Classification.KnownMatch, finding.Classification);
        Assert.Equal(ThreatSeverity.Low, finding.Severity);
    }

    [Fact]
    public void LeftoverFolderNamesOnlyCountAtTheInstallationRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), "mc");
        var atRoot = new ItemObservation { Path = Path.Combine(root, "meteor-client"), Name = "meteor-client", IsDirectory = true, InstallationRoot = root };
        var nested = new ItemObservation { Path = Path.Combine(root, "config", "meteor-client"), Name = "meteor-client", IsDirectory = true, InstallationRoot = root };
        Assert.Equal(Classification.NeedsReview, Classify(atRoot).Finding!.Classification);
        Assert.Null(Classify(nested).Finding);
    }

    [Fact]
    public void ValidSignatureCountsAsLegitimacyEvidenceAgainstHeuristics()
    {
        var observation = new ItemObservation
        {
            Path = "/tmp/meteor-client-installer.exe",
            Name = "meteor-client-installer.exe",
            Sha256 = new string('f', 64),
            Signature = new SignatureInfo(SignatureStatus.Valid, "CN=Example", "ok"),
        };
        var outcome = Classify(observation);
        Assert.Null(outcome.Finding);
        Assert.True(outcome.SuppressedAsLegitimate);
    }

    [Fact]
    public void DisabledCategoriesAreNotMatched()
    {
        var observation = Jar("w.jar", a =>
        {
            Mod(a, "wurst");
            a.AddEntry("net/wurstclient/A.class");
        });
        var enabled = All.Where(c => c != DetectionCategory.HackedClient).ToHashSet();
        Assert.Empty(new RuleMatcher(Database).Evaluate(observation, enabled));
    }

    [Fact]
    public void StartupEntriesAreReportedForManualReviewOnly()
    {
        var observation = new ItemObservation
        {
            Path = @"HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Microsoft Edge",
            Name = "Microsoft Edge",
            IsSystemArtifact = true,
            StartupEntry = new StartupEntry(@"HKCU\Run", "Microsoft Edge", @"javaw -jar C:\Users\x\AppData\Local\Microsoft Edge\libWebGL64.jar"),
        };
        var finding = Classify(observation).Finding!;
        Assert.Equal(Classification.HighConfidenceSuspicion, finding.Classification);
        Assert.Equal(RecommendedAction.ManualReview, finding.RecommendedAction);
    }

    [Fact]
    public void KnownLocationTemplatesExpandWithProvidedVariables()
    {
        var resolver = new LocationTemplateResolver(name => name == "LOCALAPPDATA" ? Path.Combine(Path.GetTempPath(), "local") : null);
        var expanded = resolver.Expand(@"%LOCALAPPDATA%\Microsoft Edge");
        Assert.Equal(Path.Combine(Path.GetTempPath(), "local", "Microsoft Edge"), expanded);
        Assert.Null(resolver.Expand(@"%UNKNOWNVAR%\x"));
    }
}
