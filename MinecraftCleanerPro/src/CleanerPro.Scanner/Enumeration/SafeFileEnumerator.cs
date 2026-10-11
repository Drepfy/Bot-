using CleanerPro.Core;
using CleanerPro.Core.Models;

namespace CleanerPro.Scanner.Enumeration;

public sealed record EnumeratedItem(string Path, bool IsDirectory, long Size, DateTimeOffset LastWriteUtc, ScanRoot Root);

public sealed record EnumerationSettings
{
    public int MaxDepth { get; init; } = 24;

    public IReadOnlyList<string> ExcludedPaths { get; init; } = [];

    public IReadOnlyList<string> ExcludedDirectoryNames { get; init; } = [];

    public bool FollowDirectoryLinks { get; init; }

    /// <summary>When links are followed, their target must be inside one of these roots.</summary>
    public IReadOnlyList<string> LinkTargetRoots { get; init; } = [];
}

/// <summary>
/// Walks scan roots without following links or junctions (by default), honouring exclusions and depth
/// limits, and reporting every directory it could not read instead of failing the scan.
/// </summary>
public sealed class SafeFileEnumerator
{
    private static readonly EnumerationOptions ListingOptions = new()
    {
        RecurseSubdirectories = false,
        IgnoreInaccessible = false,
        AttributesToSkip = 0,
        ReturnSpecialDirectories = false,
        MatchType = MatchType.Simple,
    };

    private readonly EnumerationSettings _settings;
    private readonly Func<string, IEnumerable<FileSystemInfo>> _lister;
    private readonly List<string> _excludedPaths;

    public SafeFileEnumerator(EnumerationSettings settings, Func<string, IEnumerable<FileSystemInfo>>? lister = null)
    {
        _settings = settings;
        _lister = lister ?? (path => new DirectoryInfo(path).EnumerateFileSystemInfos("*", ListingOptions));
        _excludedPaths = settings.ExcludedPaths.Where(p => Path.IsPathFullyQualified(p)).Select(PathKey.NormalizeFullPath).ToList();
    }

