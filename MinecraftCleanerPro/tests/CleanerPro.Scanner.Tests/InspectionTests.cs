using System.IO.Compression;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Bytecode;
using CleanerPro.Detection.Rules;
using CleanerPro.Scanner.Inspection;
using CleanerPro.TestSupport;

namespace CleanerPro.Scanner.Tests;

public sealed class InspectionTests
{
    private static readonly CompiledRuleDatabase Database = RuleDatabaseLoader.Load(RuleRepository.ReadBundledBytes(), "windows").Database!;

    private static ArchiveInspector Inspector(ArchiveInspectionOptions? options = null) =>
        new(options ?? new ArchiveInspectionOptions(), new BytecodeSignatureMatcher(Database.BytecodeSignatures), new MemoryBudget(64L * 1024 * 1024));

    [Fact]
    public void FabricMetadataIsParsed()
    {
        var mod = ModMetadataParser.ParseFabric("""{ "schemaVersion": 1, "id": "wurst", "name": "Wurst Client", "version": "7.0", /* comment */ }""", "fabric.mod.json", out var problem);
        Assert.Null(problem);
        Assert.Equal(("wurst", "Wurst Client", ModLoader.Fabric), (mod!.ModId, mod.Name, mod.Loader));
    }

    [Fact]
    public void MalformedMetadataIsReportedNotGuessed()
    {
        Assert.Null(ModMetadataParser.ParseFabric("{ id: ", "fabric.mod.json", out var problem));
        Assert.Contains("could not be parsed", problem);
    }

    [Fact]
    public void QuiltForgeAndLegacyMetadataAreParsed()
    {
        var quilt = ModMetadataParser.ParseQuilt("""{ "quilt_loader": { "id": "q", "version": "1", "metadata": { "name": "Q" } } }""", "quilt.mod.json", out _);
        Assert.Equal(("q", "Q", ModLoader.Quilt), (quilt!.ModId, quilt.Name, quilt.Loader));

        var toml = """
            modLoader="javafml"
            [[mods]] # comment
            modId="examplemod"
            displayName="Example Mod"
            version="1.2"
            [[dependencies.examplemod]]
            modId="forge"
            """;
        var forge = Assert.Single(ModMetadataParser.ParseModsToml(toml, "META-INF/mods.toml", ModLoader.Forge));
        Assert.Equal(("examplemod", "Example Mod", "1.2"), (forge.ModId, forge.Name, forge.Version));

        var legacy = ModMetadataParser.ParseMcmodInfo("""{ "modList": [ { "modid": "old", "name": "Old" } ] }""", "mcmod.info", out _);
        Assert.Equal("old", Assert.Single(legacy).ModId);
    }

    [Fact]
    public void ManifestMainSectionIsParsedWithContinuationLines()
    {
        var attributes = ModMetadataParser.ParseManifest("Manifest-Version: 1.0\r\nMain-Class: net.example.Very\r\n LongName\r\n\r\nName: x\r\nIgnored: yes\r\n");
        Assert.Equal("net.example.VeryLongName", attributes["Main-Class"]);
        Assert.False(attributes.ContainsKey("Ignored"));
    }

    [Fact]
    public void ArchiveEntriesPackagesAndModsAreCollected()
    {
        var bytes = new JarBuilder().FabricMod("meteor-client").EmptyClasses("meteordevelopment/meteorclient/MeteorClient.class").Text("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n").Build();
        var problems = new List<string>();
        var archive = Inspector().Inspect(new MemoryStream(bytes), problems, CancellationToken.None)!;

        Assert.Contains("meteordevelopment/meteorclient/", archive.ClassPackages);
        Assert.Contains("meteordevelopment/", archive.ClassPackages);
        Assert.Equal("meteor-client", Assert.Single(archive.Mods).ModId);
        Assert.Equal(1, archive.ClassCount);
        Assert.Equal(1, archive.ClassFilesInspected); // the empty fixture is ruled out by the signature pre-filter
        Assert.Equal(0, archive.ClassFilesUnparseable);
        Assert.Empty(problems);
    }

    [Fact]
    public void NestedJarsAreMergedIntoTheOuterFile()
    {
        var inner = new JarBuilder().FabricMod("liquidbounce").EmptyClasses("net/ccbluex/liquidbounce/LiquidBounce.class");
        var outer = new JarBuilder().FabricMod("innocent").Nested("META-INF/jars/inner.jar", inner).Build();
        var archive = Inspector().Inspect(new MemoryStream(outer), [], CancellationToken.None)!;

        Assert.Contains(archive.Mods, m => m.ModId == "liquidbounce" && m.MetadataFile!.StartsWith("META-INF/jars/inner.jar!/", StringComparison.Ordinal));
        Assert.Contains("net/ccbluex/liquidbounce/", archive.ClassPackages);
        Assert.Contains("META-INF/jars/inner.jar", archive.NestedArchives);
    }

