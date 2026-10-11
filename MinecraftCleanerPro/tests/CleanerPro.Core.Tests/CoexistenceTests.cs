using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.TestSupport;

namespace CleanerPro.Core.Tests;

/// <summary>The application must not get in the way of other programs while it reads their files.</summary>
public sealed class CoexistenceTests : IDisposable
{
    private readonly TempDirectory _temp = new();

    public void Dispose() => _temp.Dispose();

    [Fact]
    public void OtherProgramsCanWriteAndDeleteAFileWhileItIsBeingRead()
    {
        var path = _temp.WriteText("launcher_profiles.json", "{ }");
        using var reading = SharedFile.OpenRead(path);

        // A launcher saving its settings at the same moment must succeed...
        using (var writer = new FileStream(path, FileMode.Open, FileAccess.Write, FileShare.ReadWrite | FileShare.Delete))
        {
            writer.Write("{ \"saved\": true }"u8);
        }

        // ...and so must deleting or replacing the file.
        File.Delete(path);
        Assert.False(File.Exists(path));
    }

    [Fact]
    public void HashingSharesTheFileWithWriters()
    {
        var path = _temp.WriteText("mods/a.jar", "content");
        using var writer = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite | FileShare.Delete);
        Assert.Equal(FileHasher.Sha256Hex("content"u8.ToArray()), FileHasher.Compute(path, false).Sha256);
    }

    [Fact]
    public void SharedReadsReturnTheTextAndLines()
    {
        var path = _temp.WriteText("instance.cfg", "name=PvP\r\nJvmArgs=-Xmx4G\n");
        Assert.Equal(["name=PvP", "JvmArgs=-Xmx4G", ""], SharedFile.ReadAllLines(path));
    }

    [Fact]
    public void RunningGamesAndLaunchersAreRecognisedByProcessName()
    {
        var running = RunningGameDetector.Describe(["explorer", "JAVAW", "PrismLauncher", "chrome"]);
        Assert.Equal(["javaw (Minecraft Java Edition or another Java program)", "Prism Launcher"], running);
        Assert.Contains("Close Minecraft", RunningGameDetector.Warning(running));
        Assert.Equal(string.Empty, RunningGameDetector.Warning([]));
        Assert.Empty(RunningGameDetector.Describe(["explorer", "notepad"]));
    }

    [Fact]
    public void ListingRunningProgramsNeverFails()
    {
        _ = RunningGameDetector.FindRunning(); // Read-only; must not throw even without permission to inspect other processes.
    }
}
