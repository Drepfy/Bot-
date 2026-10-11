using CleanerPro.Configuration;
using CleanerPro.Core.Safety;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Logging;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Privacy;
using CleanerPro.Quarantine;
using CleanerPro.Reporting;
using CleanerPro.Scanner;
using CleanerPro.Scanner.Discovery;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace CleanerPro.App.Composition;

/// <summary>
/// Composition root. Every service is a singleton created here from the configuration; view models
/// receive them through the service provider.
/// </summary>
public static class AppServices
{
    public static ServiceProvider Build(string? dataRoot = null, Action<IServiceCollection>? configureUi = null)
    {
        var paths = new AppPaths(dataRoot);
        paths.EnsureCreated();

        // The configuration is loaded with a policy that already protects the application's own data.
        var bootstrapPolicy = PathSafetyPolicy.ForCurrentSystem([paths.DataRoot]);
        var configuration = new ConfigurationService(paths, bootstrapPolicy);
        configuration.Load();
        var config = configuration.Current;

        var loggerProvider = new JsonFileLoggerProvider(LoggerOptions(paths, config));
        configuration.ConfigurationChanged += (_, updated) => loggerProvider.UpdateOptions(LoggerOptions(paths, updated));

        var services = new ServiceCollection();
        services.AddLogging(builder =>
        {
            builder.ClearProviders();
            builder.SetMinimumLevel(LogLevel.Trace);
            builder.AddProvider(loggerProvider);
        });
        services.AddSingleton(loggerProvider);
        services.AddSingleton(TimeProvider.System);
        services.AddSingleton(paths);
        services.AddSingleton(configuration);

        // Protected locations include the application data folder and any configured quarantine/report folders.
        services.AddSingleton(_ => PathSafetyPolicy.ForCurrentSystem(
        [
            paths.DataRoot,
            EffectiveLocations.QuarantineDirectory(config, paths),
            EffectiveLocations.ReportsDirectory(config, paths),
        ]));

        services.AddSingleton(new NetworkActivityLog(paths.NetworkActivityLogFile));
        services.AddSingleton(sp => new NetworkAccessPolicy(() => sp.GetRequiredService<ConfigurationService>().Current));
        services.AddSingleton(sp => new GuardedHttpClient(sp.GetRequiredService<NetworkAccessPolicy>(), sp.GetRequiredService<NetworkActivityLog>()));

        services.AddSingleton(sp => new RuleRepository(paths,
            () => RuleUpdateService.TrustedKeys(sp.GetRequiredService<ConfigurationService>().Current),
            sp.GetRequiredService<ILogger<RuleRepository>>()));
        services.AddSingleton(sp => new RuleUpdateService(sp.GetRequiredService<RuleRepository>(), sp.GetRequiredService<GuardedHttpClient>(),
            () => sp.GetRequiredService<ConfigurationService>().Current, paths, sp.GetRequiredService<ILogger<RuleUpdateService>>()));

        services.AddSingleton(_ => new InstallationDiscoveryService(DiscoveryEnvironment.Current() with
        {
            SearchExclusions = [paths.DataRoot, EffectiveLocations.QuarantineDirectory(config, paths), EffectiveLocations.ReportsDirectory(config, paths)],
        }));
        services.AddSingleton(sp => new ScanScopeBuilder(() => sp.GetRequiredService<ConfigurationService>().Current,
            () => sp.GetRequiredService<RuleRepository>().Active.Database, paths));
        services.AddSingleton(new ScanResultCache(Path.Combine(paths.CacheDirectory, "scan-cache.json")));
        services.AddSingleton(sp => new ScanEngine(() => sp.GetRequiredService<ConfigurationService>().Current,
            () => sp.GetRequiredService<RuleRepository>().Active.Database, sp.GetRequiredService<ScanResultCache>(), sp.GetRequiredService<ILogger<ScanEngine>>()));

        services.AddSingleton(new OperationLog(paths.OperationsLogFile));
        services.AddSingleton(sp => new QuarantineService(
            () => EffectiveLocations.QuarantineDirectory(sp.GetRequiredService<ConfigurationService>().Current, paths),
            sp.GetRequiredService<PathSafetyPolicy>(), sp.GetRequiredService<OperationLog>(), sp.GetRequiredService<ILogger<QuarantineService>>()));
        services.AddSingleton(new HistoryStore(paths));
        services.AddSingleton(sp => new ReportService(() => sp.GetRequiredService<ConfigurationService>().Current, paths,
            sp.GetRequiredService<HistoryStore>(), sp.GetRequiredService<OperationLog>()));
        services.AddSingleton(sp => new ApplicationDataEraser(paths, sp.GetRequiredService<ConfigurationService>(), sp.GetRequiredService<HistoryStore>(),
            sp.GetRequiredService<ReportService>(), sp.GetRequiredService<OperationLog>(), sp.GetRequiredService<QuarantineService>(),
            [
                ("Scan cache (remembered clean files)", sp.GetRequiredService<ScanResultCache>().Clear),
                ("Network activity log", sp.GetRequiredService<NetworkActivityLog>().Clear),
            ]));
        services.AddSingleton<IShellLauncher, ShellLauncher>();

        configureUi?.Invoke(services);
        var provider = services.BuildServiceProvider();
        provider.GetRequiredService<RuleRepository>().Load();
        return provider;
    }

    private static FileLoggerOptions LoggerOptions(AppPaths paths, AppConfiguration config) => new()
    {
        Directory = paths.LogsDirectory,
        MinimumLevel = Enum.TryParse<LogLevel>(config.Logging.Level, ignoreCase: true, out var level) ? level : LogLevel.Information,
        RetentionDays = config.Logging.RetentionDays,
        MaxFileBytes = config.Logging.MaxFileMegabytes * 1024L * 1024,
        MaxTotalBytes = config.Logging.MaxTotalMegabytes * 1024L * 1024,
    };
}
