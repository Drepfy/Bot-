using CleanerPro.Core;
using CleanerPro.Core.Models;

namespace CleanerPro.Reporting;

public enum VerificationOutcome
{
    /// <summary>The item is no longer at the scanned location (no cleanup was recorded for it).</summary>
    NoLongerPresent,

    /// <summary>The item was quarantined and is not present at its original location.</summary>
    Quarantined,

    /// <summary>The item was quarantined and the quarantined copy was later permanently deleted.</summary>
    Deleted,

    /// <summary>The item is still present and still detected.</summary>
    StillPresent,

    /// <summary>The same content (identical SHA-256) is still present at another path.</summary>
    PresentElsewhere,

    /// <summary>The location could not be read during verification.</summary>
    NotAccessible,

    /// <summary>A cleanup operation was attempted and failed.</summary>
    OperationFailed,

    /// <summary>The verification scan did not cover the item, so nothing can be concluded.</summary>
    Inconclusive,
}

public sealed record VerificationItem(string FindingId, string Path, string Family, Classification OriginalClassification, VerificationOutcome Outcome, string Detail);

public sealed record VerificationReport
{
    public required string InitialSessionId { get; init; }

    public required string VerificationSessionId { get; init; }

    public required DateTimeOffset CompletedAtUtc { get; init; }

    public required IReadOnlyList<VerificationItem> Items { get; init; }

    /// <summary>Detections in the verification scan that were not part of the original scan (related files to review).</summary>
    public IReadOnlyList<VerificationItem> NewFindings { get; init; } = [];

    public IReadOnlyList<string> InaccessiblePaths { get; init; } = [];

    public IReadOnlyList<string> Notes { get; init; } = [];

    public int Count(VerificationOutcome outcome) => Items.Count(i => i.Outcome == outcome);
}

/// <summary>Compares an original scan with a post-cleanup verification scan using paths and hashes.</summary>
public static class VerificationService
{
    public static VerificationReport Compare(ScanSession initial, ScanSession verification, IReadOnlyList<OperationRecord> operations)
    {
        var finalByPath = verification.Findings.ToDictionary(f => Key(f.Path), StringComparer.Ordinal);
        var finalByHash = verification.Findings.Where(f => f.Sha256 is not null).GroupBy(f => f.Sha256!).ToDictionary(g => g.Key, g => g.ToList(), StringComparer.Ordinal);
        var skippedPaths = verification.Skipped.Select(s => Key(s.Path)).ToHashSet(StringComparer.Ordinal);
        var coveredRoots = verification.Scope.Roots.Select(r => r.Path).ToList();
        var items = new List<VerificationItem>();

        foreach (var finding in initial.Findings.Where(f => f.Classification != Classification.LikelyLegitimate))
        {
            var family = finding.RuleMatches.FirstOrDefault()?.Family ?? "Unknown";
            var related = operations
                .Where(o => o.FindingId == finding.Id || (o.Path is not null && Key(o.Path) == Key(finding.Path)) ||
                            (finding.IsDirectory && o.Path is not null && PathKey.IsSameOrWithin(o.Path, finding.Path)))
                .OrderBy(o => o.TimestampUtc)
                .ToList();
            var quarantineOps = related.Where(o => o.Type == OperationType.Quarantine).ToList();
            var quarantined = quarantineOps.Any(o => o.Succeeded);
            var failed = quarantineOps.Count > 0 && !quarantined;
            var restored = related.Any(o => o.Type == OperationType.Restore && o.Succeeded);
            var deleted = related.Any(o => o.Type == OperationType.PermanentDelete && o.Succeeded);
            var stillPresent = finalByPath.TryGetValue(Key(finding.Path), out var current);
            var exists = Exists(finding);

            VerificationOutcome outcome;
            string detail;
            if (stillPresent)
            {
                outcome = failed ? VerificationOutcome.OperationFailed : VerificationOutcome.StillPresent;
                detail = failed
                    ? "Quarantine failed and the item is still detected: " + quarantineOps[^1].Message
                    : restored ? "The item was restored from quarantine and is still detected." : $"Still detected as {ClassificationOrder.ToDisplay(current!.Classification)}.";
            }
            else if (skippedPaths.Contains(Key(finding.Path)))
            {
                outcome = VerificationOutcome.NotAccessible;
                detail = "The location could not be read during verification.";
            }
            else if (finding.Sha256 is not null && finalByHash.TryGetValue(finding.Sha256, out var copies))
            {
                outcome = VerificationOutcome.PresentElsewhere;
                detail = "Identical content is still present at: " + string.Join(", ", copies.Select(c => c.Path));
            }
            else if (quarantined && !exists)
            {
                outcome = deleted ? VerificationOutcome.Deleted : VerificationOutcome.Quarantined;
                detail = deleted
                    ? "Quarantined, not found at its original location, and the quarantined copy was permanently deleted."
                    : "Quarantined and no longer found at its original location.";
            }
            else if (failed)
            {
                outcome = VerificationOutcome.OperationFailed;
                detail = quarantineOps[^1].Message;
            }
            else if (!exists)
            {
                outcome = VerificationOutcome.NoLongerPresent;
                detail = "No longer present in the scanned location. No cleanup was recorded by this application for it.";
            }
            else if (!coveredRoots.Any(r => PathKey.IsSameOrWithin(finding.Path, r)) && !finding.IsSystemArtifact)
            {
                outcome = VerificationOutcome.Inconclusive;
                detail = "The verification scan did not cover this location.";
            }
            else
            {
                outcome = VerificationOutcome.Inconclusive;
                detail = "The item still exists but was not detected again (for example because rules or settings changed). Review it manually.";
            }

            items.Add(new VerificationItem(finding.Id, finding.Path, family, finding.Classification, outcome, detail));
        }

        var initialPaths = initial.Findings.Select(f => Key(f.Path)).ToHashSet(StringComparer.Ordinal);
        var newFindings = verification.Findings
            .Where(f => !initialPaths.Contains(Key(f.Path)) && f.Classification != Classification.LikelyLegitimate)
            .Select(f => new VerificationItem(f.Id, f.Path, f.RuleMatches.FirstOrDefault()?.Family ?? "Unknown", f.Classification, VerificationOutcome.StillPresent,
                "Detected during verification but not part of the original findings; review it."))
            .ToList();

        var notes = new List<string>
        {
            "A file that is no longer present is not proof that every component of a cheat or malware infection was removed. Cheats that run in memory, files outside the scanned locations, and changes to other programs are not covered.",
        };
        if (verification.State != ScanState.Completed)
        {
            notes.Add($"The verification scan ended as {verification.State}; results may be incomplete.");
        }

        return new VerificationReport
        {
            InitialSessionId = initial.Id,
            VerificationSessionId = verification.Id,
            CompletedAtUtc = verification.CompletedAtUtc ?? DateTimeOffset.UtcNow,
            Items = items,
            NewFindings = newFindings,
            InaccessiblePaths = verification.Skipped.Where(s => s.Reason is SkipReason.AccessDenied or SkipReason.Unreadable).Select(s => s.Path).ToList(),
            Notes = notes,
        };
    }

    private static bool Exists(Finding finding)
    {
        if (!Path.IsPathFullyQualified(finding.Path))
        {
            return false;
        }

        try
        {
            return finding.IsDirectory ? Directory.Exists(finding.Path) : File.Exists(finding.Path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return true; // Unknown is treated as still present.
        }
    }

    private static string Key(string path)
    {
        try
        {
            return Path.IsPathFullyQualified(path) ? PathKey.ToKey(path) : path;
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return path;
        }
    }
}
