using System.Text;
using System.Windows;
using System.Windows.Threading;
using CleanerPro.App.Composition;
using CleanerPro.App.Mvvm;
using CleanerPro.App.Services;
using CleanerPro.App.ViewModels;
using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Rules;
using CleanerPro.Quarantine;
using CleanerPro.Reporting;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace CleanerPro.App;

public partial class App : Application
{
    private ServiceProvider? _services;
    private Mutex? _singleInstance;
    private ILogger<App>? _logger;
    private CommandLine _commandLine = new(null, null, null);

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        _commandLine = CommandLine.Parse(e.Args);

        if (_commandLine.SelfTestOutput is { } selfTestOutput)
        {
            int exitCode;
            try
            {
                exitCode = SelfTest.Run(selfTestOutput, _commandLine.DataRoot);
            }
            catch (Exception ex)
            {
                File.WriteAllText(selfTestOutput, "{ \"passed\": false, \"error\": " + System.Text.Json.JsonSerializer.Serialize(ex.ToString()) + " }");
                exitCode = 2;
            }

            Shutdown(exitCode);
            return;
        }

        // One instance at a time, so two processes never modify the quarantine concurrently.
        var mutexName = _commandLine.DataRoot is null
            ? @"Local\MinecraftCleanerPro.SingleInstance"
            : @"Local\MinecraftCleanerPro.Test." + Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(_commandLine.DataRoot)), 0, 8);
        _singleInstance = new Mutex(initiallyOwned: true, mutexName, out var createdNew);
        if (!createdNew)
        {
            MessageBox.Show("Minecraft Cleaner Pro is already running.", "Minecraft Cleaner Pro", MessageBoxButton.OK, MessageBoxImage.Information);
            Shutdown(0);
            return;
        }

        DispatcherUnhandledException += OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += (_, args) => LogFatal(args.ExceptionObject as Exception);
        TaskScheduler.UnobservedTaskException += (_, args) =>
        {
            _logger?.LogError(args.Exception, "Unobserved task exception");
            args.SetObserved();
        };

        try
        {
            _services = AppServices.Build(_commandLine.DataRoot, RegisterUi);
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Minecraft Cleaner Pro could not start:\n\n{ex.Message}", "Startup error", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
            return;
        }

        _logger = _services.GetRequiredService<ILogger<App>>();
        var dialogs = _services.GetRequiredService<IDialogService>();
        AsyncRelayCommand.UnhandledErrorHandler = ex =>
        {
            _logger.LogError(ex, "Command failed");
            dialogs.ShowError("Something went wrong", $"{ex.Message}\n\nThe details were written to the log. No files were changed by this error unless a result said otherwise.");
        };

        var configuration = _services.GetRequiredService<ConfigurationService>();
        ThemeManager.Apply(configuration.Current);
        _logger.LogInformation("Started {Product} {Version}", Core.AppInfo.ProductName, Core.AppInfo.Version);

        // Finish or roll back any quarantine operation that was interrupted by a crash or power loss.
        var dashboard = _services.GetRequiredService<DashboardViewModel>();
        var recovery = _services.GetRequiredService<QuarantineService>().RecoverInterruptedOperations();
        dashboard.StartupNotices.AddRange(recovery.Actions);
        try
        {
            _services.GetRequiredService<ReportService>().ApplyRetention();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _logger.LogWarning(ex, "Retention could not be applied");
        }

        var main = _services.GetRequiredService<MainViewModel>();
        var window = new MainWindow(main, configuration);
        MainWindow = window;
        window.Show();

        _services.GetRequiredService<InstallationsViewModel>().Refresh();
        dashboard.Refresh();

        var config = configuration.Current;
        if (_commandLine.SmokeUiLog is { } smokeLog)
        {
            RunSmokeTest(main, smokeLog);
        }
        else
        {
            if (config.Startup.CheckRuleUpdatesOnLaunch && !config.Privacy.OfflineMode)
            {
                _ = _services.GetRequiredService<RuleUpdateService>().CheckForUpdatesAsync(CancellationToken.None);
            }

            if (config.Startup.ScanOnLaunch)
            {
                var scanner = _services.GetRequiredService<ScannerViewModel>();
                if (config.Startup.ScanModeOnLaunch == ScanMode.Full)
                {
                    scanner.IsFull = true;
                }

                main.SelectedPage = scanner;
                scanner.RefreshScope();
                if (scanner.StartCommand.CanExecute(null))
                {
                    scanner.StartCommand.Execute(null);
                }
            }
        }
    }

    private static void RegisterUi(IServiceCollection services)
    {
        services.AddSingleton<AppState>();
        services.AddSingleton<IDialogService, DialogService>();
        services.AddSingleton<DashboardViewModel>();
        services.AddSingleton<InstallationsViewModel>();
        services.AddSingleton<ScannerViewModel>();
        services.AddSingleton<FindingsViewModel>();
        services.AddSingleton<QuarantineViewModel>();
        services.AddSingleton<HistoryViewModel>();
        services.AddSingleton<ConfigurationViewModel>();
        services.AddSingleton<PrivacyViewModel>();
        services.AddSingleton<AboutViewModel>();
        services.AddSingleton<MainViewModel>();
    }

    /// <summary>Opens every page once and writes a log; used by CI on a real Windows desktop session.</summary>
    private void RunSmokeTest(MainViewModel main, string logPath)
    {
        var log = new StringBuilder();
        var pages = main.Pages.ToList();
        var index = 0;
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(400) };
        timer.Tick += (_, _) =>
        {
            if (index < pages.Count)
            {
                main.SelectedPage = pages[index];
                log.AppendLine($"Rendered page: {pages[index].Title}");
                index++;
                return;
            }

            timer.Stop();
            log.AppendLine("SMOKE-UI: OK");
            File.WriteAllText(logPath, log.ToString());
            Shutdown(0);
        };
        timer.Start();
    }

    private void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        LogFatal(e.Exception);
        if (_commandLine.SmokeUiLog is { } smokeLog)
        {
            File.WriteAllText(smokeLog, "SMOKE-UI: FAILED\n" + e.Exception);
            e.Handled = true;
            Shutdown(2);
            return;
        }

        MessageBox.Show($"An unexpected error occurred:\n\n{e.Exception.Message}\n\nThe details were written to the log. The application will try to continue.",
            "Minecraft Cleaner Pro", MessageBoxButton.OK, MessageBoxImage.Error);
        e.Handled = true;
    }

    private void LogFatal(Exception? exception)
    {
        try
        {
            _logger?.LogCritical(exception, "Unhandled exception");
        }
        catch (Exception)
        {
            // Never throw from the last-chance handler.
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _services?.Dispose();
        if (_singleInstance is not null)
        {
            try
            {
                _singleInstance.ReleaseMutex();
            }
            catch (ApplicationException)
            {
            }

            _singleInstance.Dispose();
        }

        base.OnExit(e);
    }
}