    public IEnumerable<EnumeratedItem> Enumerate(ScanRoot root, Action<SkippedItem> onSkipped, Action onDirectoryVisited, CancellationToken cancellationToken)
    {
        string rootPath;
        try
        {
            rootPath = PathKey.NormalizeFullPath(root.Path);
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            onSkipped(new SkippedItem { Path = root.Path, Reason = SkipReason.Unreadable, Detail = ex.Message });
            yield break;
        }

        if (IsExcluded(rootPath))
        {
            onSkipped(new SkippedItem { Path = rootPath, Reason = SkipReason.Excluded, Detail = "The location is excluded in the configuration." });
            yield break;
        }

        if (root.IsFile)
        {
            var file = new FileInfo(rootPath);
            if (!TryRefresh(file, onSkipped))
            {
                yield break;
            }

            if (IsLink(file))
            {
                onSkipped(new SkippedItem { Path = rootPath, Reason = SkipReason.ReparsePoint, Detail = "Links are not followed." });
                yield break;
            }

            yield return new EnumeratedItem(rootPath, false, file.Length, file.LastWriteTimeUtc, root);
            yield break;
        }

        var rootInfo = new DirectoryInfo(rootPath);
        if (!rootInfo.Exists)
        {
            onSkipped(new SkippedItem { Path = rootPath, Reason = SkipReason.NotFound, Detail = "The directory does not exist." });
            yield break;
        }

        if (IsLink(rootInfo) && !LinkTargetAllowed(rootInfo))
        {
            onSkipped(new SkippedItem { Path = rootPath, Reason = SkipReason.ReparsePoint, Detail = "The scan location itself is a link or junction and was not followed." });
            yield break;
        }

        var maxDepth = root.MaxDepth is { } rootLimit ? Math.Min(rootLimit, _settings.MaxDepth) : _settings.MaxDepth;
        var stack = new Stack<(string Path, int Depth)>();
        stack.Push((rootPath, 0));
        while (stack.Count > 0)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var (directory, depth) = stack.Pop();
            onDirectoryVisited();

            List<FileSystemInfo> children;
            try
            {
                children = _lister(directory).ToList();
            }
            catch (UnauthorizedAccessException ex)
            {
                onSkipped(new SkippedItem { Path = directory, Reason = SkipReason.AccessDenied, Detail = ex.Message });
                continue;
            }
            catch (DirectoryNotFoundException ex)
            {
                onSkipped(new SkippedItem { Path = directory, Reason = SkipReason.NotFound, Detail = $"Removed during the scan: {ex.Message}" });
                continue;
            }
            catch (IOException ex)
            {
                onSkipped(new SkippedItem { Path = directory, Reason = SkipReason.Unreadable, Detail = ex.Message });
                continue;
            }

            // Sorted for deterministic results.
            children.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
            var subdirectories = new List<string>();
            foreach (var child in children)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var childPath = child.FullName;
                var isDirectory = child.Attributes.HasFlag(FileAttributes.Directory);

                if (IsLink(child) && !(isDirectory && LinkTargetAllowed(child)))
                {
                    onSkipped(new SkippedItem
                    {
                        Path = childPath,
                        Reason = SkipReason.ReparsePoint,
                        Detail = _settings.FollowDirectoryLinks
                            ? "Link target is outside the approved scan locations."
                            : "Symbolic links and junctions are not followed.",
                    });
                    continue;
                }

                if (isDirectory)
                {
                    if (IsExcluded(childPath) || _settings.ExcludedDirectoryNames.Contains(child.Name, StringComparer.OrdinalIgnoreCase))
                    {
                        onSkipped(new SkippedItem { Path = childPath, Reason = SkipReason.Excluded, Detail = "Excluded by configuration." });
                        continue;
                    }

                    yield return new EnumeratedItem(childPath, true, 0, SafeTime(child), root);
                    if (!root.Recursive)
                    {
                        continue;
                    }

                    if (depth + 1 > maxDepth)
                    {
                        if (root.MaxDepth is null)
                        {
                            onSkipped(new SkippedItem { Path = childPath, Reason = SkipReason.DepthLimit, Detail = $"Deeper than the {maxDepth}-level limit." });
                        }

                        continue; // Locations with their own shallow limit (for example Downloads) are not reported folder by folder.
                    }

                    subdirectories.Add(childPath);
                }
                else
                {
                    if (IsExcluded(childPath))
                    {
                        continue;
                    }

                    var length = child is FileInfo fileInfo ? SafeLength(fileInfo) : 0;
                    yield return new EnumeratedItem(childPath, false, length, SafeTime(child), root);
                }
            }

            for (var i = subdirectories.Count - 1; i >= 0; i--)
            {
                stack.Push((subdirectories[i], depth + 1));
            }
        }
    }

    private bool IsExcluded(string path) => _excludedPaths.Any(excluded => PathKey.IsSameOrWithin(path, excluded));

    private static bool IsLink(FileSystemInfo info)
    {
        try
        {
            return info.Attributes.HasFlag(FileAttributes.ReparsePoint) || info.LinkTarget is not null;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return true; // Treat unknown as a link so it is not followed.
        }
    }

    private bool LinkTargetAllowed(FileSystemInfo info)
    {
        if (!_settings.FollowDirectoryLinks)
        {
            return false;
        }

        try
        {
            var target = info.ResolveLinkTarget(returnFinalTarget: true);
            if (target is null)
            {
                return false;
            }

            var resolved = PathKey.NormalizeFullPath(target.FullName);
            return _settings.LinkTargetRoots.Any(root => PathKey.IsSameOrWithin(resolved, PathKey.NormalizeFullPath(root)));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static bool TryRefresh(FileInfo file, Action<SkippedItem> onSkipped)
    {
        try
        {
            file.Refresh();
            if (!file.Exists)
            {
                onSkipped(new SkippedItem { Path = file.FullName, Reason = SkipReason.NotFound });
                return false;
            }

            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            onSkipped(new SkippedItem { Path = file.FullName, Reason = SkipReason.AccessDenied, Detail = ex.Message });
            return false;
        }
    }

    private static long SafeLength(FileInfo file)
    {
        try
        {
            return file.Length;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return 0;
        }
    }

    private static DateTimeOffset SafeTime(FileSystemInfo info)
    {
        try
        {
            return info.LastWriteTimeUtc;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return DateTimeOffset.MinValue;
        }
    }
}
