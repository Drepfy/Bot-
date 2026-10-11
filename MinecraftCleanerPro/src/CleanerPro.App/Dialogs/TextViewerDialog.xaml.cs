using System.Windows;
using CleanerPro.App.Controls;

namespace CleanerPro.App.Dialogs;

/// <summary>
/// Read-only text (configuration, logs). Private values such as the user name are replaced by blocks until
/// "Show private information" is pressed; copying copies exactly what is shown.
/// </summary>
public partial class TextViewerDialog : Window
{
    private readonly string _text;

    public TextViewerDialog(string title, string text)
    {
        InitializeComponent();
        Title = title;
        _text = text;
        RevealToggle.Visibility = PrivacyDisplay.HidePrivateInformation && PrivacyDisplay.Masker.ContainsPrivateData(text) ? Visibility.Visible : Visibility.Collapsed;
        ShowText();
    }

    private void ShowText() =>
        Body.Text = PrivacyDisplay.HidePrivateInformation && RevealToggle.IsChecked != true ? PrivacyDisplay.Masker.Mask(_text) : _text;

    private void OnRevealChanged(object sender, RoutedEventArgs e) => ShowText();

    private void OnCopy(object sender, RoutedEventArgs e)
    {
        try
        {
            Clipboard.SetText(Body.Text);
        }
        catch (System.Runtime.InteropServices.ExternalException)
        {
            // The clipboard can be locked by another application; copying is a convenience only.
        }
    }

    private void OnClose(object sender, RoutedEventArgs e) => Close();
}
