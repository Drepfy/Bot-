using System.Collections.ObjectModel;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.Configuration;
using CleanerPro.Detection.Rules;

namespace CleanerPro.App.ViewModels;

/// <summary>Shell: navigation between pages and the status bar.</summary>
public sealed class MainViewModel : ObservableObject
{
    private readonly ConfigurationService _configuration;
    private readonly RuleRepository _rules;
    private PageViewModel _selectedPage;

    public MainViewModel(AppState state, ConfigurationService configuration, RuleRepository rules, DashboardViewModel dashboard, InstallationsViewModel installations,
        ScannerViewModel scanner, FindingsViewModel findings, QuarantineViewModel quarantine, HistoryViewModel history,
        ConfigurationViewModel settings, PrivacyViewModel privacy, AboutViewModel about)
    {
        State = state;
        _configuration = configuration;
        _rules = rules;
        Scanner = scanner;
        Pages = [dashboard, installations, scanner, findings, quarantine, history, settings, privacy, about];
        _selectedPage = dashboard;
        state.NavigationRequested += (_, key) => SelectedPage = Pages.FirstOrDefault(p => p.Key == key) ?? SelectedPage;
        state.DataChanged += (_, _) => OnPropertyChanged(nameof(NetworkStatus));
        _rules.RulesChanged += (_, _) => OnPropertyChanged(nameof(RulesStatus));
    }

    public AppState State { get; }

    public ScannerViewModel Scanner { get; }

    public ObservableCollection<PageViewModel> Pages { get; }

    public PageViewModel SelectedPage
    {
        get => _selectedPage;
        set
        {
            if (value is not null && SetProperty(ref _selectedPage, value))
            {
                value.OnNavigatedTo();
            }
        }
    }

    public string RulesStatus => $"Rules {_rules.Active.Database.DisplayVersion} ({(_rules.Active.Source == RuleSource.Bundled ? "bundled" : "signed update")})";

    public string NetworkStatus => _configuration.Current.Privacy.OfflineMode ? "Offline mode" : "Online updates allowed";

    public string WindowTitle => $"{Core.AppInfo.ProductName} {Core.AppInfo.Version}";
}
