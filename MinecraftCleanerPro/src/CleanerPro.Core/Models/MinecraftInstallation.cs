namespace CleanerPro.Core.Models;

/// <summary>A Minecraft game directory or launcher data location found by discovery.</summary>
public sealed record MinecraftInstallation
{
    public required string Id { get; init; }

    public required string Name { get; init; }

    public required LauncherKind Launcher { get; init; }

    /// <summary>The directory that will be scanned for this installation.</summary>
    public required string RootPath { get; init; }

    public IReadOnlyList<ModLoader> ModLoaders { get; init; } = [];

    public string? MinecraftVersion { get; init; }

    /// <summary>How the installation was found (metadata file, default location, user choice...).</summary>
    public required string DiscoveredBy { get; init; }

    /// <summary>Sub-directories that a Quick Scan inspects (relative to <see cref="RootPath"/>).</summary>
    public IReadOnlyList<string> QuickScanSubdirectories { get; init; } = [];

    /// <summary>Sub-directories that are skipped by default because they contain large runtime files.</summary>
    public IReadOnlyList<string> DefaultExcludedSubdirectories { get; init; } = [];

    /// <summary>Parsing problems or other limitations found while discovering this installation.</summary>
    public IReadOnlyList<string> Notes { get; init; } = [];

    /// <summary>Launcher settings files that can add JVM arguments (for example Java agents) when this installation starts.</summary>
    public IReadOnlyList<string> LaunchSettingsFiles { get; init; } = [];

    public DateTimeOffset? LastInspectedUtc { get; init; }
}

/// <summary>Result of an installation discovery pass, including problems that were encountered.</summary>
public sealed record DiscoveryResult
{
    public IReadOnlyList<MinecraftInstallation> Installations { get; init; } = [];

    public IReadOnlyList<string> Notes { get; init; } = [];

    public IReadOnlyList<string> LocationsChecked { get; init; } = [];
}