    [Fact]
    public void NestingDepthIsLimited()
    {
        var level3 = new JarBuilder().FabricMod("deep");
        var level2 = new JarBuilder().Nested("META-INF/jars/l3.jar", level3);
        var level1 = new JarBuilder().Nested("META-INF/jars/l2.jar", level2).Build();
        var archive = Inspector(new ArchiveInspectionOptions { MaxNestedDepth = 1 }).Inspect(new MemoryStream(level1), [], CancellationToken.None)!;
        Assert.DoesNotContain(archive.Mods, m => m.ModId == "deep");
    }

    [Fact]
    public void BytecodeSignaturesInsideArchivesAreFound()
    {
        var bytes = new JarBuilder().FabricMod("somemod").Bytes("net/example/InfectedMain.class", FractureiserFixtures.Sig1Class()).Build();
        var archive = Inspector().Inspect(new MemoryStream(bytes), [], CancellationToken.None)!;
        Assert.Equal("net/example/InfectedMain.class", archive.BytecodeHits["CP-MAL-0001/sig1"]);
        Assert.Equal(1, archive.ClassFilesInspected);
    }

    [Fact]
    public void BytecodeInspectionCanBeDisabled()
    {
        var bytes = new JarBuilder().Bytes("a/B.class", FractureiserFixtures.Sig1Class()).Build();
        var archive = Inspector(new ArchiveInspectionOptions { InspectBytecode = false }).Inspect(new MemoryStream(bytes), [], CancellationToken.None)!;
        Assert.Empty(archive.BytecodeHits);
    }

    [Fact]
    public void CorruptArchivesAreReported()
    {
        var problems = new List<string>();
        var result = Inspector().Inspect(new MemoryStream("PK\u0003\u0004 definitely not a zip"u8.ToArray()), problems, CancellationToken.None);
        Assert.Null(result);
        Assert.Contains(problems, p => p.Contains("not a readable ZIP"));
    }

    [Fact]
    public void EntryCountLimitIsEnforced()
    {
        var builder = new JarBuilder();
        for (var i = 0; i < 150; i++)
        {
            builder.Text($"file{i}.txt", "x");
        }

        var problems = new List<string>();
        var archive = Inspector(new ArchiveInspectionOptions { MaxEntries = 100 }).Inspect(new MemoryStream(builder.Build()), problems, CancellationToken.None)!;
        Assert.Equal(100, archive.EntryCount);
        Assert.Contains(problems, p => p.Contains("more than 100 entries"));
    }

    [Fact]
    public void HighlyCompressedEntriesAreNotExpanded()
    {
        // 8 MB of zeros compresses roughly 1000:1, which is treated as a potential archive bomb.
        var bytes = new JarBuilder().Bytes("fabric.mod.json", new byte[8 * 1024 * 1024]).Build();
        var problems = new List<string>();
        var archive = Inspector(new ArchiveInspectionOptions { MaxCompressionRatio = 100 }).Inspect(new MemoryStream(bytes), problems, CancellationToken.None)!;
        Assert.Empty(archive.Mods);
        Assert.Contains(problems, p => p.Contains("too large") || p.Contains("compression ratio"));
    }

    [Fact]
    public void TotalUncompressedSizeIsBounded()
    {
        var builder = new JarBuilder();
        var random = new Random(1);
        for (var i = 0; i < 4; i++)
        {
            var data = new byte[300_000];
            random.NextBytes(data);
            builder.Bytes($"META-INF/jars/n{i}.jar", data);
        }

        var problems = new List<string>();
        Inspector(new ArchiveInspectionOptions { MaxTotalUncompressedBytes = 500_000 }).Inspect(new MemoryStream(builder.Build()), problems, CancellationToken.None);
        Assert.Contains(problems, p => p.Contains("total uncompressed size"));
    }

    [Fact]
    public void MemoryBudgetRefusesImpossibleRequestsAndReleasesLeases()
    {
        var budget = new MemoryBudget(100);
        Assert.Null(budget.Acquire(101, CancellationToken.None));
        using (budget.Acquire(60, CancellationToken.None))
        {
            Assert.Equal(60, budget.InUse);
        }

        Assert.Equal(0, budget.InUse);
    }

    [Fact]
    public void ZipEntryNamesWithTraversalAreTreatedAsPlainStrings()
    {
        using var memory = new MemoryStream();
        using (var zip = new ZipArchive(memory, ZipArchiveMode.Create, leaveOpen: true))
        {
            using var stream = zip.CreateEntry("../../evil.txt").Open();
            stream.Write("x"u8);
        }

        var archive = Inspector().Inspect(new MemoryStream(memory.ToArray()), [], CancellationToken.None)!;
        Assert.Contains("../../evil.txt", archive.Entries); // recorded, never extracted
    }
}
