using System.Collections.ObjectModel;
using System.Windows.Input;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Platform;

namespace CleanerPro.App.ViewModels;

public sealed class CategoryOption : ObservableObject
{
    private bool _isEnabled;

    public CategoryOption(DetectionCategory category, bool isEnabled)
    {
        Category = category;
        _isEnabled = isEnabled;
    }

    public DetectionCategory Category { get; }

    public string Name => Category.ToString();

    public bool IsEnabled
    {
        get => _isEnabled;
        set => SetProperty(ref _isEnabled, value);
    }
}

/// <summary>
/// Edits a working copy of the configuration. Nothing is written until Save validates it; the previous file
/// is backed up first. Mandatory protections cannot be switched off here or in the file.
/// </summary>
public sealed class ConfigurationViewModel : PageViewModel
{
    private readonly ConfigurationService _configuration;
    private readonly AppPaths _paths;
    private readonly IDialogService _dialogs;
    private readonly IShellLauncher _shell;
    private readonly AppState _state;
    private AppConfiguration _working;
    private string _customDirectories = string.Empty;
    private string _excludedDirectories = string.Empty;
    private string _excludedNames = string.Empty;
    private string _extensions = string.Empty;
    private string _trustedKeys = string.Empty;
    private string _trustedExclusions = string.Empty;
    private string _loadStatus = string.Empty;

    public ConfigurationViewModel(ConfigurationService configuration, AppPaths paths, IDialogService dialogs, IShellLauncher shell, AppState state)
    {
        _configuration = configuration;
        _paths = paths;
        _dialogs = dialogs;
        _shell = shell;
        _state = state;
        _working = configuration.CloneCurrent();

        SaveCommand = new RelayCommand(Save);
        ValidateCommand = new RelayCommand(Validate);
        RestoreDefaultsCommand = new RelayCommand(RestoreDefaults);
        OpenFileCommand = new RelayCommand(OpenFile);
        ViewEffectiveCommand = new RelayCommand(() => _dialogs.ShowText("Effective configuration", _configuration.SerializeEffective()));
        ExportCommand = new RelayCommand(Export);
        ReloadCommand = new RelayCommand(Reload);
        OpenBackupsCommand = new RelayCommand(() =>
        {
            Directory.CreateDirectory(_paths.ConfigBackupDirectory);
            ShowShell(_shell.OpenFolder(_paths.ConfigBackupDirectory));
        });
        LoadFromWorking();
    }

    public override string Key => "configuration";

    public override string Title => "Configuration";

    public override string Icon => "\uE713";

    public override string Description => "All supported settings. Changes are validated and the previous configuration is backed up before saving.";

    public string FilePath => _configuration.FilePath;

    public AppConfiguration Config => _working;

    public ObservableCollection<CategoryOption> Categories { get; } = [];

    public ObservableCollection<ConfigIssue> Issues { get; } = [];

    public IReadOnlyList<ThemePreference> Themes { get; } = Enum.GetValues<ThemePreference>();

    public IReadOnlyList<ReportFormat> ReportFormats { get; } = Enum.GetValues<ReportFormat>();

    public IReadOnlyList<ScanMode> LaunchScanModes { get; } = [ScanMode.Quick, ScanMode.Full];

    public IReadOnlyList<string> LogLevels { get; } = ["Trace", "Debug", "Information", "Warning", "Error", "Critical", "None"];

    public string LoadStatus
    {
        get => _loadStatus;
        private set => SetProperty(ref _loadStatus, value);
    }

    public string CustomDirectories
    {
        get => _customDirectories;
        set => SetProperty(ref _customDirectories, value);
    }

    public string ExcludedDirectories
    {
        get => _excludedDirectories;
        set => SetProperty(ref _excludedDirectories, value);
    }

    public string ExcludedNames
    {
        get => _excludedNames;
        set => SetProperty(ref _excludedNames, value);
    }

    public string Extensions
    {
        get => _extensions;
        set => SetProperty(ref _extensions, value);
    }

    public string TrustedKeys
    {
        get => _trustedKeys;
        set => SetProperty(ref _trustedKeys, value);
    }

    /// <summary>One exclusion per line: "sha256" or "sha256 | path".</summary>
    public string TrustedExclusions
    {
        get => _trustedExclusions;
        set => SetProperty(ref _trustedExclusions, value);
    }

    public ICommand SaveCommand { get; }

    public ICommand ValidateCommand { get; }

    public ICommand RestoreDefaultsCommand { get; }

    public ICommand OpenFileCommand { get; }

    public ICommand ViewEffectiveCommand { get; }

    public ICommand ExportCommand { get; }

    public ICommand ReloadCommand { get; }

    public ICommand OpenBackupsCommand { get; }

    public override void OnNavigatedTo()
    {
        UpdateLoadStatus();
    }

    private void LoadFromWorking()
    {
        Categories.Clear();
        foreach (var category in Enum.GetValues<DetectionCategory>())
        {
            Categories.Add(new CategoryOption(category, _working.Detection.EnabledCategories.Contains(category)));
        }

        CustomDirectories = string.Join(Environment.NewLine, _working.Scan.CustomDirectories);
        ExcludedDirectories = string.Join(Environment.NewLine, _working.Scan.ExcludedDirectories);
        ExcludedNames = string.Join(Environment.NewLine, _working.Scan.ExcludedDirectoryNames);
        Extensions = string.Join(" ", _working.Scan.FileExtensions);
        TrustedKeys = string.Join(Environment.NewLine, _working.RuleUpdates.AdditionalTrustedPublicKeys);
        TrustedExclusions = string.Join(Environment.NewLine, _working.Detection.TrustedExclusions.Select(e => e.Path is null ? e.Sha256 : $"{e.Sha256} | {e.Path}"));
        OnPropertyChanged(nameof(Config));
        UpdateLoadStatus();
    }

