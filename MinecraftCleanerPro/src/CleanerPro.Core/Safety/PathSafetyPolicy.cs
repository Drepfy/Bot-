using System.Text.RegularExpressions;

namespace CleanerPro.Core.Safety;

/// <summary>
/// The single safety policy every filesystem modification must pass. It cannot be disabled through
/// configuration. Protected locations always win over approved scan roots, so adding a drive root as a
/// custom scan directory never makes system files eligible for cleanup.
/// </summary>
public sealed partial class PathSafetyPolicy
{
    private static readonly string[] ReservedDeviceNames =
    [
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    ];

    private static readonly string[] ProtectedExtensions = [".sys", ".drv", ".efi", ".mui", ".cat"];

    private readonly List<string> _protectedRoots;
    private readonly List<string> _protectedExactPaths;
    private readonly bool _windowsRules;
    private readonly StringComparison _comparison;

    public PathSafetyPolicy(
        IEnumerable<string> protectedRoots,
        IEnumerable<string> protectedExactPaths,
        bool applyWindowsPathRules,
        bool caseInsensitive)
    {
        _windowsRules = applyWindowsPathRules;
        _comparison = caseInsensitive ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        _protectedRoots = protectedRoots.Where(p => !string.IsNullOrWhiteSpace(p)).Select(SafeNormalize).Distinct().ToList();
        _protectedExactPaths = protectedExactPaths.Where(p => !string.IsNullOrWhiteSpace(p)).Select(SafeNormalize).Distinct().ToList();
    }

    public IReadOnlyList<string> ProtectedRoots => _protectedRoots;

    public IReadOnlyList<string> ProtectedExactPaths => _protectedExactPaths;

    /// <summary>Builds the policy for the operating system the application is running on.</summary>
    public static PathSafetyPolicy ForCurrentSystem(IEnumerable<string>? additionalProtectedRoots = null)
    {
        var roots = new List<string>();
        var exact = new List<string>();

        if (OperatingSystem.IsWindows())
        {
            AddFolder(roots, Environment.SpecialFolder.Windows);
            AddFolder(roots, Environment.SpecialFolder.System);
            AddFolder(roots, Environment.SpecialFolder.SystemX86);
            AddFolder(roots, Environment.SpecialFolder.ProgramFiles);
            AddFolder(roots, Environment.SpecialFolder.ProgramFilesX86);
            AddFolder(roots, Environment.SpecialFolder.CommonProgramFiles);
            AddFolder(roots, Environment.SpecialFolder.CommonProgramFilesX86);

            var programData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
            if (!string.IsNullOrEmpty(programData))
            {
                roots.Add(Path.Combine(programData, "Microsoft"));
            }

            var systemDrive = Environment.GetEnvironmentVariable("SystemDrive");
            if (!string.IsNullOrEmpty(systemDrive))
            {
                var driveRoot = systemDrive.TrimEnd('\\') + "\\";
                roots.Add(Path.Combine(driveRoot, "Recovery"));
                roots.Add(Path.Combine(driveRoot, "$Recycle.Bin"));
                roots.Add(Path.Combine(driveRoot, "System Volume Information"));
                roots.Add(Path.Combine(driveRoot, "Boot"));
                roots.Add(Path.Combine(driveRoot, "EFI"));
            }

            var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            AddFolder(exact, Environment.SpecialFolder.UserProfile);
            AddFolder(exact, Environment.SpecialFolder.ApplicationData);
            AddFolder(exact, Environment.SpecialFolder.LocalApplicationData);
            AddFolder(exact, Environment.SpecialFolder.Desktop);
            AddFolder(exact, Environment.SpecialFolder.MyDocuments);
            AddFolder(exact, Environment.SpecialFolder.StartMenu);
            AddFolder(exact, Environment.SpecialFolder.Startup);
            if (!string.IsNullOrEmpty(profile))
            {
                exact.Add(Path.Combine(profile, "AppData"));
                exact.Add(Path.Combine(profile, "AppData", "LocalLow"));
                exact.Add(Path.Combine(profile, "Downloads"));
            }
        }
        else
        {
            roots.AddRange(["/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/proc", "/run", "/sbin", "/sys", "/usr", "/var/lib", "/snap"]);
            exact.AddRange(["/home", "/tmp", "/var", "/opt", "/mnt", "/media"]);
            AddFolder(exact, Environment.SpecialFolder.UserProfile);
        }

        try
        {
            foreach (var drive in DriveInfo.GetDrives())
            {
                exact.Add(drive.Name);
            }
        }
        catch (IOException)
        {
            // Drive enumeration is best-effort; the root check below still applies.
        }
        catch (UnauthorizedAccessException)
        {
        }

        if (Environment.ProcessPath is { } processPath)
        {
            exact.Add(processPath);
        }

        if (additionalProtectedRoots is not null)
        {
            roots.AddRange(additionalProtectedRoots);
        }

        return new PathSafetyPolicy(roots, exact, OperatingSystem.IsWindows(), PathKey.IsCaseInsensitivePlatform);
    }

