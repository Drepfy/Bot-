using System.Windows;
using CleanerPro.App.Dialogs;
using Microsoft.Win32;

namespace CleanerPro.App.Services;

/// <summary>A labelled choice in a dialog.</summary>
public sealed record DialogChoice(string Id, string Label, bool IsDefault = false, bool IsCancel = false, bool IsDestructive = false);

public sealed record ConfirmationRequest
{
    public required string Title { get; init; }

    public required string Message { get; init; }

    /// <summary>The exact items the action affects; always shown in full.</summary>
    public IReadOnlyList<string> Items { get; init; } = [];

    /// <summary>When set, the user must type this text before the confirm button is enabled.</summary>
    public string? TypeToConfirm { get; init; }

    public string? AcknowledgementText { get; init; }

    public IReadOnlyList<DialogChoice> Choices { get; init; } = [new("ok", "OK", IsDefault: true), new("cancel", "Cancel", IsCancel: true)];
}

public interface IDialogService
{
    /// <summary>Returns the id of the chosen option, or null if the dialog was closed.</summary>
    string? Ask(ConfirmationRequest request);

    bool Confirm(string title, string message, IReadOnlyList<string>? items = null, string confirmLabel = "Continue");

    void ShowInfo(string title, string message);

    void ShowError(string title, string message);

    void ShowText(string title, string text);

    string? PickFolder(string title);

    string? SaveFile(string title, string filter, string defaultFileName);
}

public sealed class DialogService : IDialogService
{
    private static Window? Owner => Application.Current?.Windows.OfType<Window>().FirstOrDefault(w => w.IsActive) ?? Application.Current?.MainWindow;

    public string? Ask(ConfirmationRequest request)
    {
        var dialog = new ConfirmationDialog(request) { Owner = Owner };
        dialog.ShowDialog();
        return dialog.Result;
    }

    public bool Confirm(string title, string message, IReadOnlyList<string>? items = null, string confirmLabel = "Continue") =>
        Ask(new ConfirmationRequest
        {
            Title = title,
            Message = message,
            Items = items ?? [],
            Choices = [new DialogChoice("yes", confirmLabel, IsDefault: true), new DialogChoice("cancel", "Cancel", IsCancel: true)],
        }) == "yes";

    public void ShowInfo(string title, string message) =>
        Ask(new ConfirmationRequest { Title = title, Message = message, Choices = [new DialogChoice("ok", "OK", IsDefault: true, IsCancel: true)] });

    public void ShowError(string title, string message) =>
        Ask(new ConfirmationRequest { Title = title, Message = message, Choices = [new DialogChoice("ok", "OK", IsDefault: true, IsCancel: true)] });

    public void ShowText(string title, string text)
    {
        var dialog = new TextViewerDialog(title, text) { Owner = Owner };
        dialog.ShowDialog();
    }

    public string? PickFolder(string title)
    {
        var dialog = new OpenFolderDialog { Title = title, Multiselect = false };
        return dialog.ShowDialog(Owner) == true ? dialog.FolderName : null;
    }

    public string? SaveFile(string title, string filter, string defaultFileName)
    {
        var dialog = new SaveFileDialog { Title = title, Filter = filter, FileName = defaultFileName, OverwritePrompt = true, AddExtension = true };
        return dialog.ShowDialog(Owner) == true ? dialog.FileName : null;
    }
}
