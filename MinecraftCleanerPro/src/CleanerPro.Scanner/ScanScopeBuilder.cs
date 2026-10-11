using CleanerPro.Configuration;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Matching;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure;

namespace CleanerPro.Scanner;

/// <summary>
/// Builds the explicit scope of a scan so it can be shown to the user before anything is read.
/// Drives are never scanned implicitly; only discovered installations, folders the user added and
/// documented system locations are included.
/// </summary>
public sealed class ScanScopeBuilder
{
    private readonly Func<AppConfiguration> _config;
    private readonly Func<CompiledRuleDatabase> _rules;
    private readonly AppPaths _paths;
    private readonly LocationTemplateResolver _resolver;

    public ScanScopeBuilder(Func<AppConfiguration> config, Func<CompiledRuleDatabase> rules, AppPaths paths, LocationTemplateResolver? resolver = null)
    {
        _config = config;
        _rules = rules;
        _paths = paths;
        _resolver = resolver ?? new LocationTemplateResolver();
    }

    public ScanScope Build(ScanMode mode, DiscoveryResult discovery, IReadOnlyList<string>? customRoots = null)
    {
        var config = _config();
        var roots = new List<ScanRoot>();

        if (mode == ScanMode.Custom)
        {
            foreach (var path in customRoots ?? [])
            {
                if (Path.IsPathFullyQualified(path) && Directory.Exists(path))
                {
                    var normalized = PathKey.NormalizeFullPath(path);
                    var installation = discovery.Installations.FirstOrDefault(i => PathKey.IsSameOrWithin(normalized, i.RootPath));
                    roots.Add(new ScanRoot
                    {
                        Path = normalized,
                        Kind = ScanRootKind.CustomDirectory,
                        Reason = "Selected by you for this custom scan",
                        InstallationId = installation?.Id,
                        InstallationName = installation?.Name,
                        InstallationRoot = installation?.RootPath,
                    });
                }
            }
        }
        else
        {
            foreach (var installation in SelectInstallations(discovery, config))
            {
                roots.AddRange(mode == ScanMode.Quick ? QuickRoots(installation) : [FullRoot(installation)]);
            }
        }

        var includeSystem = mode is ScanMode.Quick or ScanMode.Full && config.Scan.InspectSystemArtifacts;
        if (includeSystem)
        {
            var enabled = config.Detection.EnabledCategories.ToHashSet();
            var resolution = SystemArtifactResolver.Resolve(_rules(), _resolver, enabled);
            roots.AddRange(resolution.Roots);
        }

        var excluded = new List<string>(config.Scan.ExcludedDirectories.Where(Path.IsPathFullyQualified))
        {
            _paths.DataRoot,
            EffectiveLocations.QuarantineDirectory(config, _paths),
            EffectiveLocations.ReportsDirectory(config, _paths),
        };
        if (mode == ScanMode.Full)
        {
            foreach (var installation in SelectInstallations(discovery, config))
            {
                excluded.AddRange(installation.DefaultExcludedSubdirectories.Select(sub => Path.Combine(installation.RootPath, sub)));
            }
        }

        return new ScanScope
        {
            Mode = mode,
            Roots = Deduplicate(roots),
            ExcludedPaths = excluded.Distinct(PathKey.Comparer).ToList(),
            IncludeSystemArtifactChecks = includeSystem,
            IncludeStartupInspection = mode is ScanMode.Quick or ScanMode.Full && config.Scan.InspectStartupEntries && OperatingSystem.IsWindows(),
            IncludeProcessInspection = config.Scan.InspectRunningProcesses,
        };
    }