    /// <summary>Validates a file or directory that the user approved for quarantine.</summary>
    public PathValidationResult ValidateCleanupTarget(string path, IEnumerable<string> approvedRoots, PathTargetKind kind)
    {
        var syntax = ValidateSyntax(path);
        if (!syntax.IsAllowed)
        {
            return syntax;
        }

        var normalized = syntax.NormalizedPath!;
        var location = ValidateLocation(normalized, approvedRoots, allowRootItself: false);
        if (!location.IsAllowed)
        {
            return location;
        }

        if (kind == PathTargetKind.File && ProtectedExtensions.Any(e => normalized.EndsWith(e, StringComparison.OrdinalIgnoreCase)))
        {
            return PathValidationResult.Blocked(PathBlockCode.ProtectedFileType,
                "This file type (drivers and operating-system components) is never modified by Minecraft Cleaner Pro.", normalized);
        }

        FileAttributes attributes;
        try
        {
            attributes = File.GetAttributes(normalized);
        }
        catch (Exception ex) when (ex is FileNotFoundException or DirectoryNotFoundException)
        {
            return PathValidationResult.Blocked(PathBlockCode.NotFound, "The item no longer exists at this location.", normalized);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return PathValidationResult.Blocked(PathBlockCode.NotFound, $"The item could not be inspected: {ex.Message}", normalized);
        }

        var isDirectory = attributes.HasFlag(FileAttributes.Directory);
        if (kind == PathTargetKind.File && isDirectory)
        {
            return PathValidationResult.Blocked(PathBlockCode.WrongType, "Expected a file but found a directory.", normalized);
        }

        if (kind == PathTargetKind.Directory && !isDirectory)
        {
            return PathValidationResult.Blocked(PathBlockCode.WrongType, "Expected a directory but found a file.", normalized);
        }

        return CheckReparsePoints(normalized, location.NormalizedPath!) ?? PathValidationResult.Allowed(normalized);
    }

    /// <summary>
    /// Validates where a quarantined file would be restored. The destination does not need to exist,
    /// but it must be inside an approved root and every existing ancestor must be a real directory.
    /// </summary>
    public PathValidationResult ValidateRestoreDestination(string path, IEnumerable<string> approvedRoots)
    {
        var syntax = ValidateSyntax(path);
        if (!syntax.IsAllowed)
        {
            return syntax;
        }

        var normalized = syntax.NormalizedPath!;
        var location = ValidateLocation(normalized, approvedRoots, allowRootItself: false);
        if (!location.IsAllowed)
        {
            return location;
        }

        if (ProtectedExtensions.Any(e => normalized.EndsWith(e, StringComparison.OrdinalIgnoreCase)))
        {
            return PathValidationResult.Blocked(PathBlockCode.ProtectedFileType, "Restoring this file type is not permitted.", normalized);
        }

        return CheckReparsePoints(normalized, location.NormalizedPath!) ?? PathValidationResult.Allowed(normalized);
    }

    /// <summary>Validates a directory the user wants to add to the scan scope (read-only use).</summary>
    public PathValidationResult ValidateScanRoot(string path)
    {
        var syntax = ValidateSyntax(path);
        if (!syntax.IsAllowed)
        {
            return syntax;
        }

        if (!Directory.Exists(syntax.NormalizedPath))
        {
            return PathValidationResult.Blocked(PathBlockCode.NotFound, "The directory does not exist.", syntax.NormalizedPath);
        }

        return syntax;
    }

