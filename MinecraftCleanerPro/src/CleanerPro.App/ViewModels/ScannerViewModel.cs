using System.Collections.ObjectModel;
using System.Windows.Input;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Core.Safety;
using CleanerPro.Reporting;
using CleanerPro.Scanner;
using CleanerPro.Scanner.Discovery;
using Microsoft.Extensions.Logging;

namespace CleanerPro.App.ViewModels;

public sealed record ScopeRootItem(string Path, string Kind, string Reason, string Depth);

/// <summary>Quick, Full and Custom scans with an explicit scope preview, live progress, pause/resume and cancel.</summary>
public sealed class ScannerViewModel : PageViewModel
{
    public const string SelfTestContent =
        "MINECRAFT-CLEANER-PRO HARMLESS TEST FILE v1\nThis file contains no code. It only exists to confirm that detection, quarantine and restore work.\n";

    private readonly ScanEngine _engine;
    private readonly ScanScopeBuilder _scopes;
    private readonly DiscoveryCoordinator _discoveryCoordinator;
    private readonly HistoryStore _history;
    private readonly ReportService _reports;
    private readonly ConfigurationService _configuration;
    private readonly PathSafetyPolicy _policy;
    private readonly IDialogService _dialogs;
    private readonly AppState _state;
    private readonly ILogger<ScannerViewModel> _logger;

    private ScanMode _mode = ScanMode.Quick;
    private ScanScope? _scope;
    private CancellationTokenSource? _cancellation;
    private PauseController? _pause;
    private Task<ScanSession>? _running;
    private bool _isRunning;
    private bool _isPaused;
    private string _stageText = "Not started";
    private long _discovered;
    private long _inspected;
    private long _skipped;
    private long _findings;
    private string? _currentPath;
    private double _percent;
    private bool _indeterminate;
    private string _resultSummary = string.Empty;
    private string? _selectedCustomFolder;

    public ScannerViewModel(ScanEngine engine, ScanScopeBuilder scopes, DiscoveryCoordinator discoveryCoordinator, HistoryStore history, ReportService reports,
        ConfigurationService configuration, PathSafetyPolicy policy, IDialogService dialogs, AppState state, ILogger<ScannerViewModel> logger)
    {
        _engine = engine;
        _scopes = scopes;
        _discoveryCoordinator = discoveryCoordinator;
        _history = history;
        _reports = reports;
        _configuration = configuration;
        _policy = policy;
        _dialogs = dialogs;
        _state = state;
        _logger = logger;

        StartCommand = new AsyncRelayCommand(StartAsync, () => !IsRunning && _scope is { Roots.Count: > 0 });
        PauseCommand = new RelayCommand(Pause, () => IsRunning && !IsPaused);
        ResumeCommand = new RelayCommand(Resume, () => IsRunning && IsPaused);
        CancelCommand = new RelayCommand(Cancel, () => IsRunning);
        AddCustomFolderCommand = new RelayCommand(AddCustomFolder, () => !IsRunning);
        RemoveCustomFolderCommand = new RelayCommand(RemoveCustomFolder, () => !IsRunning && SelectedCustomFolder is not null);
        RefreshScopeCommand = new RelayCommand(RefreshScope, () => !IsRunning);
        ViewFindingsCommand = new RelayCommand(() => _state.Navigate("findings"));
        SelfTestCommand = new AsyncRelayCommand(RunSelfTestAsync, () => !IsRunning);
        _state.DiscoveryChanged += (_, _) => RefreshScope();
    }

    public override string Key => "scanner";

    public override string Title => "Scanner";

    public override string Icon => "\uE721";

    public override string Description => "Choose what to scan, review the exact scope, then start. Scanning only reads files; nothing is changed until you approve a cleanup action.";

    public ICommand StartCommand { get; }

    public ICommand PauseCommand { get; }

    public ICommand ResumeCommand { get; }

    public ICommand CancelCommand { get; }

    public ICommand AddCustomFolderCommand { get; }

    public ICommand RemoveCustomFolderCommand { get; }

    public ICommand RefreshScopeCommand { get; }

    public ICommand ViewFindingsCommand { get; }

    public ICommand SelfTestCommand { get; }

    public ObservableCollection<ScopeRootItem> ScopeRoots { get; } = [];

