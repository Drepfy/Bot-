using System.Collections.ObjectModel;
using System.Windows.Input;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Rules;
using CleanerPro.Quarantine;
using CleanerPro.Reporting;

namespace CleanerPro.App.ViewModels;

/// <summary>Dashboard. Every value comes from persisted history, the quarantine store or the rule repository.</summary>
public sealed class DashboardViewModel : PageViewModel
{
    private readonly HistoryStore _history;
    private readonly QuarantineService _quarantine;
    private readonly RuleRepository _rules;
    private readonly ConfigurationService _configuration;
    private readonly AppState _state;
    private DashboardStatistics? _stats;

    public DashboardViewModel(HistoryStore history, QuarantineService quarantine, RuleRepository rules, ConfigurationService configuration, AppState state)
    {
        _history = history;
        _quarantine = quarantine;
        _rules = rules;
        _configuration = configuration;
        _state = state;
        GoToScannerCommand = new RelayCommand(() => _state.Navigate("scanner"));
        GoToFindingsCommand = new RelayCommand(() => _state.Navigate("findings"));
        GoToQuarantineCommand = new RelayCommand(() => _state.Navigate("quarantine"));
        GoToInstallationsCommand = new RelayCommand(() => _state.Navigate("installations"));
        _state.DataChanged += (_, _) => Refresh();
        _state.SessionChanged += (_, _) => Refresh();
        _state.DiscoveryChanged += (_, _) => Refresh();
    }

    public override string Key => "dashboard";

    public override string Title => "Dashboard";

    public override string Icon => "\uE80F";

    public override string Description => "Overview of your most recent scan and current protection state.";

    public ICommand GoToScannerCommand { get; }

    public ICommand GoToFindingsCommand { get; }

    public ICommand GoToQuarantineCommand { get; }

    public ICommand GoToInstallationsCommand { get; }

    public ObservableCollection<string> Notices { get; } = [];

    /// <summary>Messages from startup (for example recovered quarantine operations).</summary>
    public List<string> StartupNotices { get; } = [];

    public bool HasScan => _stats?.LastScan is not null;

    public string LastScanText => _stats?.LastScan is { } last
        ? $"{last.Mode} scan, {last.CompletedAtUtc?.ToLocalTime():g} ({last.State})"
        : "No completed scan yet";

    public string FilesInspected => _stats is { LastScan: not null } s ? s.FilesInspected.ToString("N0") : "—";

    public string UniqueDetections => _stats is { LastScan: not null } s ? s.UniqueDetections.ToString("N0") : "—";

    public string ConfirmedMatches => _stats is { LastScan: not null } s ? s.ConfirmedMatches.ToString("N0") : "—";

    public string SuspiciousFiles => _stats is { LastScan: not null } s ? s.SuspiciousFiles.ToString("N0") : "—";

    public string QuarantinedFiles => (_stats?.QuarantinedFiles ?? 0).ToString("N0");

    public string VerifiedRemovals => _stats is { LastScan: not null } s ? s.VerifiedRemovals.ToString("N0") : "—";

    public string SkippedFiles => _stats is { LastScan: not null } s ? s.SkippedFiles.ToString("N0") : "—";

    public string DatabaseVersion => _stats?.DatabaseVersion ?? "—";

    public string RulesSource => _rules.Active.StatusMessage;

    public string InstallationsSummary => _state.Discovery.Installations.Count switch
    {
        0 => "No Minecraft installation was found automatically. Add your game folder on the Installations page.",
        1 => "1 Minecraft installation discovered.",
        var n => $"{n} Minecraft installations discovered.",
    };

    public string NetworkSummary => _configuration.Current.Privacy.OfflineMode
        ? "Offline mode is on: the application makes no network requests."
        : "Offline mode is off: only signed rule updates from your configured HTTPS source can be downloaded.";

    public override void OnNavigatedTo() => Refresh();

    public void Refresh()
    {
        _stats = DashboardStatistics.Compute(_history, _quarantine, _rules.Active.Database.DisplayVersion);
        Notices.Clear();
        foreach (var notice in StartupNotices)
        {
            Notices.Add(notice);
        }

        var load = _configuration.LastLoad;
        if (load.UsingSafeDefaults)
        {
            Notices.Add("Configuration problem: " + load.FailureMessage + " Open the Configuration page to fix it.");
        }

        foreach (var warning in _rules.Active.Warnings)
        {
            Notices.Add("Rule database: " + warning);
        }

        if (_stats.LastScan is { Mode: not ScanMode.Verification } last && last.KnownMatches + last.HighConfidence > 0 && _stats.QuarantinedFiles == 0)
        {
            Notices.Add($"The last scan reported {last.KnownMatches + last.HighConfidence} item(s) that may need cleanup. Review them on the Findings page.");
        }

        OnAllPropertiesChanged();
    }
}
