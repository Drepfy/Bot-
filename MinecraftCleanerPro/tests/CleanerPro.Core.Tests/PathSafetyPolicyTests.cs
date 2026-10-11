using CleanerPro.Core;
using CleanerPro.Core.Safety;
using CleanerPro.TestSupport;

namespace CleanerPro.Core.Tests;

public sealed class PathSafetyPolicyTests : IDisposable
{
    private readonly TempDirectory _temp = new();

    public void Dispose() => _temp.Dispose();

    [Fact]
    public void AllowsAFileInsideTheApprovedScope()
    {
        var root = _temp.CreateDirectory("game");
        var file = _temp.WriteText("game/mods/cheat.jar", "x");
        var result = TestPolicies.Create().ValidateCleanupTarget(file, [root], PathTargetKind.File);
        Assert.True(result.IsAllowed, result.Reason);
    }

    [Fact]
    public void RejectsFilesOutsideTheApprovedScope()
    {
        var root = _temp.CreateDirectory("game");
        var outside = _temp.WriteText("other/file.jar", "x");
        var result = TestPolicies.Create().ValidateCleanupTarget(outside, [root], PathTargetKind.File);
        Assert.False(result.IsAllowed);
        Assert.Equal(PathBlockCode.OutsideApprovedScope, result.Code);
    }

    [Fact]
    public void RejectsSiblingFolderWithCommonPrefix()
    {
        var root = _temp.CreateDirectory("game");
        var sibling = _temp.WriteText("game-backup/file.jar", "x");
        var result = TestPolicies.Create().ValidateCleanupTarget(sibling, [root], PathTargetKind.File);
        Assert.Equal(PathBlockCode.OutsideApprovedScope, result.Code);
    }

    [Fact]
    public void RejectsTheApprovedRootItself()
    {
        var root = _temp.CreateDirectory("game");
        var result = TestPolicies.Create().ValidateCleanupTarget(root, [root], PathTargetKind.Directory);
        Assert.Equal(PathBlockCode.IsApprovedRoot, result.Code);
    }

    [Fact]
    public void ProtectedLocationsWinOverApprovedRoots()
    {
        var system = _temp.CreateDirectory("system");
        var file = _temp.WriteText("system/driver.jar", "x");
        // Even if the user approved the whole temp folder as a scan root, the protected folder stays blocked.
        var result = TestPolicies.Create(system).ValidateCleanupTarget(file, [_temp.Path], PathTargetKind.File);
        Assert.Equal(PathBlockCode.ProtectedLocation, result.Code);
    }

    [Fact]
    public void RejectsRelativeSegments()
    {
        var root = _temp.CreateDirectory("game");
        _temp.WriteText("outside.jar", "x");
        var sneaky = Path.Combine(root, "..", "outside.jar");
        var result = TestPolicies.Create().ValidateCleanupTarget(sneaky, [root], PathTargetKind.File);
        Assert.Equal(PathBlockCode.RelativeSegments, result.Code);
    }

    [Theory]
    [InlineData("*.jar")]
    [InlineData("mods?.jar")]
    public void RejectsWildcards(string name)
    {
        var root = _temp.CreateDirectory("game");
        var result = TestPolicies.Create().ValidateCleanupTarget(Path.Combine(root, name), [root], PathTargetKind.File);
        Assert.Equal(PathBlockCode.Wildcard, result.Code);
    }

    [Fact]
    public void RejectsRelativePaths()
    {
        var result = TestPolicies.Create().ValidateSyntax(Path.Combine("mods", "file.jar"));
        Assert.Equal(PathBlockCode.NotFullyQualified, result.Code);
    }

    [Fact]
    public void RejectsEmptyPaths()
    {
        Assert.Equal(PathBlockCode.Empty, TestPolicies.Create().ValidateSyntax("  ").Code);
    }

    [Fact]
    public void RejectsDriverFileTypes()
    {
        var root = _temp.CreateDirectory("game");
        var file = _temp.WriteText("game/mods/evil.sys", "x");
        Assert.Equal(PathBlockCode.ProtectedFileType, TestPolicies.Create().ValidateCleanupTarget(file, [root], PathTargetKind.File).Code);
    }

    [Fact]
    public void RejectsMissingFilesAndWrongTypes()
    {
        var root = _temp.CreateDirectory("game");
        var dir = _temp.CreateDirectory("game", "folder");
        var policy = TestPolicies.Create();
        Assert.Equal(PathBlockCode.NotFound, policy.ValidateCleanupTarget(Path.Combine(root, "missing.jar"), [root], PathTargetKind.File).Code);
        Assert.Equal(PathBlockCode.WrongType, policy.ValidateCleanupTarget(dir, [root], PathTargetKind.File).Code);
    }

