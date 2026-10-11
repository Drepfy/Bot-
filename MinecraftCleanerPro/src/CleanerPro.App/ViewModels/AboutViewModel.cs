using CleanerPro.Core;
using CleanerPro.Detection.Rules;

namespace CleanerPro.App.ViewModels;

/// <summary>Version information and an honest list of what the application cannot do.</summary>
public sealed class AboutViewModel : PageViewModel
{
    private readonly RuleRepository _rules;

    public AboutViewModel(RuleRepository rules)
    {
        _rules = rules;
    }

    public override string Key => "about";

    public override string Title => "About & Limitations";

    public override string Icon => "\uE946";

    public override string Description => "What this application is, how it was built, and what it cannot verify.";

    public string Product => AppInfo.ProductName;

    public string Version => $"Version {AppInfo.Version} · rule database {_rules.Active.Database.DisplayVersion}";

    public string SigningNotice =>
        "This build is not code-signed. Windows SmartScreen may warn when you first run it. Verify the SHA-256 of the executable against the published release notes before running it.";

    public IReadOnlyList<string> Limitations { get; } =
    [
        "A file scan cannot prove that a player cheated. Detected files may be unused or left over, and cheats that run only in memory, are injected at runtime or were deleted before the scan leave nothing to find.",
        "Only cheat families and malware listed in the rule database are recognised. A file without findings is not declared safe.",
        "Renamed, repackaged or obfuscated cheats can avoid the specific rules; generic heuristics only report them for review.",
        "Closed-source clients (Lunar, Badlion, Feather) have undocumented folder layouts; their folders are scanned as a whole.",
        "The application never executes, injects into or reads the memory of Minecraft or any other process. Optional process inspection only lists executable paths.",
        "Registry startup entries and scheduled tasks are reported but never modified. Remove them with Windows tools or your antivirus after confirming.",
        "Authenticode signatures are verified offline; certificate revocation is not checked.",
        "Jar signature files (META-INF/*.SF) are noted but not cryptographically verified.",
        "No official online rule-update service exists for this release. Updates only work if you configure a trusted HTTPS source and signing key.",
        "Quarantine stores files encoded (XOR) to prevent accidental execution. This is not encryption.",
        "If malware such as fractureiser stage 2 or 3 was found, credentials may already have been stolen. Change passwords from a clean device and run a full antivirus scan; this application is not a replacement for antivirus software.",
    ];

    public IReadOnlyList<string> Credits { get; } =
    [
        "Detection indicators were verified on 2026-10-11 against the official repositories of Wurst7, Meteor Client, LiquidBounce, BleachHack, ThunderHack, Baritone, Sodium, Iris, Lithium, Mod Menu and Fabric, and against the fractureiser investigation and nekodetector. Every rule lists its sources.",
        "Built with .NET 10 and WPF. Dependencies: Microsoft.Extensions.DependencyInjection and Microsoft.Extensions.Logging (MIT).",
    ];
}
