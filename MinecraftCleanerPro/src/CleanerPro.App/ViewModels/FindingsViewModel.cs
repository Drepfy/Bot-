using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Windows;
using System.Windows.Data;
using System.Windows.Input;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.Configuration;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Quarantine;
using CleanerPro.Reporting;
using CleanerPro.Scanner;

namespace CleanerPro.App.ViewModels;

public sealed class FindingItem : ObservableObject
{
    private bool _isSelected;

    public FindingItem(Finding finding)
    {
        Finding = finding;
    }

    public Finding Finding { get; }

    public bool IsSelected
    {
        get => _isSelected;
        set => SetProperty(ref _isSelected, value);
    }

    public string Path => Finding.Path;

    public string Name => System.IO.Path.GetFileName(Finding.Path.TrimEnd('\\', '/'));

    public Classification Classification => Finding.Classification;

    public string ClassificationText => ClassificationOrder.ToDisplay(Finding.Classification);

    public int ClassificationRank => ClassificationOrder.Rank(Finding.Classification);

    public string Family => Finding.RuleMatches.FirstOrDefault()?.Family ?? "—";

    public string Rules => string.Join(", ", Finding.RuleMatches.Select(m => $"{m.RuleId} v{m.RuleVersion}"));

    public ThreatSeverity Severity => Finding.Severity;

    public DetectionConfidence Confidence => Finding.Confidence;

    public FileReputation Reputation => Finding.Reputation;

    public string RecommendedActionText => ClassificationOrder.ToDisplay(Finding.RecommendedAction);

    public string StatusText => ClassificationOrder.ToDisplay(Finding.CleanupStatus) + (Finding.CleanupMessage is null ? string.Empty : $": {Finding.CleanupMessage}");

    public string Installation => Finding.InstallationName ?? (Finding.IsSystemArtifact ? "System location" : "—");

    public string Sha256 => Finding.Sha256 ?? "(not hashed)";

    public string Sha1 => Finding.Sha1 ?? "—";

    public string Size => Finding.SizeBytes is { } size ? Converters.BytesConverter.Format(size) : "—";

    public string Identity => Finding.Identity is { } id ? $"{id.Loader} mod '{id.ModId}'{(id.Name is null ? string.Empty : $" ({id.Name})")}{(id.Version is null ? string.Empty : $" version {id.Version}")}" : "—";

    public string Rationale => Finding.ConfidenceRationale;

    public IReadOnlyList<Evidence> Evidence => Finding.Evidence;

    public IReadOnlyList<RuleMatch> RuleMatches => Finding.RuleMatches;

    public IReadOnlyList<string> Limitations => Finding.Limitations;

    /// <summary>Registry entries and protected system files can only be handled manually.</summary>
    public bool CanQuarantine =>
        Finding.CleanupStatus is CleanupStatus.NotActioned or CleanupStatus.QuarantineFailed or CleanupStatus.Restored or CleanupStatus.Blocked &&
        System.IO.Path.IsPathFullyQualified(Finding.Path) && Finding.Classification != Classification.LikelyLegitimate;

    public void Refresh() => OnAllPropertiesChanged();
}

/// <summary>Findings of the current session with evidence, filtering, quarantine and post-cleanup verification.</summary>
public sealed class FindingsViewModel : PageViewModel
{
    private readonly QuarantineService _quarantine;
    private readonly HistoryStore _history;
    private readonly OperationLog _operations;
    private readonly ScanScopeBuilder _scopes;
    private readonly ScannerViewModel _scanner;
    private readonly ConfigurationService _configuration;
    private readonly ReportService _reports;
    private readonly IDialogService _dialogs;
    private readonly IShellLauncher _shell;
    private readonly AppState _state;
    private FindingItem? _selected;
    private string _searchText = string.Empty;
    private string _classificationFilter = "All";
    private bool _busy;
    private string _verificationSummary = string.Empty;

