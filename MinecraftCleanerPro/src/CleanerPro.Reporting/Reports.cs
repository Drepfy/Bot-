using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;
using CleanerPro.Configuration;
using CleanerPro.Core;
using CleanerPro.Core.Models;

namespace CleanerPro.Reporting;

public enum RedactionLevel
{
    /// <summary>Full paths, as stored. Only for reports that stay on this computer.</summary>
    None,

    /// <summary>User profile, AppData folders, user name and computer name replaced with placeholders.</summary>
    PersonalPaths,

    /// <summary>Only file names and installation names are kept.</summary>
    FileNamesOnly,
}

/// <summary>Removes personal information from paths before a report is shared.</summary>
public sealed class PathRedactor
{
    private readonly RedactionLevel _level;
    private readonly List<(string Value, string Replacement)> _replacements = [];

    public PathRedactor(RedactionLevel level, IEnumerable<(string Value, string Replacement)>? replacements = null)
    {
        _level = level;
        var list = replacements?.ToList() ?? DefaultReplacements();
        _replacements = list.Where(r => !string.IsNullOrWhiteSpace(r.Value) && r.Value.Length >= 2)
            .OrderByDescending(r => r.Value.Length)
            .ToList();
    }

    public RedactionLevel Level => _level;

    public string Redact(string? text)
    {
        if (string.IsNullOrEmpty(text) || _level == RedactionLevel.None)
        {
            return text ?? string.Empty;
        }

        var result = text;
        foreach (var (value, replacement) in _replacements)
        {
            result = result.Replace(value, replacement, StringComparison.OrdinalIgnoreCase);
        }

        return result;
    }

    public string RedactPath(string? path)
    {
        if (string.IsNullOrEmpty(path))
        {
            return string.Empty;
        }

        return _level switch
        {
            RedactionLevel.None => path,
            RedactionLevel.FileNamesOnly => Path.GetFileName(path.TrimEnd('\\', '/')) is { Length: > 0 } name ? "…" + Path.DirectorySeparatorChar + name : "…",
            _ => Redact(path),
        };
    }

    private static List<(string, string)> DefaultReplacements()
    {
        var list = new List<(string, string)>
        {
            (Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "%LOCALAPPDATA%"),
            (Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "%APPDATA%"),
            (Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "%USERPROFILE%"),
        };
        if (Environment.UserName is { Length: >= 3 } user)
        {
            list.Add((user, "<user>"));
        }

        if (Environment.MachineName is { Length: >= 3 } machine)
        {
            list.Add((machine, "<computer>"));
        }

        return list;
    }
}

/// <summary>Everything a report contains. Built from persisted application data only.</summary>
public sealed record ReportDocument
{
    public required string Title { get; init; }

    public required DateTimeOffset GeneratedAtUtc { get; init; }

    public required string AppVersion { get; init; }

    public required string RulesVersion { get; init; }

    public required RedactionLevel Redaction { get; init; }

    public string? UserName { get; init; }

    public string? ComputerName { get; init; }

    public required string SessionId { get; init; }

    public required ScanMode Mode { get; init; }

    public required ScanState State { get; init; }

    public required DateTimeOffset StartedAtUtc { get; init; }

    public DateTimeOffset? CompletedAtUtc { get; init; }

    public required IReadOnlyList<ScanRoot> Scope { get; init; }

    public required ScanStatistics Statistics { get; init; }

    public required IReadOnlyDictionary<string, int> ClassificationBreakdown { get; init; }

    public required IReadOnlyList<Finding> Findings { get; init; }

    public required IReadOnlyList<OperationRecord> Operations { get; init; }

    public required IReadOnlyList<SkippedItem> Skipped { get; init; }

    public long SkippedTotal { get; init; }

    public VerificationReport? Verification { get; init; }

    public required IReadOnlyList<string> Notes { get; init; }

    public required IReadOnlyList<string> Limitations { get; init; }
}

