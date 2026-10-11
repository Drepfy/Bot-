using System.Text.Json;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Infrastructure;

namespace CleanerPro.Reporting;

/// <summary>Small summary of a stored scan, used for the History page and the dashboard.</summary>
public sealed record ScanSummary
{
    public required string Id { get; init; }

    public required ScanMode Mode { get; init; }

    public required ScanState State { get; init; }

    public required DateTimeOffset StartedAtUtc { get; init; }

    public DateTimeOffset? CompletedAtUtc { get; init; }

    public required string RulesVersion { get; init; }

    public string? ParentSessionId { get; init; }

    public required ScanStatistics Statistics { get; init; }

    public int KnownMatches { get; init; }

    public int HighConfidence { get; init; }

    public int NeedsReview { get; init; }

    public int Unverified { get; init; }

    public int RootCount { get; init; }

    public static ScanSummary From(ScanSession session) => new()
    {
        Id = session.Id,
        Mode = session.Mode,
        State = session.State,
        StartedAtUtc = session.StartedAtUtc,
        CompletedAtUtc = session.CompletedAtUtc,
        RulesVersion = session.RulesVersion,
        ParentSessionId = session.ParentSessionId,
        Statistics = session.Statistics,
        KnownMatches = session.Findings.Count(f => f.Classification == Classification.KnownMatch),
        HighConfidence = session.Findings.Count(f => f.Classification == Classification.HighConfidenceSuspicion),
        NeedsReview = session.Findings.Count(f => f.Classification == Classification.NeedsReview),
        Unverified = session.Findings.Count(f => f.Classification == Classification.Unverified),
        RootCount = session.Scope.Roots.Count,
    };
}

/// <summary>Persists scan sessions and verification reports locally, with retention and user deletion.</summary>
public sealed class HistoryStore
{
    private readonly AppPaths _paths;
    private readonly object _gate = new();

    public HistoryStore(AppPaths paths)
    {
        _paths = paths;
    }

    private string SessionsDirectory => Path.Combine(_paths.HistoryDirectory, "sessions");

    private string VerificationsDirectory => Path.Combine(_paths.HistoryDirectory, "verifications");

    public void Save(ScanSession session)
    {
        ValidateId(session.Id);
        lock (_gate)
        {
            AtomicFile.WriteAllText(Path.Combine(SessionsDirectory, session.Id + ".json"), JsonSerializer.Serialize(session, CleanerJson.Default));
            AtomicFile.WriteAllText(Path.Combine(SessionsDirectory, session.Id + ".summary.json"), JsonSerializer.Serialize(ScanSummary.From(session), CleanerJson.Default));
        }
    }

    public ScanSession? Load(string id)
    {
        if (!IsValidId(id))
        {
            return null;
        }

        var path = Path.Combine(SessionsDirectory, id + ".json");
        try
        {
            return File.Exists(path) ? JsonSerializer.Deserialize<ScanSession>(File.ReadAllText(path), CleanerJson.Default) : null;
        }
        catch (Exception ex) when (ex is JsonException or IOException)
        {
            return null;
        }
    }

    public IReadOnlyList<ScanSummary> ListSummaries()
    {
        if (!Directory.Exists(SessionsDirectory))
        {
            return [];
        }

        var summaries = new List<ScanSummary>();
        foreach (var file in Directory.EnumerateFiles(SessionsDirectory, "*.summary.json"))
        {
            try
            {
                if (JsonSerializer.Deserialize<ScanSummary>(File.ReadAllText(file), CleanerJson.Default) is { } summary)
                {
                    summaries.Add(summary);
                }
            }
            catch (Exception ex) when (ex is JsonException or IOException)
            {
                // Damaged summaries are skipped; the full session file is still available.
            }
        }

        return summaries.OrderByDescending(s => s.StartedAtUtc).ToList();
    }

    public ScanSummary? LatestCompleted(bool includeVerification = false) =>
        ListSummaries().FirstOrDefault(s => s.State == ScanState.Completed && (includeVerification || s.Mode != ScanMode.Verification));

    public void SaveVerification(VerificationReport report)
    {
        ValidateId(report.VerificationSessionId);
        lock (_gate)
        {
            AtomicFile.WriteAllText(Path.Combine(VerificationsDirectory, report.VerificationSessionId + ".json"), JsonSerializer.Serialize(report, CleanerJson.Default));
        }
    }

    public IReadOnlyList<VerificationReport> ListVerifications(string? initialSessionId = null)
    {
        if (!Directory.Exists(VerificationsDirectory))
        {
            return [];
        }

        var reports = new List<VerificationReport>();
        foreach (var file in Directory.EnumerateFiles(VerificationsDirectory, "*.json"))
        {
            try
            {
                if (JsonSerializer.Deserialize<VerificationReport>(File.ReadAllText(file), CleanerJson.Default) is { } report &&
                    (initialSessionId is null || report.InitialSessionId == initialSessionId))
                {
                    reports.Add(report);
                }
            }
            catch (Exception ex) when (ex is JsonException or IOException)
            {
            }
        }

        return reports.OrderByDescending(r => r.CompletedAtUtc).ToList();
    }

    public bool Delete(string id)
    {
        if (!IsValidId(id))
        {
            return false;
        }

        lock (_gate)
        {
            var existed = File.Exists(Path.Combine(SessionsDirectory, id + ".json"));
            AtomicFile.TryDelete(Path.Combine(SessionsDirectory, id + ".json"));
            AtomicFile.TryDelete(Path.Combine(SessionsDirectory, id + ".summary.json"));
            AtomicFile.TryDelete(Path.Combine(VerificationsDirectory, id + ".json"));
            return existed;
        }
    }

    /// <summary>Deletes all scan history and verification reports (not the quarantine or the operations audit log).</summary>
    public int DeleteAll()
    {
        var count = 0;
        foreach (var summary in ListSummaries())
        {
            count += Delete(summary.Id) ? 1 : 0;
        }

        if (Directory.Exists(VerificationsDirectory))
        {
            foreach (var file in Directory.EnumerateFiles(VerificationsDirectory, "*.json"))
            {
                AtomicFile.TryDelete(file);
            }
        }

        return count;
    }

    public int ApplyRetention(int retentionDays, int maxSessions, DateTimeOffset now)
    {
        var removed = 0;
        var summaries = ListSummaries();
        for (var i = 0; i < summaries.Count; i++)
        {
            if (i >= maxSessions || summaries[i].StartedAtUtc < now.AddDays(-retentionDays))
            {
                removed += Delete(summaries[i].Id) ? 1 : 0;
            }
        }

        return removed;
    }

    private static bool IsValidId(string id) => !string.IsNullOrEmpty(id) && id.Length <= 64 && id.All(c => char.IsAsciiLetterOrDigit(c) || c == '-');

    private static void ValidateId(string id)
    {
        if (!IsValidId(id))
        {
            throw new ArgumentException("Invalid session id.", nameof(id));
        }
    }
}
