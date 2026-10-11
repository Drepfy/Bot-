using CleanerPro.App.Mvvm;
using CleanerPro.Core.Models;

namespace CleanerPro.App.Services;

/// <summary>Shared, observable application state (current scan session, discovery results, busy flags).</summary>
public sealed class AppState : ObservableObject
{
    private DiscoveryResult _discovery = new();
    private ScanSession? _currentSession;
    private bool _isScanning;
    private string _statusMessage = "Ready.";

    public DiscoveryResult Discovery
    {
        get => _discovery;
        set
        {
            if (SetProperty(ref _discovery, value))
            {
                DiscoveryChanged?.Invoke(this, EventArgs.Empty);
            }
        }
    }

    /// <summary>The session shown on the Findings page (the latest scan, or one opened from History).</summary>
    public ScanSession? CurrentSession
    {
        get => _currentSession;
        set
        {
            if (SetProperty(ref _currentSession, value))
            {
                SessionChanged?.Invoke(this, EventArgs.Empty);
            }
        }
    }

    public bool IsScanning
    {
        get => _isScanning;
        set => SetProperty(ref _isScanning, value);
    }

    public string StatusMessage
    {
        get => _statusMessage;
        set => SetProperty(ref _statusMessage, value);
    }

    public event EventHandler? SessionChanged;

    public event EventHandler? DiscoveryChanged;

    /// <summary>Raised after quarantine, restore, deletion or history changes so pages can refresh.</summary>
    public event EventHandler? DataChanged;

    public event EventHandler<string>? NavigationRequested;

    public void NotifyDataChanged() => DataChanged?.Invoke(this, EventArgs.Empty);

    public void Navigate(string pageKey) => NavigationRequested?.Invoke(this, pageKey);
}
