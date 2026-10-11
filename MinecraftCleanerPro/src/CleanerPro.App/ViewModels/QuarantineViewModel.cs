using System.Collections.ObjectModel;
using System.Windows.Input;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Quarantine;

namespace CleanerPro.App.ViewModels;

public sealed class QuarantineItem : ObservableObject
{
    private bool _isSelected;
    private string _integrity = "Not checked";

    public QuarantineItem(QuarantineEntry entry)
    {
        Entry = entry;
    }

    public QuarantineEntry Entry { get; }

    public bool IsSelected
    {
        get => _isSelected;
        set => SetProperty(ref _isSelected, value);
    }

    public string OriginalPath => Entry.OriginalPath;

    public string Name => Entry.OriginalName;

    public string Size => Converters.BytesConverter.Format(Entry.Size);

    public DateTimeOffset QuarantinedAt => Entry.QuarantinedAtUtc.ToLocalTime();

    public string Family => Entry.Family ?? "—";

    public string Rules => string.Join(", ", Entry.RuleIds);

    public string Sha256 => Entry.Sha256;

    public string Integrity
    {
        get => _integrity;
        set => SetProperty(ref _integrity, value);
    }
}

/// <summary>Quarantined items: integrity checks, restore (never overwriting) and confirmed permanent deletion.</summary>
public sealed class QuarantineViewModel : PageViewModel
{
    private readonly QuarantineService _quarantine;
    private readonly IDialogService _dialogs;
    private readonly IShellLauncher _shell;
    private readonly AppState _state;
    private QuarantineItem? _selected;

    public QuarantineViewModel(QuarantineService quarantine, IDialogService dialogs, IShellLauncher shell, AppState state)
    {
        _quarantine = quarantine;
        _dialogs = dialogs;
        _shell = shell;
        _state = state;
        RefreshCommand = new RelayCommand(Refresh);
        VerifyCommand = new AsyncRelayCommand(VerifyAllAsync, () => Items.Count > 0);
        RestoreCommand = new AsyncRelayCommand(RestoreAsync, () => Selected is not null);
        DeleteCommand = new RelayCommand(DeletePermanently, () => Items.Any(i => i.IsSelected) || Selected is not null);
        OpenFolderCommand = new RelayCommand(() =>
        {
            Directory.CreateDirectory(_quarantine.RootDirectory);
            var result = _shell.OpenFolder(_quarantine.RootDirectory);
            if (!result.Succeeded)
            {
                _dialogs.ShowError("Could not open", result.Message);
            }
        });
        _state.DataChanged += (_, _) => Refresh();
    }

    public override string Key => "quarantine";

    public override string Title => "Quarantine";

    public override string Icon => "\uE72E";

    public override string Description => "Files moved out of your Minecraft folders. They are stored encoded so they cannot run, can be restored at any time, and are only deleted permanently after you confirm the exact items.";

    public ObservableCollection<QuarantineItem> Items { get; } = [];

    public QuarantineItem? Selected
    {
        get => _selected;
        set => SetProperty(ref _selected, value);
    }

    public bool IsEmpty => Items.Count == 0;

    public string Location => _quarantine.RootDirectory;

    public ICommand RefreshCommand { get; }

    public ICommand VerifyCommand { get; }

    public ICommand RestoreCommand { get; }

    public ICommand DeleteCommand { get; }

    public ICommand OpenFolderCommand { get; }

    public override void OnNavigatedTo() => Refresh();

    public void Refresh()
    {
        var selectedId = Selected?.Entry.Id;
        Items.Clear();
        foreach (var entry in _quarantine.ListEntries())
        {
            Items.Add(new QuarantineItem(entry));
        }

        Selected = Items.FirstOrDefault(i => i.Entry.Id == selectedId) ?? Items.FirstOrDefault();
        OnPropertyChanged(nameof(IsEmpty));
        OnPropertyChanged(nameof(Location));
    }

