using System.Text;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Infrastructure.Platform;

namespace CleanerPro.Detection.Matching;

public sealed record TrustedExclusionEntry(string? Sha256, string? Path, string? Note);

public sealed record ClassifierOptions
{
    public bool ReportLikelyLegitimate { get; init; }

    public IReadOnlyList<TrustedExclusionEntry> TrustedExclusions { get; init; } = [];
}

public sealed record ClassificationOutcome(Finding? Finding, bool SuppressedByTrustedExclusion, bool SuppressedAsLegitimate);

/// <summary>
/// Turns rule evaluations into a single finding per item. Classification, confidence, severity,
/// reputation and recommended action are derived separately and every decision is explained.
/// </summary>
public sealed class FindingClassifier
{
    private const string FileScannerLimitation =
        "A file scan cannot prove that a player used a cheat: files may be unused, renamed or leftovers, and some cheats leave no files at all.";

    public ClassificationOutcome Classify(ItemObservation observation, IReadOnlyList<RuleEvaluation> evaluations, ClassifierOptions options)
    {
        var detections = evaluations.Where(e => e.Rule.Definition.Category != DetectionCategory.LegitimateSoftware).ToList();
        var legitimacy = evaluations.Where(e => e.Rule.Definition.Category == DetectionCategory.LegitimateSoftware).ToList();
        var signedValid = observation.Signature?.Status == SignatureStatus.Valid;

        if (detections.Count == 0 && legitimacy.Count == 0)
        {
            return new ClassificationOutcome(null, false, false);
        }

        // Trusted exclusions apply to everything except documented malware, which is always reported.
        var excluded = IsTrusted(observation, options.TrustedExclusions);
        if (excluded)
        {
            detections = detections.Where(d => d.Rule.Definition.Category == DetectionCategory.Malware).ToList();
            if (detections.Count == 0)
            {
                return new ClassificationOutcome(null, true, false);
            }
        }

        var extraEvidence = new List<Evidence>();
        var limitations = new List<string>();
        if (signedValid)
        {
            extraEvidence.Add(new Evidence
            {
                Kind = IndicatorType.AuthenticodeSignature,
                Description = $"Valid Authenticode signature{(observation.Signature!.Subject is null ? string.Empty : $" from {observation.Signature.Subject}")} (revocation not checked).",
                MatchedValue = observation.Signature.Subject,
                Strength = EvidenceStrength.Moderate,
            });
        }

        var hasLegitimacyEvidence = legitimacy.Count > 0 || signedValid;
        var best = detections.OrderBy(d => ClassificationOrder.Rank(d.Level)).FirstOrDefault();

        Classification classification;
        List<RuleEvaluation> used;
        var suppressedAsLegitimate = false;

        if (best is null)
        {
            classification = Classification.LikelyLegitimate;
            used = legitimacy;
        }
        else if (hasLegitimacyEvidence && best.Level == Classification.NeedsReview &&
                 detections.Where(d => d.Level == Classification.NeedsReview).All(d => d.Rule.Definition.Heuristic))
        {
            // Strong identity evidence for a known legitimate mod outweighs generic naming heuristics.
            classification = Classification.LikelyLegitimate;
            used = legitimacy;
            suppressedAsLegitimate = true;
            limitations.Add("Generic heuristic matches were overridden by legitimacy evidence: " +
                            string.Join("; ", detections.Select(d => $"{d.Rule.Id} ({d.Rule.Definition.Family})")) + ".");
        }
        else
        {
            classification = best.Level;
            used = detections;
            if (hasLegitimacyEvidence)
            {
                foreach (var legit in legitimacy)
                {
                    extraEvidence.AddRange(legit.Evidence);
                }

                limitations.Add("This item also carries identity markers of legitimate software. That can mean a disguised file or a false positive; review the evidence before acting.");
            }

            if (observation.InspectionIncomplete && classification == Classification.NeedsReview)
            {
                classification = Classification.Unverified;
            }
        }

        if (classification == Classification.LikelyLegitimate && !options.ReportLikelyLegitimate)
        {
            return new ClassificationOutcome(null, false, suppressedAsLegitimate);
        }

        if (observation.InspectionIncomplete)
        {
            limitations.Add("The item could not be fully inspected: " + string.Join("; ", observation.InspectionProblems));
        }

        var primary = used.OrderBy(u => ClassificationOrder.Rank(u.Level)).FirstOrDefault();
        var ruleMatches = used.Select(ToRuleMatch).ToList();
        if (best is not null && used != detections)
        {
            // Keep the overridden heuristic matches visible for transparency.
            ruleMatches.AddRange(detections.Select(ToRuleMatch));
        }

        var evidence = used.SelectMany(u => u.Evidence).Concat(extraEvidence).ToList();
        foreach (var match in used)
        {
            if (!string.IsNullOrWhiteSpace(match.Rule.Definition.Limitations))
            {
                limitations.Add(match.Rule.Definition.Limitations!);
            }
        }

        if (used.Any(u => u.Rule.Definition.Category is not (DetectionCategory.Malware or DetectionCategory.LegitimateSoftware or DetectionCategory.TestSignature)))
        {
            limitations.Add(FileScannerLimitation);
        }

        var finding = new Finding
        {
            Id = Finding.CreateId(SafeKey(observation.Path), observation.Sha256),
            Path = observation.Path,
            IsDirectory = observation.IsDirectory,
            IsSystemArtifact = observation.IsSystemArtifact,
            SizeBytes = observation.Size,
            LastWriteUtc = observation.LastWriteUtc,
            Sha256 = observation.Sha256,
            Sha1 = observation.Sha1,
            InstallationId = observation.InstallationId,
            InstallationName = observation.InstallationName,
            Identity = observation.Archive?.Mods.FirstOrDefault(),
            Classification = classification,
            Confidence = DeriveConfidence(classification, evidence, signedValid),
            Severity = DeriveSeverity(classification, primary),
            Reputation = DeriveReputation(classification, primary, signedValid),
            RecommendedAction = DeriveAction(classification, primary, observation),
            ConfidenceRationale = BuildRationale(classification, primary, used, suppressedAsLegitimate),
            RuleMatches = ruleMatches,
            Evidence = evidence,
            Limitations = limitations.Distinct().ToList(),
        };

        return new ClassificationOutcome(finding, false, suppressedAsLegitimate);
    }