public static class ReportBuilder
{
    public static ReportDocument Build(ScanSession session, IReadOnlyList<OperationRecord> allOperations, VerificationReport? verification,
        PathRedactor redactor, PrivacySettings privacy, TimeProvider? time = null)
    {
        var findingIds = session.Findings.Select(f => f.Id).ToHashSet(StringComparer.Ordinal);
        var findingPaths = session.Findings.Select(f => f.Path).ToHashSet(PathKey.Comparer);
        var operations = allOperations
            .Where(o => o.SessionId == session.Id || (o.FindingId is not null && findingIds.Contains(o.FindingId)) ||
                        (o.Path is not null && findingPaths.Contains(o.Path)))
            .OrderBy(o => o.TimestampUtc)
            .Select(o => o with { Path = redactor.RedactPath(o.Path), Message = redactor.Redact(o.Message) })
            .ToList();

        var findings = session.Findings.Select(f => RedactFinding(f, redactor)).ToList();
        var breakdown = Enum.GetValues<Classification>().ToDictionary(c => ClassificationOrder.ToDisplay(c), c => session.Findings.Count(f => f.Classification == c));

        var limitations = new List<string>(session.Limitations.Select(redactor.Redact));
        if (redactor.Level != RedactionLevel.None)
        {
            limitations.Add("Paths in this report were redacted to remove personal information.");
        }

        return new ReportDocument
        {
            Title = $"{AppInfo.ProductName} scan report",
            GeneratedAtUtc = (time ?? TimeProvider.System).GetUtcNow(),
            AppVersion = session.AppVersion,
            RulesVersion = session.RulesVersion,
            Redaction = redactor.Level,
            UserName = privacy.IncludeUserNameInReports ? Environment.UserName : null,
            ComputerName = privacy.IncludeMachineNameInReports ? Environment.MachineName : null,
            SessionId = session.Id,
            Mode = session.Mode,
            State = session.State,
            StartedAtUtc = session.StartedAtUtc,
            CompletedAtUtc = session.CompletedAtUtc,
            Scope = session.Scope.Roots.Select(r => r with { Path = redactor.RedactPath(r.Path), InstallationRoot = redactor.RedactPath(r.InstallationRoot), Reason = redactor.Redact(r.Reason) }).ToList(),
            Statistics = session.Statistics,
            ClassificationBreakdown = breakdown,
            Findings = findings,
            Operations = operations,
            Skipped = session.Skipped.Select(s => s with { Path = redactor.RedactPath(s.Path), Detail = redactor.Redact(s.Detail) }).ToList(),
            SkippedTotal = session.SkippedTotal,
            Verification = verification is null ? null : verification with
            {
                Items = verification.Items.Select(i => i with { Path = redactor.RedactPath(i.Path), Detail = redactor.Redact(i.Detail) }).ToList(),
                NewFindings = verification.NewFindings.Select(i => i with { Path = redactor.RedactPath(i.Path), Detail = redactor.Redact(i.Detail) }).ToList(),
                InaccessiblePaths = verification.InaccessiblePaths.Select(redactor.RedactPath).ToList(),
            },
            Notes = session.Notes.Select(redactor.Redact).ToList(),
            Limitations = limitations,
        };
    }

    private static Finding RedactFinding(Finding finding, PathRedactor redactor) => new()
    {
        Id = finding.Id,
        Path = redactor.RedactPath(finding.Path),
        IsDirectory = finding.IsDirectory,
        IsSystemArtifact = finding.IsSystemArtifact,
        SizeBytes = finding.SizeBytes,
        LastWriteUtc = finding.LastWriteUtc,
        Sha256 = finding.Sha256,
        Sha1 = finding.Sha1,
        InstallationId = finding.InstallationId,
        InstallationName = redactor.Redact(finding.InstallationName),
        Identity = finding.Identity,
        Classification = finding.Classification,
        Confidence = finding.Confidence,
        Severity = finding.Severity,
        Reputation = finding.Reputation,
        RecommendedAction = finding.RecommendedAction,
        ConfidenceRationale = finding.ConfidenceRationale,
        RuleMatches = finding.RuleMatches,
        Evidence = finding.Evidence.Select(e => e with { Description = redactor.Redact(e.Description), MatchedValue = redactor.Redact(e.MatchedValue), Location = redactor.Redact(e.Location) }).ToList(),
        Limitations = finding.Limitations.Select(redactor.Redact).ToList(),
        CleanupStatus = finding.CleanupStatus,
        CleanupMessage = redactor.Redact(finding.CleanupMessage),
        QuarantineEntryId = finding.QuarantineEntryId,
    };
}

/// <summary>Writes reports as JSON, plain text or self-contained HTML (no scripts, no external resources).</summary>
public static class ReportExporter
{
    public static string Render(ReportDocument report, ReportFormat format) => format switch
    {
        ReportFormat.Json => JsonSerializer.Serialize(report, CleanerJson.Default),
        ReportFormat.Txt => RenderText(report),
        ReportFormat.Html => RenderHtml(report),
        _ => throw new ArgumentOutOfRangeException(nameof(format)),
    };

    public static string Extension(ReportFormat format) => format switch
    {
        ReportFormat.Json => ".json",
        ReportFormat.Txt => ".txt",
        _ => ".html",
    };