    public FindingsViewModel(QuarantineService quarantine, HistoryStore history, OperationLog operations, ScanScopeBuilder scopes, ScannerViewModel scanner,
        ConfigurationService configuration, ReportService reports, IDialogService dialogs, IShellLauncher shell, AppState state)
    {
        _quarantine = quarantine;
        _history = history;
        _operations = operations;
        _scopes = scopes;
        _scanner = scanner;
        _configuration = configuration;
        _reports = reports;
        _dialogs = dialogs;
        _shell = shell;
        _state = state;

        View = CollectionViewSource.GetDefaultView(Items);
        View.Filter = Filter;
        View.SortDescriptions.Add(new SortDescription(nameof(FindingItem.ClassificationRank), ListSortDirection.Ascending));

        QuarantineSelectedCommand = new AsyncRelayCommand(QuarantineSelectedAsync, () => !_busy && !_state.IsScanning && Targets().Any());
        VerifyCommand = new AsyncRelayCommand(VerifyAsync, () => !_busy && !_state.IsScanning && Session is not null);
        OpenLocationCommand = new RelayCommand(() => ShowShell(_shell.RevealFile(Selected!.Path)), () => Selected is not null && System.IO.Path.IsPathFullyQualified(Selected.Path));
        CopyHashCommand = new RelayCommand(CopyHash, () => Selected?.Finding.Sha256 is not null);
        TrustCommand = new RelayCommand(Trust, () => Selected?.Finding.Sha256 is not null && Selected.Classification is not (Classification.KnownMatch or Classification.LikelyLegitimate));
        SelectAllCommand = new RelayCommand(() => SetSelection(true));
        ClearSelectionCommand = new RelayCommand(() => SetSelection(false));
        ExportReportCommand = new RelayCommand(ExportReport, () => Session is not null);
        GoToScannerCommand = new RelayCommand(() => _state.Navigate("scanner"));

        _state.SessionChanged += (_, _) => Load(_state.CurrentSession);
    }

    public override string Key => "findings";

    public override string Title => "Findings";

    public override string Icon => "\uE7BA";

    public override string Description => "Each flagged item with its classification, evidence and sources. Review the evidence before acting: quarantine is reversible, and nothing is ever deleted directly from here.";

    public ObservableCollection<FindingItem> Items { get; } = [];

    public ICollectionView View { get; }

    public ObservableCollection<VerificationItem> VerificationItems { get; } = [];

    public IReadOnlyList<string> ClassificationFilters { get; } = ["All", "Known match", "High-confidence suspicion", "Needs review", "Unverified", "Likely legitimate", "Not actioned"];

    public ScanSession? Session { get; private set; }

    public string SessionHeader => Session is null
        ? "No scan has been run yet."
        : $"{Session.Mode} scan {Session.Id} — {Session.StartedAtUtc.ToLocalTime():g} — {Session.State} — rules {Session.RulesVersion}";

    public string EmptyMessage => Session is null
        ? "Run a scan to see findings here."
        : "No rule matched any inspected item. This does not prove the files are safe; it means none of the documented indicators were found.";

    public bool HasFindings => Items.Count > 0;

    public string CountsText => Session is null ? string.Empty :
        $"{Items.Count} unique item(s): {Items.Count(i => i.Classification == Classification.KnownMatch)} known match, " +
        $"{Items.Count(i => i.Classification == Classification.HighConfidenceSuspicion)} high-confidence, {Items.Count(i => i.Classification == Classification.NeedsReview)} needs review, " +
        $"{Items.Count(i => i.Classification == Classification.Unverified)} unverified. {Session.Statistics.DetectionEvents} rule match event(s).";

    public FindingItem? Selected
    {
        get => _selected;
        set
        {
            if (SetProperty(ref _selected, value))
            {
                OnPropertyChanged(nameof(HasSelection));
            }
        }
    }

    public bool HasSelection => Selected is not null;

    public string SearchText
    {
        get => _searchText;
        set
        {
            if (SetProperty(ref _searchText, value))
            {
                View.Refresh();
            }
        }
    }

    public string ClassificationFilter
    {
        get => _classificationFilter;
        set
        {
            if (SetProperty(ref _classificationFilter, value))
            {
                View.Refresh();
            }
        }
    }

    public string VerificationSummary
    {
        get => _verificationSummary;
        private set => SetProperty(ref _verificationSummary, value);
    }

    public ICommand QuarantineSelectedCommand { get; }

    public ICommand VerifyCommand { get; }

    public ICommand OpenLocationCommand { get; }

    public ICommand CopyHashCommand { get; }

    public ICommand TrustCommand { get; }

    public ICommand SelectAllCommand { get; }

    public ICommand ClearSelectionCommand { get; }

    public ICommand ExportReportCommand { get; }

    public ICommand GoToScannerCommand { get; }

    public override void OnNavigatedTo()
    {
        if (Session is null)
        {
            var latest = _state.CurrentSession ?? (_history.LatestCompleted() is { } summary ? _history.Load(summary.Id) : null);
            if (latest is not null && _state.CurrentSession is null)
            {
                _state.CurrentSession = latest; // triggers Load
            }
            else
            {
                Load(latest);
            }
        }
    }

    private void Load(ScanSession? session)
    {
        Session = session;
        Items.Clear();
        foreach (var finding in session?.Findings ?? [])
        {
            Items.Add(new FindingItem(finding));
        }

        Selected = Items.FirstOrDefault();
        LoadVerification();
        OnAllPropertiesChanged();
    }

