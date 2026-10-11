using System.Collections.ObjectModel;
using System.Windows.Input;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.Configuration;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Privacy;
using CleanerPro.Reporting;
using CleanerPro.Scanner;

namespace CleanerPro.App.ViewModels;

public sealed record DataLocation(string Name, string Path, string Purpose);

/// <summary>Privacy statement, network activity audit, rule database status and local data management.</summary>
public sealed class PrivacyViewModel : PageViewModel
{
    private readonly ConfigurationService _configuration;
    private readonly AppPaths _paths;
    private readonly NetworkActivityLog _networkLog;
    private readonly RuleRepository _rules;
    private readonly RuleUpdateService _updates;
    private readonly HistoryStore _history;
    private readonly ReportService _reports;
    private readonly ScanResultCache _cache;
    private readonly IDialogService _dialogs;
    private readonly IShellLauncher _shell;
    private readonly AppState _state;
    private string _updateStatus = string.Empty;

    public PrivacyViewModel(ConfigurationService configuration, AppPaths paths, NetworkActivityLog networkLog, RuleRepository rules, RuleUpdateService updates,
        HistoryStore history, ReportService reports, ScanResultCache cache, IDialogService dialogs, IShellLauncher shell, AppState state)
    {
        _configuration = configuration;
        _paths = paths;
        _networkLog = networkLog;
        _rules = rules;
        _updates = updates;
        _history = history;
        _reports = reports;
        _cache = cache;
        _dialogs = dialogs;
        _shell = shell;
        _state = state;

        CheckUpdatesCommand = new AsyncRelayCommand(CheckUpdatesAsync, () => !_configuration.Current.Privacy.OfflineMode && _configuration.Current.RuleUpdates.Enabled &&
                                                                              !string.IsNullOrWhiteSpace(_configuration.Current.RuleUpdates.Endpoint));
        OpenLocationCommand = new RelayCommand(p =>
        {
            if (p is string path)
            {
                Directory.CreateDirectory(path);
                var result = _shell.OpenFolder(path);
                if (!result.Succeeded)
                {
                    _dialogs.ShowError("Could not open", result.Message);
                }
            }
        });
        DeleteHistoryCommand = new RelayCommand(DeleteHistory, () => !_state.IsScanning);
        DeleteReportsCommand = new RelayCommand(DeleteReports);
        ClearCacheCommand = new RelayCommand(ClearCache, () => !_state.IsScanning);
        ClearNetworkLogCommand = new RelayCommand(ClearNetworkLog);
        RefreshCommand = new RelayCommand(Refresh);
    }

    public override string Key => "privacy";

    public override string Title => "Privacy & Updates";

    public override string Icon => "\uE8D7";

    public override string Description => "What the application does with data, every network request it has made, and the detection rule database.";

    public string Statement => PrivacyStatement.Summary;

    public string OfflineStatus => _configuration.Current.Privacy.OfflineMode
        ? "Offline mode is ON. No network requests are made. (Change it on the Configuration page.)"
        : "Offline mode is OFF. Only signed rule updates from your configured HTTPS source may be downloaded.";

    public string RulesStatus => _rules.Active.StatusMessage;

    public string RulesDetails
    {
        get
        {
            var database = _rules.Active.Database;
            return $"Version {database.DisplayVersion} (#{database.DatabaseVersion}), published {database.Document.PublishedAt:yyyy-MM-dd}, " +
                   $"{database.Rules.Count} rules active on Windows, SHA-256 {database.Sha256}.";
        }
    }

    public string UpdateConfiguration => _updates.DescribeConfiguration();

    public string UpdateStatus
    {
        get => _updateStatus;
        private set => SetProperty(ref _updateStatus, value);
    }

    public ObservableCollection<NetworkActivityRecord> NetworkActivity { get; } = [];

    public ObservableCollection<DataLocation> Locations { get; } = [];

    public ObservableCollection<string> RuleWarnings { get; } = [];

    public bool NoNetworkActivity => NetworkActivity.Count == 0;

    public ICommand CheckUpdatesCommand { get; }

    public ICommand OpenLocationCommand { get; }

    public ICommand DeleteHistoryCommand { get; }

    public ICommand DeleteReportsCommand { get; }

    public ICommand ClearCacheCommand { get; }

    public ICommand ClearNetworkLogCommand { get; }

    public ICommand RefreshCommand { get; }

    public override void OnNavigatedTo() => Refresh();

    public void Refresh()
    {
        NetworkActivity.Clear();
        foreach (var record in _networkLog.ReadAll().OrderByDescending(r => r.TimestampUtc))
        {
            NetworkActivity.Add(record);
        }

        var config = _configuration.Current;
        Locations.Clear();
        Locations.Add(new DataLocation("Application data", _paths.DataRoot, "Everything the application stores"));
        Locations.Add(new DataLocation("Configuration", Path.GetDirectoryName(_paths.ConfigFile)!, "config.json and backups"));
        Locations.Add(new DataLocation("Quarantine", EffectiveLocations.QuarantineDirectory(config, _paths), "Encoded copies of quarantined files"));
        Locations.Add(new DataLocation("Reports", EffectiveLocations.ReportsDirectory(config, _paths), "Exported scan reports"));
        Locations.Add(new DataLocation("History", _paths.HistoryDirectory, "Scan records, verification results, operations audit log"));
        Locations.Add(new DataLocation("Logs", _paths.LogsDirectory, "Diagnostic logs (no file contents)"));

        RuleWarnings.Clear();
        foreach (var warning in _rules.Active.Warnings)
        {
            RuleWarnings.Add(warning);
        }

        var status = _updates.ReadStatus();
        UpdateStatus = status.LastCheckUtc is null ? "No update check has been performed." : $"Last check {status.LastCheckUtc.Value.ToLocalTime():g}: {status.Message}";
        OnAllPropertiesChanged();
    }

    private async Task CheckUpdatesAsync()
    {
        UpdateStatus = "Checking for a signed rule update…";
        var status = await _updates.CheckForUpdatesAsync(CancellationToken.None);
        Refresh();
        UpdateStatus = status.Message;
        _state.StatusMessage = status.Message;
        _state.NotifyDataChanged();
    }

    private void DeleteHistory()
    {
        if (!_dialogs.Confirm("Delete scan history?", "All scan records and verification results are deleted. Quarantined files and the operations audit log are kept.", [_paths.HistoryDirectory], "Delete history"))
        {
            return;
        }

        var count = _history.DeleteAll();
        _state.CurrentSession = null;
        _state.StatusMessage = $"{count} scan record(s) deleted.";
        _state.NotifyDataChanged();
    }

    private void DeleteReports()
    {
        if (!_dialogs.Confirm("Delete saved reports?", "All reports in the reports folder created by this application are deleted.", [_reports.ReportsDirectory], "Delete reports"))
        {
            return;
        }

        _state.StatusMessage = $"{_reports.DeleteAllReports()} report(s) deleted.";
    }

    private void ClearCache()
    {
        _cache.Clear();
        _state.StatusMessage = "The scan cache was cleared. The next scan re-inspects every file.";
    }

    private void ClearNetworkLog()
    {
        if (_dialogs.Confirm("Clear network activity log?", "The local record of network requests is deleted.", [_networkLog.FilePath], "Clear log"))
        {
            _networkLog.Clear();
            Refresh();
        }
    }
}
