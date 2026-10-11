using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Infrastructure;
using CleanerPro.Quarantine;

namespace CleanerPro.Reporting;

/// <summary>Saves reports locally, applies report retention and computes dashboard statistics.</summary>
public sealed class ReportService
{
    private readonly Func<AppConfiguration> _config;
    private readonly AppPaths _paths;
    private readonly HistoryStore _history;
    private readonly OperationLog _operations;
    private readonly TimeProvider _time;

    public ReportService(Func<AppConfiguration> config, AppPaths paths, HistoryStore history, OperationLog operations, TimeProvider? time = null)
    {
        _config = config;
        _paths = paths;
        _history = history;
        _operations = operations;
        _time = time ?? TimeProvider.System;
    }

    public string ReportsDirectory => EffectiveLocations.ReportsDirectory(_config(), _paths);

    public ReportDocument BuildReport(ScanSession session, RedactionLevel redaction)
    {
        var verification = _history.ListVerifications(session.Id).FirstOrDefault();
        return ReportBuilder.Build(session, _operations.ReadAll(), verification, new PathRedactor(redaction), _config().Privacy, _time);
    }

    /// <summary>Writes the report to <paramref name="destination"/> (or the reports folder) and returns the path.</summary>
    public string Export(ScanSession session, ReportFormat format, RedactionLevel redaction, string? destination = null)
    {
        var document = BuildReport(session, redaction);
        var path = destination ?? Path.Combine(ReportsDirectory, $"scan-{session.Id}{ReportExporter.Extension(format)}");
        AtomicFile.WriteAllText(path, ReportExporter.Render(document, format));
        ApplyRetention();
        return path;
    }

    public IReadOnlyList<FileInfo> ListReports()
    {
        var directory = new DirectoryInfo(ReportsDirectory);
        return directory.Exists
            ? directory.GetFiles("scan-*.*").Where(f => f.Extension is ".html" or ".txt" or ".json").OrderByDescending(f => f.LastWriteTimeUtc).ToList()
            : [];
    }

    public int DeleteAllReports()
    {
        var count = 0;
        foreach (var report in ListReports())
        {
            AtomicFile.TryDelete(report.FullName);
            count++;
        }

        return count;
    }

    public int ApplyRetention()
    {
        var settings = _config().Reports;
        var cutoff = _time.GetUtcNow().AddDays(-settings.RetentionDays);
        var removed = 0;
        var reports = ListReports();
        for (var i = 0; i < reports.Count; i++)
        {
            if (i >= settings.MaxReports || reports[i].LastWriteTimeUtc < cutoff.UtcDateTime)
            {
                AtomicFile.TryDelete(reports[i].FullName);
                removed++;
            }
        }

        removed += _history.ApplyRetention(settings.HistoryRetentionDays, settings.MaxHistorySessions, _time.GetUtcNow());
        return removed;
    }
}

/// <summary>Dashboard values. Every number comes from persisted data or the current session; nothing is sample data.</summary>
public sealed record DashboardStatistics
{
    public ScanSummary? LastScan { get; init; }

    public long FilesInspected { get; init; }

    public long UniqueDetections { get; init; }

    public int ConfirmedMatches { get; init; }

    public int SuspiciousFiles { get; init; }

    public int QuarantinedFiles { get; init; }

    public int VerifiedRemovals { get; init; }

    public long SkippedFiles { get; init; }

    public required string DatabaseVersion { get; init; }

    public static DashboardStatistics Compute(HistoryStore history, QuarantineService quarantine, string databaseVersion)
    {
        var last = history.LatestCompleted();
        var verification = last is null ? null : history.ListVerifications(last.Id).FirstOrDefault();
        return new DashboardStatistics
        {
            LastScan = last,
            FilesInspected = last?.Statistics.FilesInspected ?? 0,
            UniqueDetections = last?.Statistics.UniqueFilesFlagged ?? 0,
            ConfirmedMatches = last?.KnownMatches ?? 0,
            SuspiciousFiles = (last?.HighConfidence ?? 0) + (last?.NeedsReview ?? 0) + (last?.Unverified ?? 0),
            QuarantinedFiles = quarantine.ListEntries().Count,
            VerifiedRemovals = verification is null ? 0 : verification.Count(VerificationOutcome.Quarantined) + verification.Count(VerificationOutcome.Deleted),
            SkippedFiles = last?.Statistics.FilesSkipped ?? 0,
            DatabaseVersion = databaseVersion,
        };
    }
}