    private void LoadVerification()
    {
        VerificationItems.Clear();
        var report = Session is null ? null : _history.ListVerifications(Session.Id).FirstOrDefault();
        if (report is null)
        {
            VerificationSummary = string.Empty;
            return;
        }

        foreach (var item in report.Items.Concat(report.NewFindings))
        {
            VerificationItems.Add(item);
        }

        VerificationSummary =
            $"Verification {report.CompletedAtUtc.ToLocalTime():g}: {report.Count(VerificationOutcome.Quarantined)} quarantined, {report.Count(VerificationOutcome.Deleted)} deleted, " +
            $"{report.Count(VerificationOutcome.NoLongerPresent)} no longer present, {report.Count(VerificationOutcome.StillPresent)} still present, " +
            $"{report.Count(VerificationOutcome.PresentElsewhere)} present elsewhere, {report.Count(VerificationOutcome.OperationFailed)} failed, " +
            $"{report.Count(VerificationOutcome.NotAccessible) + report.Count(VerificationOutcome.Inconclusive)} inconclusive, {report.NewFindings.Count} related item(s) to review. " +
            string.Join(" ", report.Notes);
    }

    private bool Filter(object item)
    {
        if (item is not FindingItem finding)
        {
            return false;
        }

        var classificationOk = ClassificationFilter switch
        {
            "Known match" => finding.Classification == Classification.KnownMatch,
            "High-confidence suspicion" => finding.Classification == Classification.HighConfidenceSuspicion,
            "Needs review" => finding.Classification == Classification.NeedsReview,
            "Unverified" => finding.Classification == Classification.Unverified,
            "Likely legitimate" => finding.Classification == Classification.LikelyLegitimate,
            "Not actioned" => finding.Finding.CleanupStatus == CleanupStatus.NotActioned,
            _ => true,
        };
        if (!classificationOk)
        {
            return false;
        }

        var search = SearchText.Trim();
        return search.Length == 0 ||
               finding.Path.Contains(search, StringComparison.OrdinalIgnoreCase) ||
               finding.Family.Contains(search, StringComparison.OrdinalIgnoreCase) ||
               finding.Rules.Contains(search, StringComparison.OrdinalIgnoreCase) ||
               (finding.Finding.Sha256?.Contains(search, StringComparison.OrdinalIgnoreCase) ?? false);
    }

    private IEnumerable<FindingItem> Targets()
    {
        var ticked = Items.Where(i => i.IsSelected).ToList();
        var candidates = ticked.Count > 0 ? ticked : Selected is null ? [] : [Selected];
        return candidates.Where(i => i.CanQuarantine);
    }

    private void SetSelection(bool value)
    {
        foreach (var item in View.Cast<FindingItem>())
        {
            item.IsSelected = value && item.CanQuarantine;
        }
    }