    public ObservableCollection<string> ExcludedPaths { get; } = [];

    public ObservableCollection<string> CustomFolders { get; } = [];

    public string? SelectedCustomFolder
    {
        get => _selectedCustomFolder;
        set => SetProperty(ref _selectedCustomFolder, value);
    }

    public bool IsQuick
    {
        get => _mode == ScanMode.Quick;
        set => SetMode(value, ScanMode.Quick);
    }

    public bool IsFull
    {
        get => _mode == ScanMode.Full;
        set => SetMode(value, ScanMode.Full);
    }

    public bool IsCustom
    {
        get => _mode == ScanMode.Custom;
        set => SetMode(value, ScanMode.Custom);
    }

    public string ModeExplanation => _mode switch
    {
        ScanMode.Quick => "Quick Scan: mods, config, versions and resource packs of each enabled installation, files directly in the game folder, documented malware locations and your startup entries.",
        ScanMode.Full => "Full Minecraft Scan: every file of each enabled installation (except saves, screenshots, assets and logs), plus documented malware locations and your startup entries.",
        _ => "Custom Scan: only the folders you choose below, recursively. Folders outside Minecraft are allowed but only read.",
    };

    public string ScopeSummary => _scope is null
        ? "The scope has not been calculated yet."
        : _scope.Roots.Count == 0
            ? _mode == ScanMode.Custom ? "Add at least one folder to scan." : "No enabled installation was found. Add a folder on the Installations page or use Custom Scan."
            : $"{_scope.Roots.Count} location(s) will be read. {(_scope.IncludeStartupInspection ? "Per-user startup entries will be read (never modified). " : string.Empty)}" +
              $"{(_scope.IncludeJavaEnvironment ? $"{_scope.LaunchSettingsFiles.Count} launcher settings file(s) and the Java environment variables will be checked for Java agents (read-only). " : string.Empty)}" +
              $"{(_scope.IncludeProcessInspection ? "Running processes will be listed (read-only). " : string.Empty)}";

    public string ResourceNotice =>
        "Scanning temporarily uses CPU, memory and disk. Workers run at reduced priority" +
        (_configuration.Current.Performance.LowResourceMode ? " in low-resource mode (one worker)." : $" with at most {_configuration.Current.Performance.MaxParallelTasks} parallel task(s).") +
        " The actual impact depends on your hardware and the number of files.";

    public bool IsRunning
    {
        get => _isRunning;
        private set
        {
            if (SetProperty(ref _isRunning, value))
            {
                _state.IsScanning = value;
                CommandManager.InvalidateRequerySuggested();
            }
        }
    }

    public bool IsPaused
    {
        get => _isPaused;
        private set => SetProperty(ref _isPaused, value);
    }

    public string StageText
    {
        get => _stageText;
        private set => SetProperty(ref _stageText, value);
    }

    public long FilesDiscovered
    {
        get => _discovered;
        private set => SetProperty(ref _discovered, value);
    }

    public long FilesInspected
    {
        get => _inspected;
        private set => SetProperty(ref _inspected, value);
    }

    public long FilesSkipped
    {
        get => _skipped;
        private set => SetProperty(ref _skipped, value);
    }

    public long FindingsCount
    {
        get => _findings;
        private set => SetProperty(ref _findings, value);
    }

    public string? CurrentPath
    {
        get => _currentPath;
        private set => SetProperty(ref _currentPath, value);
    }

    public double ProgressPercent
    {
        get => _percent;
        private set => SetProperty(ref _percent, value);
    }

    /// <summary>True while the total is still unknown (enumeration in progress): no percentage is invented.</summary>
    public bool IsIndeterminate
    {
        get => _indeterminate;
        private set => SetProperty(ref _indeterminate, value);
    }

    public string ResultSummary
    {
        get => _resultSummary;
        private set => SetProperty(ref _resultSummary, value);
    }

    public override void OnNavigatedTo()
    {
        if (!IsRunning)
        {
            RefreshScope();
        }

        OnPropertyChanged(nameof(ResourceNotice));
    }