    /// <summary>Checks that apply to every path regardless of intent.</summary>
    public PathValidationResult ValidateSyntax(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return PathValidationResult.Blocked(PathBlockCode.Empty, "No path was provided.");
        }

        if (path.Any(char.IsControl) || path.IndexOfAny(Path.GetInvalidPathChars()) >= 0 || path.Contains('"') || path.Contains('<') || path.Contains('>') || path.Contains('|'))
        {
            return PathValidationResult.Blocked(PathBlockCode.InvalidCharacters, "The path contains characters that are not allowed.");
        }

        // Windows prefix tricks (\\?\ etc.) are checked first so they are reported precisely.
        if (_windowsRules)
        {
            var windowsResult = ValidateWindowsSyntax(path);
            if (windowsResult is not null)
            {
                return windowsResult;
            }
        }

        if (path.Contains('*') || path.Contains('?'))
        {
            return PathValidationResult.Blocked(PathBlockCode.Wildcard, "Wildcards are never accepted; every target must be an exact path.");
        }

        if (!Path.IsPathFullyQualified(path))
        {
            return PathValidationResult.Blocked(PathBlockCode.NotFullyQualified, "Only absolute (fully qualified) paths are accepted.");
        }

        string full;
        try
        {
            full = PathKey.TrimTrailingSeparators(Path.GetFullPath(path));
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return PathValidationResult.Blocked(PathBlockCode.InvalidCharacters, $"The path is not valid: {ex.Message}");
        }

        var original = PathKey.TrimTrailingSeparators(path.Replace(Path.AltDirectorySeparatorChar, Path.DirectorySeparatorChar));
        if (!string.Equals(full, original, _comparison))
        {
            return PathValidationResult.Blocked(PathBlockCode.RelativeSegments,
                "The path contains relative segments (such as '..') or redundant separators and was rejected to prevent path substitution.", full);
        }

