using System.Windows;

namespace CleanerPro.App.Dialogs;

public partial class TextViewerDialog : Window
{
    public TextViewerDialog(string title, string text)
    {
        InitializeComponent();
        Title = title;
        Body.Text = text;
    }

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
