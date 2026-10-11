using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Windows.Data;
using System.Windows.Input;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Reporting;

namespace CleanerPro.App.ViewModels;

/// <summary>Previous scans and the audit log of cleanup operations, with search, export and deletion.</summary>
public sealed class HistoryViewModel : PageViewModel
{
    private readonly HistoryStore _history;
    private readonly OperationLog _operations;
    private readonly ReportService _reports;
    private readonly ConfigurationService _configuration;
    private readonly IDialogService _dialogs;
    private readonly IShellLauncher _shell;
    private readonly AppState _state;
    private ScanSummary? _selected;
    private string _searchText = string.Empty;

    public HistoryViewModel(HistoryStore history, OperationLog operations, ReportService reports, ConfigurationService configuration,
        IDialogService dialogs, IShellLauncher shell, AppState state)
    {
        _history = history;
        _operations = operations;
        _reports = reports;
        _configuration = configuration;
        _dialogs = dialogs;
        _shell = shell;
        _state = state;

        SessionsView = CollectionViewSource.GetDefaultView(Sessions);
        SessionsView.Filter = o => o is ScanSummary s && Matches(s.Id + " " + s.Mode + " " + s.State + " " + s.RulesVersion);
        OperationsView = CollectionViewSource.GetDefaultView(Operations);
        OperationsView.Filter = o => o is OperationRecord r && Matches(r.Type + " " + r.Path + " " + r.Message);

        OpenCommand = new RelayCommand(Open, () => Selected is not null);
        ExportCommand = new RelayCommand(Export, () => Selected is not null);
        DeleteCommand = new RelayCommand(Delete, () => Selected is not null && !_state.IsScanning);
        DeleteAllCommand = new RelayCommand(DeleteAll, () => Sessions.Count > 0 && !_state.IsScanning);
        RefreshCommand = new RelayCommand(Refresh);
        OpenReportsFolderCommand = new RelayCommand(() =>
        {
            Directory.CreateDirectory(_reports.ReportsDirectory);
            var result = _shell.OpenFolder(_reports.ReportsDirectory);
            if (!result.Succeeded)
            {
                _dialogs.ShowError("Could not open", result.Message);
            }
        });
        _state.DataChanged += (_, _) => Refresh();
    }

    public override string Key => "history";

    public override string Title => "History";

    public override string Icon => "\uE81C";

    public override string Description => "Every scan and every quarantine, restore and deletion, stored only on this computer.";

    public ObservableCollection<ScanSummary> Sessions { get; } = [];

    public ObservableCollection<OperationRecord> Operations { get; } = [];

    public ICollectionView SessionsView { get; }

    public ICollectionView OperationsView { get; }

    public ScanSummary? Selected
    {
        get => _selected;
        set => SetProperty(ref _selected, value);
    }

    public string SearchText
    {
        get => _searchText;
        set
        {
            if (SetProperty(ref _searchText, value))
            {
                SessionsView.Refresh();
                OperationsView.Refresh();
            }
        }
    }

    public bool IsEmpty => Sessions.Count == 0;

    public ICommand OpenCommand { get; }

    public ICommand ExportCommand { get; }

    public ICommand DeleteCommand { get; }

    public ICommand DeleteAllCommand { get; }

    public ICommand RefreshCommand { get; }

    public ICommand OpenReportsFolderCommand { get; }

    public override void OnNavigatedTo() => Refresh();

    public void Refresh()
    {
        Sessions.Clear();
        foreach (var summary in _history.ListSummaries())
        {
            Sessions.Add(summary);
        }

        Operations.Clear();
        foreach (var record in _operations.ReadAll().OrderByDescending(o => o.TimestampUtc))
        {
            Operations.Add(record);
        }

        OnPropertyChanged(nameof(IsEmpty));
    }

    private bool Matches(string text) => SearchText.Trim().Length == 0 || text.Contains(SearchText.Trim(), StringComparison.OrdinalIgnoreCase);

    private void Open()
    {
        var session = Selected is null ? null : _history.Load(Selected.Id);
        if (session is null)
        {
            _dialogs.ShowError("Could not open", "The scan record could not be read.");
            return;
        }

        _state.CurrentSession = session;
        _state.Navigate("findings");
    }

    private void Export()
    {
        var session = Selected is null ? null : _history.Load(Selected.Id);
        if (session is not null)
        {
            ReportExportFlow.Run(session, _reports, _dialogs, _configuration.Current, _shell, _state);
        }
    }

    private void Delete()
    {
        if (Selected is not { } selected ||
            !_dialogs.Confirm("Delete scan record?", "The scan record and its verification results are deleted. Quarantined files and the operations audit log are not affected.",
                [$"{selected.Mode} scan {selected.Id} ({selected.StartedAtUtc.ToLocalTime():g})"], "Delete record"))
        {
            return;
        }

        _history.Delete(selected.Id);
        if (_state.CurrentSession?.Id == selected.Id)
        {
            _state.CurrentSession = null;
        }

        Refresh();
        _state.NotifyDataChanged();
    }

    private void DeleteAll()
    {
        var answer = _dialogs.Ask(new ConfirmationRequest
        {
            Title = "Delete all scan history?",
            Message = $"All {Sessions.Count} scan record(s) and verification results will be deleted. Quarantined files, saved reports and the operations audit log are kept.",
            TypeToConfirm = "DELETE",
            Choices = [new DialogChoice("delete", "Delete all history", IsDestructive: true), new DialogChoice("cancel", "Cancel", IsCancel: true)],
        });
        if (answer != "delete")
        {
            return;
        }

        var count = _history.DeleteAll();
        _state.CurrentSession = null;
        _state.StatusMessage = $"{count} scan record(s) deleted.";
        Refresh();
        _state.NotifyDataChanged();
    }
}