        return PathValidationResult.Allowed(full);
    }

    private PathValidationResult? ValidateWindowsSyntax(string path)
    {
        if (path.StartsWith(@"\\?\", StringComparison.Ordinal) || path.StartsWith(@"\\.\", StringComparison.Ordinal) ||
            path.StartsWith(@"\??\", StringComparison.Ordinal) || path.StartsWith("//?/", StringComparison.Ordinal) ||
            path.StartsWith("//./", StringComparison.Ordinal))
        {
            return PathValidationResult.Blocked(PathBlockCode.DevicePath, "Device and extended-length path prefixes are not accepted.");
        }

        if (path.StartsWith(@"\\", StringComparison.Ordinal) || path.StartsWith("//", StringComparison.Ordinal))
        {
            return PathValidationResult.Blocked(PathBlockCode.NetworkPath, "Network (UNC) paths are not modified by Minecraft Cleaner Pro.");
        }

        // A colon is only valid as the drive-letter separator ("C:"). Anything else is an NTFS alternate data stream.
        var colon = path.IndexOf(':');
        if (colon >= 0 && (colon != 1 || path.IndexOf(':', 2) >= 0))
        {
            return PathValidationResult.Blocked(PathBlockCode.AlternateDataStream, "Alternate data streams and unusual drive specifiers are not accepted.");
        }

        var segments = path.Split(['\\', '/'], StringSplitOptions.RemoveEmptyEntries);
        foreach (var segment in segments.Skip(1))
        {
            if (segment is "." or "..")
            {
                continue; // Reported as RelativeSegments after normalization.
            }

            if (segment.EndsWith('.') || segment.EndsWith(' '))
            {
                return PathValidationResult.Blocked(PathBlockCode.TrailingDotOrSpace,
                    "Path segments ending with a dot or space are silently rewritten by Windows and were rejected.");
            }

            var baseName = segment.Split('.')[0].TrimEnd();
            if (ReservedDeviceNames.Contains(baseName, StringComparer.OrdinalIgnoreCase))
            {
                return PathValidationResult.Blocked(PathBlockCode.ReservedDeviceName, $"'{segment}' is a reserved Windows device name.");
            }

            if (ShortNameAlias().IsMatch(segment))
            {
                return PathValidationResult.Blocked(PathBlockCode.ShortNameAlias,
                    "8.3 short-name aliases (such as PROGRA~1) are rejected because they can disguise the real target. Use the full path.");
            }
        }

        return null;
    }

    private PathValidationResult ValidateLocation(string normalized, IEnumerable<string> approvedRoots, bool allowRootItself)
    {
        foreach (var root in _protectedRoots)
        {
            if (PathKey.IsSameOrWithin(normalized, root, _comparison))
            {
                return PathValidationResult.Blocked(PathBlockCode.ProtectedLocation,
                    $"'{normalized}' is inside a protected system location ({root}). Cleanup is never performed there.", normalized);
            }
        }

        foreach (var exact in _protectedExactPaths)
        {
            if (string.Equals(normalized, exact, _comparison))
            {
                return PathValidationResult.Blocked(PathBlockCode.ProtectedPath,
                    $"'{normalized}' is a protected folder and cannot be modified as a whole.", normalized);
            }
        }

        string? matchedRoot = null;
        foreach (var root in approvedRoots)
        {
            if (string.IsNullOrWhiteSpace(root) || !Path.IsPathFullyQualified(root))
            {
                continue;
            }

            var normalizedRoot = SafeNormalize(root);
            if (!PathKey.IsSameOrWithin(normalized, normalizedRoot, _comparison))
            {
                continue;
            }

            if (!allowRootItself && string.Equals(normalized, normalizedRoot, _comparison))
            {
                return PathValidationResult.Blocked(PathBlockCode.IsApprovedRoot,
                    "The selected item is an entire scan location (for example a whole Minecraft installation). Only individual findings can be cleaned.", normalized);
            }

            // Prefer the most specific root so reparse checks cover the shortest necessary chain.
            if (matchedRoot is null || normalizedRoot.Length > matchedRoot.Length)
            {
                matchedRoot = normalizedRoot;
            }
        }

        return matchedRoot is null
            ? PathValidationResult.Blocked(PathBlockCode.OutsideApprovedScope,
                "The item is outside the approved scan scope, so it cannot be modified.", normalized)
            : PathValidationResult.Allowed(matchedRoot);
    }

    /// <summary>Rejects the target if it, or any existing ancestor down from the approved root, is a link or junction.</summary>
    private static PathValidationResult? CheckReparsePoints(string target, string approvedRoot)
    {
        var current = target;
        while (true)
        {
            try
            {
                if (File.Exists(current) || Directory.Exists(current))
                {
                    var info = new FileInfo(current);
                    if (info.Attributes.HasFlag(FileAttributes.ReparsePoint) || info.LinkTarget is not null)
                    {
                        return PathValidationResult.Blocked(PathBlockCode.ReparsePoint,
                            $"'{current}' is a symbolic link, junction or other reparse point. Links are never followed during cleanup.", target);
                    }
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                return PathValidationResult.Blocked(PathBlockCode.ReparsePoint, $"Could not verify '{current}' is not a link: {ex.Message}", target);
            }

            if (string.Equals(PathKey.TrimTrailingSeparators(current), PathKey.TrimTrailingSeparators(approvedRoot), PathKey.Comparison))
            {
                return null;
            }

            var parent = Path.GetDirectoryName(current);
            if (string.IsNullOrEmpty(parent) || parent.Length >= current.Length)
            {
                return null;
            }

            current = parent;
        }
    }

    private static void AddFolder(List<string> list, Environment.SpecialFolder folder)
    {
        var path = Environment.GetFolderPath(folder, Environment.SpecialFolderOption.DoNotVerify);
        if (!string.IsNullOrEmpty(path))
        {
            list.Add(path);
        }
    }

    private static string SafeNormalize(string path)
    {
        try
        {
            return Path.IsPathFullyQualified(path) ? PathKey.NormalizeFullPath(path) : path;
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return path;
        }
    }

    [GeneratedRegex(@"^[^~]{1,6}~\d+(\.[^.]{0,3})?$")]
    private static partial Regex ShortNameAlias();
}
