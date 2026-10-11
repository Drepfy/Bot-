using CleanerPro.Core;

namespace CleanerPro.Infrastructure;

/// <summary>
/// All locations the application writes to. Everything lives under one data root
/// (%LocalAppData%\MinecraftCleanerPro by default) so users can inspect or delete it easily.
/// </summary>
public sealed class AppPaths
{
    public AppPaths(string? dataRoot = null)
    {
        DataRoot = PathKey.NormalizeFullPath(dataRoot ?? DefaultDataRoot());
    }

    public string DataRoot { get; }

    public string ConfigFile => Path.Combine(DataRoot, "config.json");

    public string ConfigBackupDirectory => Path.Combine(DataRoot, "config-backups");

    public string LogsDirectory => Path.Combine(DataRoot, "logs");

    public string DefaultReportsDirectory => Path.Combine(DataRoot, "reports");

    public string HistoryDirectory => Path.Combine(DataRoot, "history");

    public string OperationsLogFile => Path.Combine(HistoryDirectory, "operations.jsonl");

    public string DefaultQuarantineDirectory => Path.Combine(DataRoot, "quarantine");

    public string RulesDirectory => Path.Combine(DataRoot, "rules");

    public string CacheDirectory => Path.Combine(DataRoot, "cache");

    public string NetworkActivityLogFile => Path.Combine(DataRoot, "network-activity.jsonl");

    public static string DefaultDataRoot()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData, Environment.SpecialFolderOption.DoNotVerify);
        if (string.IsNullOrEmpty(local))
        {
            local = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share");
        }

        return Path.Combine(local, AppInfo.DataFolderName);
    }

    public void EnsureCreated()
    {
        Directory.CreateDirectory(DataRoot);
        Directory.CreateDirectory(ConfigBackupDirectory);
        Directory.CreateDirectory(LogsDirectory);
        Directory.CreateDirectory(HistoryDirectory);
        Directory.CreateDirectory(RulesDirectory);
        Directory.CreateDirectory(CacheDirectory);
    }
}