    private static bool IsTrusted(ItemObservation observation, IReadOnlyList<TrustedExclusionEntry> exclusions)
    {
        foreach (var exclusion in exclusions)
        {
            var hashOk = exclusion.Sha256 is null ||
                         (observation.Sha256 is not null && string.Equals(exclusion.Sha256, observation.Sha256, StringComparison.OrdinalIgnoreCase));
            var pathOk = exclusion.Path is null || string.Equals(SafeKey(exclusion.Path), SafeKey(observation.Path), StringComparison.Ordinal);
            if (hashOk && pathOk && (exclusion.Sha256 is not null || exclusion.Path is not null))
            {
                return true;
            }
        }

        return false;
    }

    private static string SafeKey(string path)
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

    private static RuleMatch ToRuleMatch(RuleEvaluation evaluation)
    {
        var definition = evaluation.Rule.Definition;
        return new RuleMatch
        {
            RuleId = definition.Id,
            RuleVersion = definition.Version,
            Family = definition.Family,
            Category = definition.Category,
            Classification = evaluation.Level,
            Severity = definition.Severity,
            RecommendedAction = definition.RecommendedAction,
            MatchedIndicatorIds = evaluation.MatchedIndicatorIds,
            Sources = definition.Sources,
            VerifiedOn = definition.VerifiedOn,
            ConfidenceRationale = definition.ConfidenceRationale,
            FalsePositiveNotes = definition.FalsePositiveNotes,
            Limitations = definition.Limitations,
        };
    }