    private void SetMode(bool selected, ScanMode mode)
    {
        if (!selected || _mode == mode)
        {
            return;
        }

        _mode = mode;
        OnPropertyChanged(nameof(IsQuick));
        OnPropertyChanged(nameof(IsFull));
        OnPropertyChanged(nameof(IsCustom));
        OnPropertyChanged(nameof(ModeExplanation));
        RefreshScope();
    }

    public void RefreshScope()
    {
        if (IsRunning)
        {
            return;
        }

        if (_state.Discovery.Installations.Count == 0 && _state.Discovery.LocationsChecked.Count == 0)
        {
            _discoveryCoordinator.Refresh();
            return; // DiscoveryChanged calls back into RefreshScope.
        }

        _scope = _scopes.Build(_mode, _state.Discovery, CustomFolders.ToList());
        ScopeRoots.Clear();
        foreach (var root in _scope.Roots)
        {
            ScopeRoots.Add(new ScopeRootItem(root.Path, root.Kind switch
            {
                ScanRootKind.Installation => "Installation",
                ScanRootKind.SystemArtifactLocation => "Documented location",
                ScanRootKind.ReferencedFile => "Loaded by launch settings",
                ScanRootKind.DownloadLocation => "Download location",
                _ => "Your folder",
            }, root.Reason, root.IsFile ? "File" : !root.Recursive ? "This folder only" : root.MaxDepth is { } depth ? $"{depth} levels deep" : "All subfolders"));
        }

        ExcludedPaths.Clear();
        foreach (var excluded in _scope.ExcludedPaths)
        {
            ExcludedPaths.Add(excluded);
        }

        OnPropertyChanged(nameof(ScopeSummary));
        CommandManager.InvalidateRequerySuggested();
    }

    private void AddCustomFolder()
    {
        var folder = _dialogs.PickFolder("Choose a folder to scan (read-only)");
        if (folder is null)
        {
            return;
        }

        var check = _policy.ValidateScanRoot(folder);
        if (!check.IsAllowed)
        {
            _dialogs.ShowError("Folder not added", check.Reason ?? "The folder cannot be scanned.");
            return;
        }

        if (!CustomFolders.Contains(check.NormalizedPath!, StringComparer.OrdinalIgnoreCase))
        {
            CustomFolders.Add(check.NormalizedPath!);
        }

        IsCustom = true;
        RefreshScope();
    }

    private void RemoveCustomFolder()
    {
        if (SelectedCustomFolder is { } folder)
        {
            CustomFolders.Remove(folder);
            RefreshScope();
        }
    }

    private async Task StartAsync()
    {
        RefreshScope();
        if (_scope is not { Roots.Count: > 0 } scope)
        {
            _dialogs.ShowInfo("Nothing to scan", ScopeSummary);
            return;
        }

        if (_configuration.Current.Interface.ShowScanScopeBeforeScan &&
            !_dialogs.Confirm($"Start {_mode} scan?", "These locations will be read. Nothing is modified during a scan.",
                scope.Roots.Select(r => $"{r.Path}  ({(r.Recursive ? "all subfolders" : "this folder only")})").ToList(), "Start scan"))
        {
            return;
        }

        await RunScanAsync(scope, parentSessionId: null);
    }

    /// <summary>Runs a scan with live progress, saves it to history and makes it the current session.</summary>
    public async Task<ScanSession?> RunScanAsync(ScanScope scope, string? parentSessionId)
    {
        if (IsRunning)
        {
            return null;
        }

        _cancellation = new CancellationTokenSource();
        _pause = new PauseController();
        IsRunning = true;
        IsPaused = false;
        ResultSummary = string.Empty;
        StageText = "Starting…";
        FilesDiscovered = FilesInspected = FilesSkipped = FindingsCount = 0;
        ProgressPercent = 0;
        IsIndeterminate = true;
        _state.StatusMessage = $"{scope.Mode} scan running…";

        var progress = new Progress<ScanProgress>(UpdateProgress);
        try
        {
            _running = _engine.RunAsync(scope, progress, _pause, _cancellation.Token, parentSessionId);
            var session = await _running;
            _history.Save(session);
            _reports.ApplyRetention();
            if (session.Mode != ScanMode.Verification)
            {
                _state.CurrentSession = session;
            }

            ResultSummary = session.State switch
            {
                ScanState.Completed => $"Scan completed: {session.Statistics.FilesInspected:N0} files inspected, {session.Findings.Count} item(s) flagged, {session.SkippedTotal:N0} skipped or partially inspected.",
                ScanState.Cancelled => $"Scan cancelled after {session.Statistics.FilesInspected:N0} files. Results are incomplete.",
                _ => $"Scan failed: {session.FailureMessage}",
            };
            _state.StatusMessage = ResultSummary;
            _state.NotifyDataChanged();
            return session;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Scan failed");
            ResultSummary = $"The scan could not run: {ex.Message}";
            _state.StatusMessage = ResultSummary;
            return null;
        }
        finally
        {
            IsRunning = false;
            IsPaused = false;
            IsIndeterminate = false;
            _pause.Dispose();
            _cancellation.Dispose();
            _cancellation = null;
            _running = null;
        }
    }