    private async Task QuarantineSelectedAsync()
    {
        var targets = Targets().ToList();
        if (targets.Count == 0 || Session is null)
        {
            return;
        }

        var weak = targets.Where(t => t.Classification is Classification.NeedsReview or Classification.Unverified).ToList();
        var message = "The selected items will be moved into quarantine. Each copy is verified by SHA-256 before the original is removed, and every item can be restored later." +
                      (weak.Count > 0 ? $"\n\n{weak.Count} item(s) are only 'Needs review' or 'Unverified'. Make sure you reviewed their evidence." : string.Empty) +
                      "\n\nClose Minecraft and launchers first so files are not in use.";
        if (_configuration.Current.Safety.ConfirmQuarantine &&
            !_dialogs.Confirm("Quarantine selected items?", message, targets.Select(t => t.Path).ToList(), $"Quarantine {targets.Count} item(s)"))
        {
            return;
        }

        _busy = true;
        CommandManager.InvalidateRequerySuggested();
        var session = Session;
        var approvedRoots = session.Scope.Roots.Select(r => r.Path).Concat(session.Scope.Roots.Select(r => r.InstallationRoot).OfType<string>()).Distinct(PathKey.Comparer).ToList();
        try
        {
            foreach (var target in targets)
            {
                var finding = target.Finding;
                var request = new QuarantineRequest
                {
                    Path = finding.Path,
                    ApprovedRoots = approvedRoots,
                    ExpectedSha256 = finding.Sha256,
                    ExpectedSize = finding.IsDirectory ? null : finding.SizeBytes,
                    FindingId = finding.Id,
                    SessionId = session.Id,
                    RuleIds = finding.RuleMatches.Select(m => m.RuleId).ToList(),
                    Classification = finding.Classification.ToString(),
                    Family = finding.RuleMatches.FirstOrDefault()?.Family,
                };

                var results = await Task.Run(() => finding.IsDirectory ? _quarantine.QuarantineDirectory(request) : [_quarantine.Quarantine(request)]);
                var allOk = results.All(r => r.Succeeded);
                finding.CleanupStatus = allOk ? CleanupStatus.Quarantined : results.Any(r => r.BlockCode != Core.Safety.PathBlockCode.None) ? CleanupStatus.Blocked : CleanupStatus.QuarantineFailed;
                finding.CleanupMessage = allOk
                    ? $"{results.Count} file(s) quarantined and verified."
                    : string.Join(" ", results.Where(r => !r.Succeeded).Select(r => r.Message).Distinct());
                finding.QuarantineEntryId = results.FirstOrDefault(r => r.Entry is not null)?.Entry?.Id;
                target.IsSelected = false;
                target.Refresh();
            }

            _history.Save(session);
        }
        finally
        {
            _busy = false;
            CommandManager.InvalidateRequerySuggested();
        }

        var succeeded = targets.Count(t => t.Finding.CleanupStatus == CleanupStatus.Quarantined);
        _state.StatusMessage = $"{succeeded} of {targets.Count} item(s) quarantined.";
        _state.NotifyDataChanged();
        OnPropertyChanged(nameof(CountsText));

        var failures = targets.Where(t => t.Finding.CleanupStatus != CleanupStatus.Quarantined).Select(t => $"{t.Path}: {t.Finding.CleanupMessage}").ToList();
        var choice = _dialogs.Ask(new ConfirmationRequest
        {
            Title = "Quarantine finished",
            Message = $"{succeeded} of {targets.Count} item(s) were quarantined and verified." +
                      (failures.Count > 0 ? " The items below were not changed:" : string.Empty) +
                      "\n\nRun a verification scan now to confirm the results?",
            Items = failures,
            Choices = [new DialogChoice("verify", "Verify now", IsDefault: true), new DialogChoice("later", "Later", IsCancel: true)],
        });
        if (choice == "verify")
        {
            await VerifyAsync();
        }
    }

    private async Task VerifyAsync()
    {
        if (Session is not { } session)
        {
            return;
        }

        var scope = _scopes.BuildVerification(session);
        if (scope.Roots.Count == 0)
        {
            _dialogs.ShowInfo("Nothing to verify", "None of the original locations exist any more, so a verification scan cannot run.");
            return;
        }

        _busy = true;
        try
        {
            var verification = await _scanner.RunScanAsync(scope, session.Id);
            if (verification is null)
            {
                return;
            }

            var report = VerificationService.Compare(session, verification, _operations.ReadAll());
            _history.SaveVerification(report);
            LoadVerification();
            _state.NotifyDataChanged();
            _dialogs.ShowInfo("Verification finished", VerificationSummary);
        }
        finally
        {
            _busy = false;
            CommandManager.InvalidateRequerySuggested();
        }
    }

    private void CopyHash()
    {
        try
        {
            Clipboard.SetText(Selected!.Finding.Sha256!);
            _state.StatusMessage = "SHA-256 copied to the clipboard.";
        }
        catch (System.Runtime.InteropServices.ExternalException)
        {
            _state.StatusMessage = "The clipboard is in use by another program.";
        }
    }

    private void Trust()
    {
        if (Selected is not { } item || item.Finding.Sha256 is null)
        {
            return;
        }

        if (!_dialogs.Confirm("Trust this file?",
                "Future scans will not report this exact file (same SHA-256 at the same path). Documented malware is always reported regardless. Only do this after reviewing the evidence.",
                [item.Path, $"SHA-256 {item.Finding.Sha256}"], "Trust file"))
        {
            return;
        }

        var config = _configuration.CloneCurrent();
        config.Detection.TrustedExclusions.Add(new TrustedExclusion { Sha256 = item.Finding.Sha256, Path = item.Path, Note = $"Trusted by user on {DateTime.Now:yyyy-MM-dd}" });
        var result = _configuration.Save(config, "trust-file");
        _state.StatusMessage = result.Succeeded ? "The file was added to your trusted exclusions." : result.Message;
    }

    private void ExportReport()
    {
        if (Session is not null)
        {
            ReportExportFlow.Run(Session, _reports, _dialogs, _configuration.Current, _shell, _state);
        }
    }

    private void ShowShell(ShellLaunchResult result)
    {
        if (!result.Succeeded)
        {
            _dialogs.ShowError("Could not open", result.Message);
        }
    }
}
