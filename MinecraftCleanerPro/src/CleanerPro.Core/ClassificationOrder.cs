using CleanerPro.Core.Models;

namespace CleanerPro.Core;

/// <summary>Ordering helpers used when several rules produce different classifications for one item.</summary>
public static class ClassificationOrder
{
    /// <summary>Lower rank wins. Legitimacy evidence ranks above "needs review" only for heuristic matches (see the classifier).</summary>
    public static int Rank(Classification classification) => classification switch
    {
        Classification.KnownMatch => 0,
        Classification.HighConfidenceSuspicion => 1,
        Classification.NeedsReview => 2,
        Classification.Unverified => 3,
        Classification.LikelyLegitimate => 4,
        _ => 5,
    };

    public static string ToDisplay(Classification classification) => classification switch
    {
        Classification.KnownMatch => "Known match",
        Classification.HighConfidenceSuspicion => "High-confidence suspicion",
        Classification.NeedsReview => "Needs review",
        Classification.LikelyLegitimate => "Likely legitimate",
        Classification.Unverified => "Unverified",
        _ => classification.ToString(),
    };

    public static string ToDisplay(RecommendedAction action) => action switch
    {
        RecommendedAction.NoAction => "No action needed",
        RecommendedAction.ManualReview => "Review manually before acting",
        RecommendedAction.Quarantine => "Quarantine (reversible)",
        RecommendedAction.QuarantineAndCheckSystem => "Quarantine, then check the whole system with a full antivirus scan",
        _ => action.ToString(),
    };

    public static string ToDisplay(CleanupStatus status) => status switch
    {
        CleanupStatus.NotActioned => "Not actioned",
        CleanupStatus.Quarantined => "Quarantined",
        CleanupStatus.QuarantineFailed => "Quarantine failed",
        CleanupStatus.Restored => "Restored",
        CleanupStatus.PermanentlyDeleted => "Permanently deleted",
        CleanupStatus.Blocked => "Blocked by safety policy",
        CleanupStatus.Skipped => "Skipped",
        _ => status.ToString(),
    };
}