    private void UpdateProgress(ScanProgress progress)
    {
        StageText = progress.State == ScanState.Paused ? "Paused" : progress.Stage switch
        {
            ScanStage.DiscoveringLocations => "Preparing",
            ScanStage.EnumeratingFiles => "Finding files and inspecting",
            ScanStage.InspectingFiles => "Inspecting files",
            ScanStage.CheckingSystemArtifacts => "Checking startup entries",
            ScanStage.Finalizing => "Finalizing results",
            ScanStage.Completed => "Done",
            _ => progress.Stage.ToString(),
        };
        FilesDiscovered = progress.FilesDiscovered;
        FilesInspected = progress.FilesInspected;
        FilesSkipped = progress.FilesSkipped;
        FindingsCount = progress.FindingsCount;
        CurrentPath = progress.CurrentPath;
        if (progress.CompletedFraction is { } fraction)
        {
            IsIndeterminate = false;
            ProgressPercent = fraction * 100;
        }
        else
        {
            IsIndeterminate = progress.Stage != ScanStage.Completed;
        }
    }

    private void Pause()
    {
        _pause?.Pause();
        IsPaused = true;
        StageText = "Paused";
        _state.StatusMessage = "Scan paused.";
    }

    private void Resume()
    {
        _pause?.Resume();
        IsPaused = false;
        _state.StatusMessage = "Scan resumed.";
    }

    private void Cancel()
    {
        _pause?.Resume();
        _cancellation?.Cancel();
        StageText = "Cancelling…";
    }

    /// <summary>Called when the application closes during a scan: cancels and waits briefly so partial results are saved.</summary>
    public async Task CancelForShutdownAsync()
    {
        if (_running is not { } running)
        {
            return;
        }

        Cancel();
        try
        {
            var session = await running.WaitAsync(TimeSpan.FromSeconds(10));
            _history.Save(session);
        }
        catch (TimeoutException)
        {
            _logger.LogWarning("Scan did not stop within 10 seconds of shutdown");
        }
    }

    private async Task RunSelfTestAsync()
    {
        var folder = Path.Combine(Path.GetTempPath(), "MinecraftCleanerPro-SelfTest");
        var file = Path.Combine(folder, "cleanerpro-harmless-test.txt");
        if (!_dialogs.Confirm("Run detection self-test?",
                "A small harmless text file will be created and scanned to confirm that detection works. It contains no code. You can then try quarantine and restore on it safely.",
                [file], "Create and scan"))
        {
            return;
        }

        Directory.CreateDirectory(folder);
        await File.WriteAllTextAsync(file, SelfTestContent);
        var scope = _scopes.Build(ScanMode.Custom, _state.Discovery, [folder]);
        var session = await RunScanAsync(scope, null);
        if (session is null)
        {
            return;
        }

        var detected = session.Findings.FirstOrDefault(f => f.RuleMatches.Any(m => m.RuleId == "CP-TEST-0001") && f.Classification == Classification.KnownMatch);
        if (detected is not null)
        {
            _dialogs.ShowInfo("Self-test passed", $"The harmless test file was detected as a Known match by rule CP-TEST-0001.\n\n{file}\n\nOpen the Findings page to try quarantine and restore on it.");
        }
        else
        {
            _dialogs.ShowError("Self-test failed", "The harmless test file was not detected. Check that the 'TestSignature' category and hash verification are enabled in the configuration.");
        }
    }
}
