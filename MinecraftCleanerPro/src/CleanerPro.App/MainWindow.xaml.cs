using System.ComponentModel;
using System.Windows;
using CleanerPro.App.ViewModels;
using CleanerPro.Configuration;

namespace CleanerPro.App;

public partial class MainWindow : Window
{
    private readonly MainViewModel _viewModel;
    private readonly ConfigurationService _configuration;
    private bool _closingAfterCancel;

    public MainWindow(MainViewModel viewModel, ConfigurationService configuration)
    {
        InitializeComponent();
        _viewModel = viewModel;
        _configuration = configuration;
        DataContext = viewModel;
    }

    protected override async void OnClosing(CancelEventArgs e)
    {
        if (_closingAfterCancel || !_viewModel.State.IsScanning)
        {
            base.OnClosing(e);
            return;
        }

        if (_configuration.Current.Interface.ConfirmExitDuringScan &&
            MessageBox.Show(this, "A scan is running. Closing will cancel it and keep the partial results in History. Close anyway?",
                "Scan in progress", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes)
        {
            e.Cancel = true;
            return;
        }

        // Cancel the scan cleanly (partial results are saved), then close.
        e.Cancel = true;
        IsEnabled = false;
        await _viewModel.Scanner.CancelForShutdownAsync();
        _closingAfterCancel = true;
        Close();
    }
}
