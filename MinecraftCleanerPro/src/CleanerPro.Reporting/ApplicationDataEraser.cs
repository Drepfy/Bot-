using CleanerPro.Configuration;
using CleanerPro.Infrastructure;
using CleanerPro.Quarantine;

namespace CleanerPro.Reporting;

/// <summary>Outcome of erasing the application's data: what was removed and anything that could not be.</summary>
public sealed record EraseResult(IReadOnlyList<string> Completed, IReadOnlyList<string> Problems)
{
    public bool Succeeded => Problems.Count == 0;
}

/// <summary>
/// Deletes everything the application has stored on this computer: scan history and verification results, saved
/// reports, quarantined files (permanently), the audit log, diagnostic logs, the scan cache, the network activity log
/// and configuration backups, and resets the configuration to its defaults. Only the application's own data folders
/// are touched. The caller must have explicit, typed confirmation from the user.
/// </summary>
public sealed class ApplicationDataEraser
{
    private readonly AppPaths _paths;
    private readonly ConfigurationService _configuration;
    private readonly HistoryStore _history;
    private readonly ReportService _reports;
    private readonly OperationLog _operations;
    private readonly QuarantineService _quarantine;
    private readonly IReadOnlyList<(string Name, Action Clear)> _otherStores;

    /// <param name="otherStores">Stores owned by other components (for example the scan cache and the network log).</param>
    public ApplicationDataEraser(AppPaths paths, ConfigurationService configuration, HistoryStore history, ReportService reports, OperationLog operations,
        QuarantineService quarantine, IReadOnlyList<(string Name, Action Clear)> otherStores)
    {
        _paths = paths;
        _configuration = configuration;
        _history = history;
        _reports = reports;
        _operations = operations;
        _quarantine = quarantine;
        _otherStores = otherStores;
    }

    /// <summary>The exact list shown to the user before anything is deleted.</summary>
    public IReadOnlyList<string> Describe()
    {
        var quarantined = _quarantine.ListEntries();
        return
        [
            $"Scan history and verification results ({_history.ListSummaries().Count} scan(s)) in {_paths.HistoryDirectory}",
            $"Saved reports in {_reports.ReportsDirectory}",
            $"Quarantined files: {quarantined.Count} item(s) in {_quarantine.RootDirectory} — deleted permanently, they cannot be restored afterwards",
            $"Audit log of quarantine, restore and deletion operations ({_paths.OperationsLogFile})",
            $"Diagnostic logs in {_paths.LogsDirectory}",
            .. _otherStores.Select(s => s.Name),
            $"Configuration: reset to defaults, and all backups in {_paths.ConfigBackupDirectory} deleted",
        ];
    }

    public EraseResult EraseAll()
    {
        var completed = new List<string>();
        var problems = new List<string>();

        void Step(string name, Func<string> action)
        {
            try
            {
                completed.Add(action());
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                problems.Add($"{name}: {ex.Message}");
            }
        }

        Step("Quarantine", () =>
        {
            var entries = _quarantine.ListEntries();
            if (entries.Count == 0)
            {
                return "Quarantine: nothing to delete.";
            }

            var plan = _quarantine.PrepareDeletion(entries.Select(e => e.Id));
            var result = _quarantine.ExecuteDeletion(plan, plan.Token);
            foreach (var failed in result.Items.Where(i => !i.Succeeded))
            {
                problems.Add($"Quarantine item {failed.EntryId}: {failed.Message}");
            }

            return $"Quarantine: {result.Message}";
        });
        Step("History", () => $"History: {_history.DeleteAll()} scan record(s) deleted.");
        Step("Reports", () => $"Reports: {_reports.DeleteAllReports()} report(s) deleted.");
        foreach (var (name, clear) in _otherStores)
        {
            Step(name, () =>
            {
                clear();
                return $"{name}: cleared.";
            });
        }

        // The audit log goes last, so the deletions above are recorded until the very end.
        Step("Audit log", () =>
        {
            _operations.Clear();
            return "Audit log: deleted.";
        });
        Step("Logs", () => $"Logs: {DeleteFiles(_paths.LogsDirectory, problems)} file(s) deleted.");
        Step("Configuration", () =>
        {
            var reset = _configuration.RestoreDefaults();
            if (!reset.Succeeded)
            {
                throw new IOException(reset.Message);
            }

            return $"Configuration: reset to defaults; {DeleteFiles(_paths.ConfigBackupDirectory, problems)} backup(s) deleted.";
        });

        return new EraseResult(completed, problems);
    }

    private static int DeleteFiles(string directory, List<string> problems)
    {
        if (!Directory.Exists(directory))
        {
            return 0;
        }

        var deleted = 0;
        foreach (var file in Directory.EnumerateFiles(directory))
        {
            try
            {
                File.Delete(file);
                deleted++;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                problems.Add($"{Path.GetFileName(file)}: {ex.Message}");
            }
        }

        return deleted;
    }
}