    private static string Time(DateTimeOffset? value) => value?.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss zzz", CultureInfo.InvariantCulture) ?? "—";

    private static string RenderText(ReportDocument r)
    {
        var s = new StringBuilder();
        s.AppendLine(r.Title.ToUpperInvariant());
        s.AppendLine(new string('=', r.Title.Length));
        s.AppendLine($"Generated:          {Time(r.GeneratedAtUtc)}");
        s.AppendLine($"Application:        {r.AppVersion}");
        s.AppendLine($"Rule database:      {r.RulesVersion}");
        s.AppendLine($"Scan id:            {r.SessionId} ({r.Mode}, {r.State})");
        s.AppendLine($"Started / finished: {Time(r.StartedAtUtc)} / {Time(r.CompletedAtUtc)}");
        if (r.UserName is not null || r.ComputerName is not null)
        {
            s.AppendLine($"User / computer:    {r.UserName ?? "—"} / {r.ComputerName ?? "—"}");
        }

        s.AppendLine($"Path redaction:     {r.Redaction}");
        s.AppendLine();
        s.AppendLine("SCOPE");
        foreach (var root in r.Scope)
        {
            s.AppendLine($"  - {root.Path}{(root.Recursive ? string.Empty : " (not recursive)")} — {root.Reason}");
        }

        var st = r.Statistics;
        s.AppendLine();
        s.AppendLine("STATISTICS");
        s.AppendLine($"  Files discovered (inspectable types): {st.FilesDiscovered}");
        s.AppendLine($"  Files inspected:                      {st.FilesInspected} ({st.CacheHits} unchanged since a previous scan)");
        s.AppendLine($"  Files skipped:                        {st.FilesSkipped}");
        s.AppendLine($"  Other files seen (not inspected):     {st.FilesNotApplicable}");
        s.AppendLine($"  Archives inspected:                   {st.ArchivesInspected}");
        s.AppendLine($"  Unique items flagged:                 {st.UniqueFilesFlagged}");
        s.AppendLine($"  Detection events (rule matches):      {st.DetectionEvents}");
        s.AppendLine();
        s.AppendLine("CLASSIFICATION BREAKDOWN");
        foreach (var (name, count) in r.ClassificationBreakdown)
        {
            s.AppendLine($"  {name,-26} {count}");
        }

        s.AppendLine();
        s.AppendLine($"FINDINGS ({r.Findings.Count} unique items)");
        var index = 1;
        foreach (var f in r.Findings)
        {
            s.AppendLine($"  [{index++}] {ClassificationOrder.ToDisplay(f.Classification)} — {f.Path}");
            s.AppendLine($"      Rules:      {string.Join(", ", f.RuleMatches.Select(m => $"{m.RuleId} v{m.RuleVersion} ({m.Family})"))}");
            s.AppendLine($"      Confidence: {f.Confidence}   Severity: {f.Severity}   Reputation: {f.Reputation}");
            s.AppendLine($"      Action:     {ClassificationOrder.ToDisplay(f.RecommendedAction)}   Cleanup status: {ClassificationOrder.ToDisplay(f.CleanupStatus)}");
            if (f.Sha256 is not null)
            {
                s.AppendLine($"      SHA-256:    {f.Sha256}");
            }

            s.AppendLine($"      Rationale:  {f.ConfidenceRationale}");
            foreach (var e in f.Evidence)
            {
                s.AppendLine($"      Evidence:   [{e.Strength}] {e.Description}");
            }

            foreach (var source in f.RuleMatches.SelectMany(m => m.Sources).DistinctBy(x => x.Url))
            {
                s.AppendLine($"      Source:     {source.Title} — {source.Url} (retrieved {source.Retrieved})");
            }
        }

        s.AppendLine();
        s.AppendLine($"CLEANUP OPERATIONS ({r.Operations.Count})");
        foreach (var o in r.Operations)
        {
            s.AppendLine($"  {Time(o.TimestampUtc)}  {o.Type,-15} {(o.Succeeded ? "OK    " : "FAILED")} {o.Path} — {o.Message}");
        }

        if (r.Verification is { } v)
        {
            s.AppendLine();
            s.AppendLine("POST-CLEANUP VERIFICATION");
            foreach (var outcome in Enum.GetValues<VerificationOutcome>())
            {
                s.AppendLine($"  {outcome,-18} {v.Count(outcome)}");
            }

            foreach (var item in v.Items)
            {
                s.AppendLine($"  - {item.Outcome}: {item.Path} — {item.Detail}");
            }

            foreach (var item in v.NewFindings)
            {
                s.AppendLine($"  - Related item to review: {item.Path}");
            }

            foreach (var note in v.Notes)
            {
                s.AppendLine($"  Note: {note}");
            }
        }

        s.AppendLine();
        s.AppendLine($"SKIPPED OR PARTIALLY INSPECTED ({r.SkippedTotal})");
        foreach (var k in r.Skipped.Take(500))
        {
            s.AppendLine($"  {k.Reason,-20} {k.Path}{(k.Detail is null ? string.Empty : " — " + k.Detail)}");
        }

        if (r.SkippedTotal > Math.Min(500, r.Skipped.Count))
        {
            s.AppendLine($"  … {r.SkippedTotal - Math.Min(500, r.Skipped.Count)} more not listed.");
        }

        s.AppendLine();
        s.AppendLine("NOTES");
        foreach (var note in r.Notes)
        {
            s.AppendLine($"  - {note}");
        }

        s.AppendLine();
        s.AppendLine("LIMITATIONS");
        foreach (var limitation in r.Limitations)
        {
            s.AppendLine($"  - {limitation}");
        }

        return s.ToString();
    }