    [Fact]
    public void RejectsSymbolicLinkTargets()
    {
        var root = _temp.CreateDirectory("game");
        var real = _temp.WriteText("elsewhere/real.jar", "x");
        var link = Path.Combine(root, "link.jar");
        if (!SymlinkSupport.TryCreateFileLink(link, real))
        {
            return; // Symbolic links are not permitted for this user (Windows without Developer Mode).
        }

        Assert.Equal(PathBlockCode.ReparsePoint, TestPolicies.Create().ValidateCleanupTarget(link, [root], PathTargetKind.File).Code);
    }

    [Fact]
    public void RejectsFilesBehindALinkedDirectory()
    {
        var root = _temp.CreateDirectory("game");
        var outside = _temp.CreateDirectory("outside");
        _temp.WriteText("outside/victim.jar", "x");
        var linkedDir = Path.Combine(root, "mods");
        if (!SymlinkSupport.TryCreateDirectoryLink(linkedDir, outside))
        {
            return;
        }

        var result = TestPolicies.Create().ValidateCleanupTarget(Path.Combine(linkedDir, "victim.jar"), [root], PathTargetKind.File);
        Assert.Equal(PathBlockCode.ReparsePoint, result.Code);
    }

    [Fact]
    public void RestoreDestinationsMustStayInScope()
    {
        var root = _temp.CreateDirectory("game");
        var policy = TestPolicies.Create();
        Assert.True(policy.ValidateRestoreDestination(Path.Combine(root, "mods", "new.jar"), [root]).IsAllowed);
        Assert.Equal(PathBlockCode.OutsideApprovedScope, policy.ValidateRestoreDestination(_temp.Combine("x.jar"), [root]).Code);
    }

    // Windows path rules are string checks, so they are verified on every platform.
    [Theory]
    [InlineData(@"\\?\C:\Games\mods\a.jar", PathBlockCode.DevicePath)]
    [InlineData(@"\\.\C:\Games\a.jar", PathBlockCode.DevicePath)]
    [InlineData(@"\\server\share\a.jar", PathBlockCode.NetworkPath)]
    [InlineData(@"C:\Games\mods\a.jar:hidden", PathBlockCode.AlternateDataStream)]
    [InlineData(@"C:\Games\mods.\a.jar", PathBlockCode.TrailingDotOrSpace)]
    [InlineData(@"C:\Games\mods \a.jar", PathBlockCode.TrailingDotOrSpace)]
    [InlineData(@"C:\Games\CON\a.jar", PathBlockCode.ReservedDeviceName)]
    [InlineData(@"C:\Games\nul.txt", PathBlockCode.ReservedDeviceName)]
    [InlineData(@"C:\PROGRA~1\a.jar", PathBlockCode.ShortNameAlias)]
    public void WindowsPathTricksAreRejected(string path, PathBlockCode expected)
    {
        var policy = new PathSafetyPolicy([], [], applyWindowsPathRules: true, caseInsensitive: true);
        Assert.Equal(expected, policy.ValidateSyntax(path).Code);
    }

    [WindowsFact]
    public void WindowsSystemFolderIsProtectedOnRealSystem()
    {
        var policy = PathSafetyPolicy.ForCurrentSystem();
        var system32 = Environment.GetFolderPath(Environment.SpecialFolder.System);
        var kernel = Path.Combine(system32, "kernel32.dll");
        var result = policy.ValidateCleanupTarget(kernel, [Path.GetPathRoot(system32)!], PathTargetKind.File);
        Assert.Equal(PathBlockCode.ProtectedLocation, result.Code);
    }

    [Fact]
    public void CurrentSystemPolicyProtectsTheUserProfileRoot()
    {
        var policy = PathSafetyPolicy.ForCurrentSystem();
        var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var result = policy.ValidateCleanupTarget(profile, [Path.GetPathRoot(profile)!], PathTargetKind.Directory);
        Assert.False(result.IsAllowed);
    }

    [Fact]
    public void PathKeyBoundaryChecks()
    {
        var a = _temp.Combine("a");
        Assert.True(PathKey.IsSameOrWithin(Path.Combine(a, "b"), a));
        Assert.True(PathKey.IsSameOrWithin(a, a));
        Assert.False(PathKey.IsSameOrWithin(a + "bc", a));
    }
}