    private static DetectionConfidence DeriveConfidence(Classification classification, IReadOnlyList<Evidence> evidence, bool signedValid) => classification switch
    {
        Classification.KnownMatch => evidence.Any(e => e.Strength == EvidenceStrength.Definitive) ? DetectionConfidence.Verified : DetectionConfidence.High,
        Classification.HighConfidenceSuspicion => evidence.Count(e => e.Strength >= EvidenceStrength.Strong) >= 2 ? DetectionConfidence.High : DetectionConfidence.Medium,
        Classification.NeedsReview => DetectionConfidence.Low,
        Classification.Unverified => DetectionConfidence.Low,
        Classification.LikelyLegitimate => signedValid || evidence.Count(e => e.Strength >= EvidenceStrength.Strong) >= 2 ? DetectionConfidence.High : DetectionConfidence.Medium,
        _ => DetectionConfidence.None,
    };

    /// <summary>
    /// Severity describes the matched family. For ambiguous classifications the potential severity is
    /// kept in the rule match, but the finding itself is capped so a weak indicator never looks alarming.
    /// </summary>
    private static ThreatSeverity DeriveSeverity(Classification classification, RuleEvaluation? primary)
    {
        if (primary is null || classification == Classification.LikelyLegitimate)
        {
            return ThreatSeverity.None;
        }

        var ruleSeverity = primary.Rule.Definition.Severity;
        return classification is Classification.KnownMatch or Classification.HighConfidenceSuspicion
            ? ruleSeverity
            : (ThreatSeverity)Math.Min((int)ruleSeverity, (int)ThreatSeverity.Low);
    }

    private static FileReputation DeriveReputation(Classification classification, RuleEvaluation? primary, bool signedValid) => classification switch
    {
        Classification.KnownMatch => primary?.Rule.Definition.ReputationOnMatch ?? FileReputation.Suspicious,
        Classification.HighConfidenceSuspicion => FileReputation.Suspicious,
        Classification.LikelyLegitimate => signedValid ? FileReputation.TrustedSignature : FileReputation.KnownLegitimate,
        _ => FileReputation.Unknown,
    };

    private static RecommendedAction DeriveAction(Classification classification, RuleEvaluation? primary, ItemObservation observation)
    {
        if (observation.StartupEntry is not null)
        {
            // Registry entries are reported only; the application never edits the registry.
            return RecommendedAction.ManualReview;
        }

        return classification switch
        {
            Classification.KnownMatch or Classification.HighConfidenceSuspicion => primary?.Rule.Definition.RecommendedAction ?? RecommendedAction.ManualReview,
            Classification.LikelyLegitimate => RecommendedAction.NoAction,
            _ => RecommendedAction.ManualReview,
        };
    }

    private static string BuildRationale(Classification classification, RuleEvaluation? primary, IReadOnlyList<RuleEvaluation> used, bool suppressed)
    {
        var builder = new StringBuilder();
        builder.Append(ClassificationOrder.ToDisplay(classification));
        if (primary is not null)
        {
            var definition = primary.Rule.Definition;
            builder.Append($" — rule {definition.Id} ({definition.Family}) matched {primary.MatchedIndicatorIds.Count} indicator(s): ");
            builder.Append(string.Join(", ", primary.Evidence.Select(e => e.IndicatorId)));
            builder.Append(". ");
            builder.Append(definition.ConfidenceRationale);
        }

        if (used.Count > 1)
        {
            builder.Append($" {used.Count - 1} additional rule(s) also matched; see the rule list.");
        }

        if (suppressed)
        {
            builder.Append(" Generic heuristic matches were outweighed by legitimacy evidence.");
        }

        if (classification == Classification.Unverified)
        {
            builder.Append(" The item could not be fully inspected, so the weak evidence could not be confirmed or ruled out.");
        }

        return builder.ToString().Trim();
    }
}