    private void UpdateLoadStatus()
    {
        var load = _configuration.LastLoad;
        LoadStatus = load.UsingSafeDefaults
            ? $"Safe defaults are active because the file could not be used: {load.FailureMessage}"
            : load.Validation.Warnings.Any()
                ? $"Loaded with {load.Validation.Warnings.Count()} warning(s)."
                : "Loaded and valid.";
        Issues.Clear();
        foreach (var issue in load.Validation.Issues)
        {
            Issues.Add(issue);
        }
    }

    private AppConfiguration BuildFromForm()
    {
        static List<string> Lines(string text) => text.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();

        var config = ConfigurationService.Clone(_working);
        config.Scan.CustomDirectories = Lines(CustomDirectories);
        config.Scan.ExcludedDirectories = Lines(ExcludedDirectories);
        config.Scan.ExcludedDirectoryNames = Lines(ExcludedNames);
        config.Scan.FileExtensions = Extensions.Split([' ', ',', ';', '\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
        config.RuleUpdates.AdditionalTrustedPublicKeys = Lines(TrustedKeys);
        config.Detection.EnabledCategories = Categories.Where(c => c.IsEnabled).Select(c => c.Category).ToList();
        var previous = _working.Detection.TrustedExclusions;
        config.Detection.TrustedExclusions = Lines(TrustedExclusions).Select(line =>
        {
            var parts = line.Split('|', 2, StringSplitOptions.TrimEntries);
            var sha = parts[0].Length == 0 ? null : parts[0];
            var path = parts.Length > 1 && parts[1].Length > 0 ? parts[1] : null;
            var note = previous.FirstOrDefault(p => p.Sha256 == sha && p.Path == path)?.Note;
            return new TrustedExclusion { Sha256 = sha, Path = path, Note = note };
        }).ToList();
        return config;
    }

    private void ShowIssues(ConfigValidationResult validation)
    {
        Issues.Clear();
        foreach (var issue in validation.Issues)
        {
            Issues.Add(issue);
        }
    }

    private void Validate()
    {
        var formValidation = _configuration.Validate(BuildFromForm());
        ShowIssues(formValidation);
        var fileValidation = _configuration.ValidateFile();
        LoadStatus = $"Form: {(formValidation.IsValid ? "valid" : $"{formValidation.Errors.Count()} error(s)")}, {formValidation.Warnings.Count()} warning(s). " +
                     $"File on disk: {(fileValidation.IsValid ? "valid" : $"{fileValidation.Errors.Count()} error(s)")}.";
        if (!fileValidation.IsValid)
        {
            foreach (var issue in fileValidation.Errors)
            {
                Issues.Add(issue with { Setting = "file: " + issue.Setting });
            }
        }
    }

    private void Save()
    {
        var config = BuildFromForm();
        var result = _configuration.Save(config, "settings-page");
        ShowIssues(result.Validation);
        if (!result.Succeeded)
        {
            LoadStatus = result.Message;
            _dialogs.ShowError("Configuration not saved", result.Message + " See the issues list for how to fix each error.");
            return;
        }

        _working = _configuration.CloneCurrent();
        LoadFromWorking();
        LoadStatus = result.Message;
        ThemeManager.Apply(_configuration.Current);
        _state.StatusMessage = "Configuration saved.";
        _state.NotifyDataChanged();
    }

    private void RestoreDefaults()
    {
        if (!_dialogs.Confirm("Restore default configuration?", "All settings return to their defaults. The current file is backed up first.", [_configuration.FilePath], "Restore defaults"))
        {
            return;
        }

        var result = _configuration.RestoreDefaults();
        _working = _configuration.CloneCurrent();
        LoadFromWorking();
        LoadStatus = result.Message;
        ThemeManager.Apply(_configuration.Current);
    }

    private void OpenFile()
    {
        if (!File.Exists(_configuration.FilePath))
        {
            _configuration.Load();
        }

        var result = _shell.OpenFile(_configuration.FilePath);
        ShowShell(result);
        if (result.Succeeded)
        {
            _state.StatusMessage = $"{result.Message} Choose 'Reload' after saving your edits.";
        }
    }

    private void Export()
    {
        var destination = _dialogs.SaveFile("Export configuration", "JSON file (*.json)|*.json", "MinecraftCleanerPro-config.json");
        if (destination is null)
        {
            return;
        }

        try
        {
            _configuration.Export(destination);
            _state.StatusMessage = $"Configuration exported to {destination}. It may contain folder paths from this computer.";
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _dialogs.ShowError("Export failed", ex.Message);
        }
    }

    private void Reload()
    {
        if (!_dialogs.Confirm("Reload configuration?", "Unsaved changes on this page are discarded and the file is read again from disk.", [_configuration.FilePath], "Reload"))
        {
            return;
        }

        var result = _configuration.Load();
        _working = _configuration.CloneCurrent();
        LoadFromWorking();
        ThemeManager.Apply(_configuration.Current);
        if (result.UsingSafeDefaults)
        {
            _dialogs.ShowError("Configuration problem", result.FailureMessage ?? "The file could not be used. Safe defaults are active.");
        }

        _state.NotifyDataChanged();
    }

    private void ShowShell(ShellLaunchResult result)
    {
        if (!result.Succeeded)
        {
            _dialogs.ShowError("Could not open", result.Message);
        }
    }
}