    private static string RenderHtml(ReportDocument r)
    {
        static string E(string? value) => WebUtility.HtmlEncode(value ?? string.Empty);
        var s = new StringBuilder();
        s.Append("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">");
        s.Append("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">");
        s.Append($"<title>{E(r.Title)}</title><style>");
        s.Append("body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1b1b1b;background:#fff;line-height:1.45}h1{font-size:1.6em}h2{margin-top:1.6em;border-bottom:1px solid #ccc}");
        s.Append("table{border-collapse:collapse;width:100%;margin:8px 0}th,td{border:1px solid #ccc;padding:6px;text-align:left;vertical-align:top;font-size:.92em}th{background:#f0f0f0}");
        s.Append(".k{font-weight:600}.c0{color:#a4262c}.c1{color:#8a4b00}.c2{color:#005a9e}.mono{font-family:Consolas,monospace;word-break:break-all}.small{font-size:.85em;color:#444}");
        s.Append("@media (prefers-color-scheme:dark){body{background:#1e1e1e;color:#eee}th{background:#333}th,td{border-color:#555}.small{color:#bbb}.c0{color:#ff8a8a}.c1{color:#ffc56b}.c2{color:#7cc4ff}}");
        s.Append("</style></head><body>");
        s.Append($"<h1>{E(r.Title)}</h1>");
        s.Append("<table>");
        void Row(string key, string? value) => s.Append($"<tr><th scope=\"row\">{E(key)}</th><td>{E(value)}</td></tr>");
        Row("Generated", Time(r.GeneratedAtUtc));
        Row("Application version", r.AppVersion);
        Row("Rule database", r.RulesVersion);
        Row("Scan", $"{r.SessionId} — {r.Mode}, {r.State}");
        Row("Started / finished", $"{Time(r.StartedAtUtc)} / {Time(r.CompletedAtUtc)}");
        if (r.UserName is not null || r.ComputerName is not null)
        {
            Row("User / computer", $"{r.UserName ?? "—"} / {r.ComputerName ?? "—"}");
        }

        Row("Path redaction", r.Redaction.ToString());
        s.Append("</table>");

        s.Append("<h2>Scope</h2><ul>");
        foreach (var root in r.Scope)
        {
            s.Append($"<li><span class=\"mono\">{E(root.Path)}</span>{(root.Recursive ? string.Empty : " (not recursive)")} — {E(root.Reason)}</li>");
        }

        s.Append("</ul>");
        var st = r.Statistics;
        s.Append("<h2>Statistics</h2><table>");
        Row("Files discovered (inspectable types)", st.FilesDiscovered.ToString(CultureInfo.InvariantCulture));
        Row("Files inspected", $"{st.FilesInspected} ({st.CacheHits} unchanged since a previous scan)");
        Row("Files skipped", st.FilesSkipped.ToString(CultureInfo.InvariantCulture));
        Row("Other files seen (not inspected)", st.FilesNotApplicable.ToString(CultureInfo.InvariantCulture));
        Row("Archives inspected", st.ArchivesInspected.ToString(CultureInfo.InvariantCulture));
        Row("Unique items flagged", st.UniqueFilesFlagged.ToString(CultureInfo.InvariantCulture));
        Row("Detection events (rule matches)", st.DetectionEvents.ToString(CultureInfo.InvariantCulture));
        s.Append("</table><h2>Classification breakdown</h2><table>");
        foreach (var (name, count) in r.ClassificationBreakdown)
        {
            Row(name, count.ToString(CultureInfo.InvariantCulture));
        }

        s.Append("</table>");
        s.Append($"<h2>Findings ({r.Findings.Count} unique items)</h2>");
        if (r.Findings.Count == 0)
        {
            s.Append("<p>No findings. This means no rule matched; it does not prove the scanned files are safe.</p>");
        }

        foreach (var f in r.Findings)
        {
            var css = f.Classification switch { Classification.KnownMatch => "c0", Classification.HighConfidenceSuspicion => "c1", _ => "c2" };
            s.Append($"<h3 class=\"{css}\">{E(ClassificationOrder.ToDisplay(f.Classification))}: <span class=\"mono\">{E(f.Path)}</span></h3><table>");
            Row("Rules", string.Join(", ", f.RuleMatches.Select(m => $"{m.RuleId} v{m.RuleVersion} ({m.Family}, {m.Category})")));
            Row("Confidence / severity / reputation", $"{f.Confidence} / {f.Severity} / {f.Reputation}");
            Row("Recommended action", ClassificationOrder.ToDisplay(f.RecommendedAction));
            Row("Cleanup status", ClassificationOrder.ToDisplay(f.CleanupStatus) + (f.CleanupMessage is null ? string.Empty : " — " + f.CleanupMessage));
            if (f.Sha256 is not null)
            {
                Row("SHA-256", f.Sha256);
            }

            Row("Rationale", f.ConfidenceRationale);
            s.Append("<tr><th scope=\"row\">Evidence</th><td><ul>");
            foreach (var e in f.Evidence)
            {
                s.Append($"<li><span class=\"k\">[{E(e.Strength.ToString())}]</span> {E(e.Description)}</li>");
            }

            s.Append("</ul></td></tr><tr><th scope=\"row\">Sources</th><td><ul>");
            foreach (var source in f.RuleMatches.SelectMany(m => m.Sources).DistinctBy(x => x.Url))
            {
                s.Append($"<li>{E(source.Title)} — <span class=\"mono\">{E(source.Url)}</span> (retrieved {E(source.Retrieved)})</li>");
            }

            s.Append("</ul></td></tr>");
            if (f.Limitations.Count > 0)
            {
                Row("Limitations", string.Join(" ", f.Limitations));
            }

            s.Append("</table>");
        }

        s.Append($"<h2>Cleanup operations ({r.Operations.Count})</h2><table><tr><th>Time</th><th>Operation</th><th>Result</th><th>Item</th><th>Details</th></tr>");
        foreach (var o in r.Operations)
        {
            s.Append($"<tr><td>{E(Time(o.TimestampUtc))}</td><td>{E(o.Type.ToString())}</td><td>{(o.Succeeded ? "Succeeded" : "Failed")}</td><td class=\"mono\">{E(o.Path)}</td><td>{E(o.Message)}</td></tr>");
        }

        s.Append("</table>");
        if (r.Verification is { } v)
        {
            s.Append("<h2>Post-cleanup verification</h2><table>");
            foreach (var outcome in Enum.GetValues<VerificationOutcome>())
            {
                Row(outcome.ToString(), v.Count(outcome).ToString(CultureInfo.InvariantCulture));
            }

            s.Append("</table><table><tr><th>Outcome</th><th>Item</th><th>Details</th></tr>");
            foreach (var item in v.Items.Concat(v.NewFindings))
            {
                s.Append($"<tr><td>{E(item.Outcome.ToString())}</td><td class=\"mono\">{E(item.Path)}</td><td>{E(item.Detail)}</td></tr>");
            }

            s.Append("</table>");
            foreach (var note in v.Notes)
            {
                s.Append($"<p class=\"small\">{E(note)}</p>");
            }
        }

        s.Append($"<h2>Skipped or partially inspected ({r.SkippedTotal})</h2><table><tr><th>Reason</th><th>Item</th><th>Details</th></tr>");
        foreach (var k in r.Skipped.Take(500))
        {
            s.Append($"<tr><td>{E(k.Reason.ToString())}</td><td class=\"mono\">{E(k.Path)}</td><td>{E(k.Detail)}</td></tr>");
        }

        s.Append("</table><h2>Notes</h2><ul>");
        foreach (var note in r.Notes)
        {
            s.Append($"<li>{E(note)}</li>");
        }

        s.Append("</ul><h2>Limitations</h2><ul>");
        foreach (var limitation in r.Limitations)
        {
            s.Append($"<li>{E(limitation)}</li>");
        }

        s.Append("</ul></body></html>");
        return s.ToString();
    }
}