    private async Task VerifyAllAsync()
    {
        foreach (var item in Items)
        {
            var status = await Task.Run(() => _quarantine.VerifyIntegrity(item.Entry.Id));
            item.Integrity = status switch
            {
                IntegrityStatus.Verified => "Verified",
                IntegrityStatus.PayloadMissing => "Missing (possibly removed by antivirus)",
                IntegrityStatus.HashMismatch => "Damaged",
                _ => status.ToString(),
            };
        }

        _state.StatusMessage = $"Integrity checked for {Items.Count} item(s): {Items.Count(i => i.Integrity == "Verified")} verified.";
    }

    private async Task RestoreAsync()
    {
        if (Selected is not { } item)
        {
            return;
        }

        if (_dialogs.Ask(new ConfirmationRequest
            {
                Title = "Restore file?",
                Message = "The file will be returned to its original location after its integrity is verified. If it was flagged as a cheat or malware, restoring it puts it back where Minecraft can load it.",
                Items = [item.OriginalPath],
                Choices = [new DialogChoice("restore", "Restore", IsDefault: true), new DialogChoice("cancel", "Cancel", IsCancel: true)],
            }) != "restore")
        {
            return;
        }

        var result = await Task.Run(() => _quarantine.Restore(new RestoreRequest(item.Entry.Id, RestoreMode.OriginalLocation)));
        if (result.Conflict)
        {
            var choice = _dialogs.Ask(new ConfirmationRequest
            {
                Title = "A file already exists there",
                Message = "Another file is already at the original location. It will not be overwritten. How do you want to restore?",
                Items = [result.ConflictPath ?? item.OriginalPath],
                Choices =
                [
                    new DialogChoice("rename", "Restore with a new name", IsDefault: true),
                    new DialogChoice("folder", "Choose another folder…"),
                    new DialogChoice("cancel", "Cancel", IsCancel: true),
                ],
            });
            if (choice == "rename")
            {
                result = await Task.Run(() => _quarantine.Restore(new RestoreRequest(item.Entry.Id, RestoreMode.OriginalLocationWithNewName)));
            }
            else if (choice == "folder" && _dialogs.PickFolder("Restore the file into this folder") is { } folder)
            {
                result = await Task.Run(() => _quarantine.Restore(new RestoreRequest(item.Entry.Id, RestoreMode.AlternateDirectory, folder)));
            }
            else
            {
                return;
            }
        }

        if (result.Succeeded)
        {
            _state.StatusMessage = result.Message;
            _dialogs.ShowInfo("Restored", result.Message);
        }
        else
        {
            _dialogs.ShowError("Restore failed", result.Message);
        }

        _state.NotifyDataChanged();
    }

    private void DeletePermanently()
    {
        var ids = Items.Where(i => i.IsSelected).Select(i => i.Entry.Id).ToList();
        if (ids.Count == 0 && Selected is not null)
        {
            ids.Add(Selected.Entry.Id);
        }

        var plan = _quarantine.PrepareDeletion(ids);
        if (plan.Targets.Count == 0)
        {
            return;
        }

        var answer = _dialogs.Ask(new ConfirmationRequest
        {
            Title = "Permanently delete quarantined files?",
            Message = "These quarantined copies will be deleted permanently and cannot be restored afterwards. Only the items listed below are affected.",
            Items = plan.Targets.Select(t => $"{t.OriginalPath}  ({Converters.BytesConverter.Format(t.Size)}, SHA-256 {t.Sha256[..16]}…)").ToList(),
            AcknowledgementText = "I understand this cannot be undone.",
            TypeToConfirm = "DELETE",
            Choices = [new DialogChoice("delete", $"Delete {plan.Targets.Count} item(s) permanently", IsDestructive: true), new DialogChoice("cancel", "Cancel", IsCancel: true)],
        });
        if (answer != "delete")
        {
            return;
        }

        var result = _quarantine.ExecuteDeletion(plan, plan.Token);
        _state.StatusMessage = result.Message;
        var failures = result.Items.Where(i => !i.Succeeded).Select(i => $"{i.EntryId}: {i.Message}").ToList();
        if (failures.Count > 0 || !result.Executed)
        {
            _dialogs.Ask(new ConfirmationRequest
            {
                Title = "Deletion result",
                Message = result.Message,
                Items = failures,
                Choices = [new DialogChoice("ok", "OK", IsDefault: true, IsCancel: true)],
            });
        }

        _state.NotifyDataChanged();
    }
}
