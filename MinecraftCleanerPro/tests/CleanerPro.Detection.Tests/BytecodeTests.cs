using CleanerPro.Detection.Bytecode;
using CleanerPro.Detection.Rules;
using CleanerPro.TestSupport;

namespace CleanerPro.Detection.Tests;

public sealed class BytecodeTests
{
    private static readonly CompiledRuleDatabase Database = RuleDatabaseLoader.Load(RuleRepository.ReadBundledBytes(), "windows").Database!;

    private static BytecodeSignatureMatcher Matcher() => new(Database.BytecodeSignatures);

    [Fact]
    public void ReaderDecodesMethodsAndSymbolicOperands()
    {
        var bytes = new ClassFileBuilder("a/B").Method("go", c => c
            .New("java/lang/String")
            .Invoke(0xB8, "java/lang/Class", "forName", "(Ljava/lang/String;)Ljava/lang/Class;")
            .Bipush(-5)
            .Op(0xB1)).Build();

        var method = Assert.Single(ClassFileReader.ReadMethods(bytes));
        Assert.Equal("go", method.Name);
        Assert.Equal(4, method.Instructions.Count);
        Assert.Equal("java/lang/String", method.Instructions[0].TypeName);
        Assert.Equal(("java/lang/Class", "forName"), (method.Instructions[1].Owner, method.Instructions[1].Name));
        Assert.Equal(-5, method.Instructions[2].IntOperand);
    }

    [Fact]
    public void ReaderHandlesSwitchesAndWideInstructions()
    {
        // iconst_0; tableswitch (padding to 4-byte boundary) default=0 low=0 high=1 offsets; wide iinc; return
        var bytes = new ClassFileBuilder().Method("s", c => c
            .Op(0x03)
            .Raw(0xAA, 0, 0, /* default */ 0, 0, 0, 0, /* low */ 0, 0, 0, 0, /* high */ 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0)
            .Raw(0xC4, 0x84, 0, 1, 0, 5)
            .Op(0xB1)).Build();
        var method = Assert.Single(ClassFileReader.ReadMethods(bytes));
        Assert.Equal(4, method.Instructions.Count);
        Assert.Equal(0xB1, method.Instructions[^1].Opcode);
    }

    [Theory]
    [InlineData(new byte[] { 0xCA, 0xFE })]
    [InlineData(new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 })]
    public void MalformedClassFilesThrowClassFormatException(byte[] bytes)
    {
        Assert.Throws<ClassFormatException>(() => ClassFileReader.ReadMethods(bytes));
    }

    [Fact]
    public void TruncatedCodeIsRejected()
    {
        var bytes = new ClassFileBuilder().Method("t", c => c.Raw(0x11, 0x01)).Build(); // sipush missing a byte
        Assert.Throws<ClassFormatException>(() => ClassFileReader.ReadMethods(bytes));
    }

    [Fact]
    public void FirstFractureiserSignatureIsDetected()
    {
        var hits = Matcher().Match(FractureiserFixtures.Sig1Class());
        Assert.Contains("CP-MAL-0001/sig1", hits);
    }

    [Fact]
    public void SecondSignatureMatchesFromAnyStart()
    {
        var bytes = new ClassFileBuilder().Method("x", FractureiserFixtures.Sig2).Build();
        Assert.Contains("CP-MAL-0001/sig2", Matcher().Match(bytes));
    }

    [Fact]
    public void ThirdSignatureMatchesTheAddressByteArray()
    {
        var bytes = new ClassFileBuilder().Method("x", FractureiserFixtures.Sig3).Build();
        Assert.Contains("CP-MAL-0001/sig3", Matcher().Match(bytes));
    }

    [Fact]
    public void OrderedFilterFailsWhenAnEarlierInstructionWithTheSameOpcodeDiffers()
    {
        // Same as nekodetector: the first NEW in the method must be java/lang/String.
        var bytes = new ClassFileBuilder().Method("x", c =>
        {
            c.New("java/lang/StringBuilder");
            FractureiserFixtures.Sig1(c);
        }).Build();
        Assert.DoesNotContain("CP-MAL-0001/sig1", Matcher().Match(bytes));
    }

    [Fact]
    public void PartialSequencesDoNotMatch()
    {
        var bytes = new ClassFileBuilder().Method("x", c => c
            .New("java/lang/String").Invoke(0xB7, "java/lang/String", "<init>", "([B)V")
            .Invoke(0xB8, "java/lang/Class", "forName", "(Ljava/lang/String;)Ljava/lang/Class;")
            .Op(0xB1)).Build();
        Assert.Empty(Matcher().Match(bytes));
    }

    [Fact]
    public void HarmlessClassesDoNotMatch()
    {
        Assert.Empty(Matcher().Match(FractureiserFixtures.HarmlessClass()));
    }

    [Fact]
    public void ContiguousSignaturesHaveARawBytePrefilter()
    {
        var sig3 = Database.BytecodeSignatures.Single(s => s.Key == "CP-MAL-0001/sig3");
        Assert.NotNull(sig3.RequiredRawBytes);
        Assert.Equal(new byte[] { 0x10, 56, 0x54, 0x59, 0x04 }, sig3.RequiredRawBytes![..5]);
    }
}
