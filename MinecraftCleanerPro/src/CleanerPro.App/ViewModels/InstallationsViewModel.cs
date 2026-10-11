using System.Collections.ObjectModel;
using System.Windows.Input;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.Configuration;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Core.Safety;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Scanner.Discovery;

namespace CleanerPro.App.ViewModels;

public sealed class InstallationItem : ObservableObject
{
    private readonly Action<InstallationItem> _onToggled;
    private bool _isEnabled;

    public InstallationItem(MinecraftInstallation installation, bool isEnabled, Action<InstallationItem> onToggled)
    {
        Installation = installation;
        _isEnabled = isEnabled;
        _onToggled = onToggled;
    }

    public MinecraftInstallation Installation { get; }

    public string Name => Installation.Name;

    public string Launcher => Installation.Launcher.ToString();

    public string RootPath => Installation.RootPath;

    public string Loaders => Installation.ModLoaders.Count == 0 ? "Unknown" : string.Join(", ", Installation.ModLoaders);

    public string DiscoveredBy => Installation.DiscoveredBy;

    public string Notes => string.Join(" ", Installation.Notes);

    public string LastInspected => Installation.LastInspectedUtc?.ToLocalTime().ToString("g") ?? "—";

    public bool IsCustom => Installation.Launcher == LauncherKind.Custom;

    public bool IsEnabled
    {
        get => _isEnabled;
        set
        {
            if (SetProperty(ref _isEnabled, value))
            {
                _onToggled(this);
            }
        }
    }
}

/// <summary>Discovered installations, the locations that were checked, and user-defined folders.</summary>
public sealed class InstallationsViewModel : PageViewModel
{
    private readonly InstallationDiscoveryService _discovery;
    private readonly ConfigurationService _configuration;
    private readonly PathSafetyPolicy _policy;
    private readonly IDialogService _dialogs;
    private readonly IShellLauncher _shell;
    private readonly AppState _state;
    private InstallationItem? _selected;
    private bool _suppressSave;

    public InstallationsViewModel(InstallationDiscoveryService discovery, ConfigurationService configuration, PathSafetyPolicy policy,
        IDialogService dialogs, IShellLauncher shell, AppState state)
    {
        _discovery = discovery;
        _configuration = configuration;
        _policy = policy;
        _dialogs = dialogs;
        _shell = shell;
        _state = state;
        RefreshCommand = new RelayCommand(Refresh);
        AddFolderCommand = new RelayCommand(AddFolder);
        RemoveFolderCommand = new RelayCommand(RemoveFolder, () => Selected?.IsCustom == true);
        OpenFolderCommand = new RelayCommand(() => ShowResult(_shell.OpenFolder(Selected!.RootPath)), () => Selected is not null);
    }

    public override string Key => "installations";

    public override string Title => "Installations";

    public override string Icon => "\uE8B7";

    public override string Description => "Minecraft installations found from launcher metadata and folders you added. Untick an installation to leave it out of Quick and Full scans.";

    public ObservableCollection<InstallationItem> Items { get; } = [];

    public ObservableCollection<string> Notes { get; } = [];

    public ObservableCollection<string> LocationsChecked { get; } = [];

    public InstallationItem? Selected
    {
        get => _selected;
        set => SetProperty(ref _selected, value);
    }

    public bool IsEmpty => Items.Count == 0;

    public string ScopeExplanation =>
        "Only these folders (plus documented malware persistence locations, if enabled) are scanned. Drives are never scanned unless you add them yourself.";

    public ICommand RefreshCommand { get; }

    public ICommand AddFolderCommand { get; }

    public ICommand RemoveFolderCommand { get; }

    public ICommand OpenFolderCommand { get; }

    public override void OnNavigatedTo()
    {
        if (Items.Count == 0)
        {
            Refresh();
        }
    }

    public void Refresh()
    {
        var config = _configuration.Current;
        var result = _discovery.Discover(config.Scan.CustomDirectories);
        _state.Discovery = result;

        _suppressSave = true;
        Items.Clear();
        foreach (var installation in result.Installations)
        {
            var enabled = (installation.Launcher == LauncherKind.Custom || config.Scan.IncludeDiscoveredInstallations) &&
                          !config.Scan.DisabledInstallationIds.Contains(installation.Id, StringComparer.OrdinalIgnoreCase);
            Items.Add(new InstallationItem(installation, enabled, OnToggled));
        }

        _suppressSave = false;
        Notes.Clear();
        foreach (var note in result.Notes)
        {
            Notes.Add(note);
        }

        LocationsChecked.Clear();
        foreach (var location in result.LocationsChecked)
        {
            LocationsChecked.Add(location);
        }

        _state.StatusMessage = $"Discovery finished: {result.Installations.Count} installation(s) found.";
        OnPropertyChanged(nameof(IsEmpty));
    }

    private void OnToggled(InstallationItem item)
    {
        if (_suppressSave)
        {
            return;
        }

        var config = _configuration.CloneCurrent();
        config.Scan.DisabledInstallationIds.RemoveAll(id => string.Equals(id, item.Installation.Id, StringComparison.OrdinalIgnoreCase));
        if (!item.IsEnabled)
        {
            config.Scan.DisabledInstallationIds.Add(item.Installation.Id);
        }

        var result = _configuration.Save(config, "installation-toggle");
        if (!result.Succeeded)
        {
            _dialogs.ShowError("Could not save", result.Message);
        }
    }

    private void AddFolder()
    {
        var folder = _dialogs.PickFolder("Choose a Minecraft game folder or modpack folder to include in scans");
        if (folder is null)
        {
            return;
        }

        var check = _policy.ValidateScanRoot(folder);
        if (!check.IsAllowed)
        {
            _dialogs.ShowError("Folder not added", check.Reason ?? "The folder cannot be used.");
            return;
        }

        var normalized = check.NormalizedPath!;
        if (string.Equals(Path.GetPathRoot(normalized)?.TrimEnd('\\'), normalized.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase) &&
            !_dialogs.Confirm("Scan an entire drive?", $"'{normalized}' is a whole drive. Full scans of it can take a long time and read many unrelated files (read-only). Continue?"))
        {
            return;
        }

        var config = _configuration.CloneCurrent();
        if (!config.Scan.CustomDirectories.Contains(normalized, PathKey.Comparer))
        {
            config.Scan.CustomDirectories.Add(normalized);
        }

        var result = _configuration.Save(config, "add-custom-directory");
        if (!result.Succeeded)
        {
            _dialogs.ShowError("Could not save", result.Message + Environment.NewLine + string.Join(Environment.NewLine, result.Validation.Errors.Select(e => e.Message)));
            return;
        }

        Refresh();
    }

    private void RemoveFolder()
    {
        if (Selected is not { IsCustom: true } item)
        {
            return;
        }

        if (!_dialogs.Confirm("Remove folder from scans?", "The folder will no longer be scanned. No files are deleted.", [item.RootPath], "Remove"))
        {
            return;
        }

        var config = _configuration.CloneCurrent();
        config.Scan.CustomDirectories.RemoveAll(d => PathKey.IsSameOrWithin(d, item.RootPath) && PathKey.IsSameOrWithin(item.RootPath, d));
        _configuration.Save(config, "remove-custom-directory");
        Refresh();
    }

    private void ShowResult(ShellLaunchResult result)
    {
        if (!result.Succeeded)
        {
            _dialogs.ShowError("Could not open", result.Message);
        }
    }
}