    /// <summary>Scope for a post-cleanup verification: the folders that contained the original findings.</summary>
    public ScanScope BuildVerification(ScanSession original)
    {
        var config = _config();
        var roots = new List<ScanRoot>();
        // System artifacts are re-checked through their documented locations below; startup entries are not files.
        foreach (var finding in original.Findings.Where(f => !f.IsSystemArtifact && Path.IsPathFullyQualified(f.Path)))
        {
            var directory = Path.GetDirectoryName(finding.Path);
            if (directory is null || !Directory.Exists(directory))
            {
                continue;
            }

            var originalRoot = original.Scope.Roots.FirstOrDefault(r => PathKey.IsSameOrWithin(finding.Path, r.Path));
            roots.Add(new ScanRoot
            {
                Path = directory,
                Kind = originalRoot?.Kind ?? ScanRootKind.CustomDirectory,
                Reason = "Folder that contained a finding in the original scan",
                InstallationId = originalRoot?.InstallationId,
                InstallationName = originalRoot?.InstallationName,
                InstallationRoot = originalRoot?.InstallationRoot,
                Recursive = false,
            });
        }

        if (original.Scope.IncludeSystemArtifactChecks)
        {
            var resolution = SystemArtifactResolver.Resolve(_rules(), _resolver, config.Detection.EnabledCategories.ToHashSet());
            roots.AddRange(resolution.Roots);
        }

        return new ScanScope
        {
            Mode = ScanMode.Verification,
            Roots = Deduplicate(roots),
            ExcludedPaths = original.Scope.ExcludedPaths,
            IncludeSystemArtifactChecks = original.Scope.IncludeSystemArtifactChecks,
            IncludeStartupInspection = original.Scope.IncludeStartupInspection,
            IncludeProcessInspection = false,
        };
    }

    private static IEnumerable<MinecraftInstallation> SelectInstallations(DiscoveryResult discovery, AppConfiguration config) =>
        discovery.Installations.Where(i =>
            (i.Launcher == LauncherKind.Custom || config.Scan.IncludeDiscoveredInstallations) &&
            !config.Scan.DisabledInstallationIds.Contains(i.Id, StringComparer.OrdinalIgnoreCase));

    private IEnumerable<ScanRoot> QuickRoots(MinecraftInstallation installation)
    {
        if (installation.QuickScanSubdirectories.Count == 0)
        {
            yield return FullRoot(installation) with { Reason = $"{installation.Name} (whole folder; its layout is not documented)" };
            yield break;
        }

        yield return new ScanRoot
        {
            Path = installation.RootPath,
            Kind = ScanRootKind.Installation,
            Reason = $"{installation.Name}: files and folder names in the game directory (not recursive)",
            InstallationId = installation.Id,
            InstallationName = installation.Name,
            InstallationRoot = installation.RootPath,
            Recursive = false,
        };

        var subdirectories = installation.QuickScanSubdirectories.Concat(RuleDerivedSubdirectories()).Distinct(StringComparer.OrdinalIgnoreCase);
        foreach (var sub in subdirectories)
        {
            var path = Path.Combine(installation.RootPath, sub);
            if (Directory.Exists(path))
            {
                yield return new ScanRoot
                {
                    Path = path,
                    Kind = ScanRootKind.Installation,
                    Reason = $"{installation.Name}: {sub} folder",
                    InstallationId = installation.Id,
                    InstallationName = installation.Name,
                    InstallationRoot = installation.RootPath,
                };
            }
        }
    }

    private static ScanRoot FullRoot(MinecraftInstallation installation) => new()
    {
        Path = installation.RootPath,
        Kind = ScanRootKind.Installation,
        Reason = $"{installation.Name} (entire game directory)",
        InstallationId = installation.Id,
        InstallationName = installation.Name,
        InstallationRoot = installation.RootPath,
    };

    /// <summary>Folders named by configuration-leftover rules (for example 'wurst'), so Quick Scan checks their contents too.</summary>
    private IEnumerable<string> RuleDerivedSubdirectories()
    {
        foreach (var rule in _rules().Rules)
        {
            foreach (var indicator in rule.Definition.Indicators)
            {
                if (indicator.Type == IndicatorType.DirectoryName && indicator.AtInstallationRoot && indicator.Value is { } name)
                {
                    yield return name;
                }
                else if (indicator.Type == IndicatorType.RelativePath && indicator.Value is { } relative && relative.Contains('/'))
                {
                    yield return relative[..relative.IndexOf('/')];
                }
            }
        }
    }

    private static List<ScanRoot> Deduplicate(List<ScanRoot> roots)
    {
        var seen = new HashSet<string>(PathKey.Comparer);
        var result = new List<ScanRoot>();
        foreach (var root in roots)
        {
            if (seen.Add(PathKey.ToKey(root.Path) + "|" + root.Recursive + "|" + root.IsFile))
            {
                result.Add(root);
            }
        }

        return result;
    }
}
