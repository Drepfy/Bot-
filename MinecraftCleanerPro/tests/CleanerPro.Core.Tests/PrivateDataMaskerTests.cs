namespace CleanerPro.Core.Tests;

public sealed class PrivateDataMaskerTests
{
    private readonly PrivateDataMasker _masker = new(["Alex", "alex.smith", "DESKTOP-7Q2", null, " ", "x"]);

    [Fact]
    public void UserAndComputerNamesInPathsArePrivate()
    {
        var segments = _masker.Split(@"C:\Users\alex.smith\AppData\Roaming\.minecraft on DESKTOP-7Q2");

        Assert.Equal([@"C:\Users\", "alex.smith", @"\AppData\Roaming\.minecraft on ", "DESKTOP-7Q2"], segments.Select(s => s.Text));
        Assert.Equal([false, true, false, true], segments.Select(s => s.IsPrivate));
    }

    [Fact]
    public void JoiningTheSegmentsGivesTheOriginalText()
    {
        const string text = "Alex's game folder: D:\\Games\\Alex\\mods (alex)";
        Assert.Equal(text, string.Concat(_masker.Split(text).Select(s => s.Text)));
        Assert.Equal(3, _masker.Split(text).Count(s => s.IsPrivate));
    }

    [Theory]
    [InlineData(@"C:\Program Files\Alexandria\x.jar")]
    [InlineData("installation complete")]
    [InlineData("")]
    public void OnlyWholeWordsMatch(string text)
    {
        Assert.False(_masker.ContainsPrivateData(text));
    }

    [Fact]
    public void LongerValuesWinOverShorterOnes()
    {
        var masker = new PrivateDataMasker(["John", "John Smith"]);
        var segment = Assert.Single(masker.Split("John Smith"));
        Assert.True(segment.IsPrivate);
        Assert.Equal("John Smith", segment.Text);
    }

    [Fact]
    public void MaskReplacesPrivateValues()
    {
        Assert.Equal(@"C:\Users\████\Desktop", _masker.Mask(@"C:\Users\ALEX\Desktop"));
        Assert.Equal(string.Empty, _masker.Mask(null));
    }

    [Fact]
    public void ValuesShorterThanTwoCharactersAreIgnored()
    {
        Assert.False(_masker.ContainsPrivateData("x marks the spot"));
        Assert.False(new PrivateDataMasker([]).HasPrivateValues);
    }
}
