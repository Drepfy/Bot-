using System.Windows;
using System.Windows.Controls;
using CleanerPro.App.Services;

namespace CleanerPro.App.Dialogs;

/// <summary>
/// Confirmation dialog that always lists the exact affected items. Destructive choices can require a
/// typed confirmation and an acknowledgement checkbox before they are enabled.
/// </summary>
public partial class ConfirmationDialog : Window
{
    private readonly ConfirmationRequest _request;
    private readonly List<(Button Button, DialogChoice Choice)> _buttons = [];

    public ConfirmationDialog(ConfirmationRequest request)
    {
        InitializeComponent();
        _request = request;
        Title = request.Title;
        TitleText.Text = request.Title;
        MessageText.Value = request.Message;

        if (request.Items.Count > 0)
        {
            ItemsPanel.Visibility = Visibility.Visible;
            ItemsHeader.Text = request.Items.Count == 1 ? "Affected item:" : $"Affected items ({request.Items.Count}):";
            ItemsList.ItemsSource = request.Items;
        }

        if (request.AcknowledgementText is not null)
        {
            Acknowledgement.Visibility = Visibility.Visible;
            Acknowledgement.Content = request.AcknowledgementText;
        }

        if (request.TypeToConfirm is not null)
        {
            TypePanel.Visibility = Visibility.Visible;
            TypePrompt.Text = $"Type {request.TypeToConfirm} to confirm:";
        }

        foreach (var choice in request.Choices)
        {
            var button = new Button
            {
                Content = choice.Label,
                IsDefault = choice.IsDefault && !choice.IsDestructive,
                IsCancel = choice.IsCancel,
                MinWidth = 96,
                Margin = new Thickness(8, 0, 0, 0),
            };
            if (choice.IsDestructive)
            {
                button.Style = (Style)FindResource("Button.Danger");
            }
            else if (choice.IsDefault)
            {
                button.Style = (Style)FindResource("Button.Primary");
            }

            button.Click += (_, _) =>
            {
                Result = choice.Id;
                DialogResult = !choice.IsCancel;
            };
            _buttons.Add((button, choice));
            ButtonsPanel.Children.Add(button);
        }

        UpdateButtons();
        Loaded += (_, _) =>
        {
            if (TypePanel.Visibility == Visibility.Visible)
            {
                TypeBox.Focus();
            }
            else
            {
                _buttons.FirstOrDefault(b => b.Choice.IsCancel).Button?.Focus();
            }
        };
    }

    /// <summary>The id of the chosen option, or null when the window was closed.</summary>
    public string? Result { get; private set; }

    private void OnInputChanged(object sender, RoutedEventArgs e)
    {
        if (_buttons.Count > 0)
        {
            UpdateButtons();
        }
    }

    private void UpdateButtons()
    {
        var typedOk = _request.TypeToConfirm is null || string.Equals(TypeBox.Text.Trim(), _request.TypeToConfirm, StringComparison.Ordinal);
        var acknowledged = _request.AcknowledgementText is null || Acknowledgement.IsChecked == true;
        foreach (var (button, choice) in _buttons)
        {
            if (!choice.IsCancel && (choice.IsDestructive || _request.TypeToConfirm is not null || _request.AcknowledgementText is not null))
            {
                button.IsEnabled = typedOk && acknowledged;
            }
        }
    }
}
