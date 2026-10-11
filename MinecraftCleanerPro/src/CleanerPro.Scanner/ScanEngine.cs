using System.Collections.Concurrent;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using CleanerPro.Configuration;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Detection.Bytecode;
using CleanerPro.Detection.Matching;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Scanner.Enumeration;
using CleanerPro.Scanner.Inspection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace CleanerPro.Scanner;

/// <summary>
/// The scan pipeline: enumerate approved locations → type/size checks → metadata → hashing → archive
/// inspection → rule matching → classification. Work is spread over a bounded queue and a configurable
/// number of low-priority worker threads, and can be paused, resumed and cancelled at any time.
/// Files are only ever read; nothing is executed or modified.
/// </summary>
public sealed class ScanEngine
{
    private const int MaxRecordedSkips = 5000;

    private readonly Func<AppConfiguration> _config;
    private readonly Func<CompiledRuleDatabase> _rules;
    private readonly ScanResultCache _cache;
    private readonly ILogger _logger;
    private readonly TimeProvider _time;
    private readonly LocationTemplateResolver _resolver;
    private readonly Func<(IReadOnlyList<StartupEntry> Entries, string? Error)> _startupReader;

    public ScanEngine(Func<AppConfiguration> config, Func<CompiledRuleDatabase> rules, ScanResultCache cache, ILogger<ScanEngine>? logger = null,
        TimeProvider? time = null, LocationTemplateResolver? resolver = null, Func<(IReadOnlyList<StartupEntry>, string?)>? startupReader = null)
    {
        _config = config;
        _rules = rules;
        _cache = cache;
        _logger = logger ?? NullLogger<ScanEngine>.Instance;
        _time = time ?? TimeProvider.System;
        _resolver = resolver ?? new LocationTemplateResolver();
        _startupReader = startupReader ?? (() =>
        {
            var entries = StartupInspector.ReadCurrentUserRunKey(out var error);
            return (entries, error);
        });
    }

    public Task<ScanSession> RunAsync(ScanScope scope, IProgress<ScanProgress>? progress, PauseController? pause, CancellationToken cancellationToken,
        string? parentSessionId = null)
    {
        // The pipeline uses dedicated threads; the returned task completes when they finish.
        return Task.Factory.StartNew(() => Run(scope, progress, pause, cancellationToken, parentSessionId),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
    }

    private ScanSession Run(ScanScope scope, IProgress<ScanProgress>? progress, PauseController? pause, CancellationToken cancellationToken, string? parentSessionId)
    {
        var config = _config();
        var database = _rules();
        var session = new ScanSession
        {
            Id = $"{_time.GetUtcNow():yyyyMMdd-HHmmss}-{Guid.NewGuid().ToString("N")[..6]}",
            Mode = scope.Mode,
            StartedAtUtc = _time.GetUtcNow(),
            AppVersion = AppInfo.Version,
            RulesVersion = database.DisplayVersion,
            RulesDatabaseVersion = database.DatabaseVersion,
            ParentSessionId = parentSessionId,
            Scope = scope,
            State = ScanState.Running,
        };

        var context = new RunContext(config, database, scope, pause, cancellationToken, _resolver);
        _logger.LogInformation("Scan {Id} started ({Mode}, {Roots} locations)", session.Id, scope.Mode, scope.Roots.Count);
        _cache.Load();

        using var reporterStop = new CancellationTokenSource();
        var reporter = Task.Run(async () =>
        {
            while (!reporterStop.IsCancellationRequested)
            {
                progress?.Report(context.Snapshot(pause?.IsPaused == true ? ScanState.Paused : ScanState.Running));
                try
                {
                    await Task.Delay(250, reporterStop.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
            }
        }, CancellationToken.None);

        try
        {
            RunPipeline(context);
            if (scope.IncludeStartupInspection)
            {
                context.Stage = ScanStage.CheckingSystemArtifacts;
                InspectStartupEntries(context);
            }

            cancellationToken.ThrowIfCancellationRequested();
            if (scope.IncludeProcessInspection)
            {
                InspectRunningProcesses(context, session);
            }

            session.State = ScanState.Completed;
        }
        catch (OperationCanceledException)
        {
            session.State = ScanState.Cancelled;
            session.Notes.Add("The scan was cancelled. Results are incomplete and only cover the files inspected before cancellation.");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Scan {Id} failed", session.Id);
            session.State = ScanState.Failed;
            session.FailureMessage = ex.Message;
        }
        finally
        {
            context.Stage = ScanStage.Finalizing;
            reporterStop.Cancel();
            try
            {
                reporter.Wait(TimeSpan.FromSeconds(2));
            }
            catch (AggregateException)
            {
            }

            _cache.Save();
        }

        Finalize(session, context);
        context.Stage = ScanStage.Completed;
        progress?.Report(context.Snapshot(session.State));
        _logger.LogInformation("Scan {Id} {State}: {Inspected} inspected, {Findings} findings", session.Id, session.State,
            session.Statistics.FilesInspected, session.Findings.Count);
        return session;
    }

    private sealed record WorkItem(EnumeratedItem Item, string PathKey);

    private void RunPipeline(RunContext context)
    {
        var config = context.Config;
        var lowResource = config.Performance.LowResourceMode;
        var workers = lowResource ? 1 : Math.Clamp(config.Performance.MaxParallelTasks, 1, 64);
        var capacity = lowResource ? 32 : Math.Clamp(config.Performance.MaxQueuedFiles, 16, 100_000);

        using var queue = new BlockingCollection<WorkItem>(new ConcurrentQueue<WorkItem>(), capacity);
        using var failure = CancellationTokenSource.CreateLinkedTokenSource(context.Cancellation);
        var token = failure.Token;

        var producer = Task.Factory.StartNew(() =>
        {
            try
            {
                Produce(context, queue, token);
            }
            finally
            {
                queue.CompleteAdding();
                context.EnumerationComplete = true;
            }
        }, token, TaskCreationOptions.LongRunning, TaskScheduler.Default);

        var consumers = Enumerable.Range(0, workers).Select(_ => Task.Factory.StartNew(() =>
        {
            using var priority = BackgroundPriority.Enter(config.Performance.ReducedPriority || lowResource);
            foreach (var work in queue.GetConsumingEnumerable(token))
            {
                context.Pause?.WaitWhilePaused(token);
                ProcessItem(context, work, token);
                if (lowResource)
                {
                    Thread.Sleep(1);
                }
            }
        }, token, TaskCreationOptions.LongRunning, TaskScheduler.Default)).ToArray();

        try
        {
            Task.WaitAll([producer, .. consumers]);
        }
        catch (AggregateException ex)
        {
            failure.Cancel();
            var inner = ex.Flatten().InnerExceptions;
            if (inner.All(e => e is OperationCanceledException))
            {
                throw new OperationCanceledException(context.Cancellation);
            }

            throw inner.First(e => e is not OperationCanceledException);
        }

        context.Cancellation.ThrowIfCancellationRequested();
    }

    private void Produce(RunContext context, BlockingCollection<WorkItem> queue, CancellationToken token)
    {
        context.Stage = ScanStage.EnumeratingFiles;
        var config = context.Config;
        var extensions = config.Scan.FileExtensions.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var settings = new EnumerationSettings
        {
            MaxDepth = config.Scan.MaxDirectoryDepth,
            ExcludedPaths = context.Scope.ExcludedPaths,
            ExcludedDirectoryNames = config.Scan.ExcludedDirectoryNames,
            FollowDirectoryLinks = config.Scan.FollowDirectoryLinks,
            LinkTargetRoots = context.Scope.Roots.Where(r => !r.IsFile).Select(r => r.Path).ToList(),
        };
        var enumerator = new SafeFileEnumerator(settings);
        var seen = new HashSet<string>(StringComparer.Ordinal);

        foreach (var root in context.Scope.Roots)
        {
            token.ThrowIfCancellationRequested();

            // A documented location that is itself a directory (for example a malware folder) is reported as an item too.
            if (!root.IsFile && context.KnownLocations.HitsByPathKey.TryGetValue(PathKey.ToKey(root.Path), out var rootHit) && rootHit.IsDirectory &&
                seen.Add(PathKey.ToKey(root.Path)))
            {
                queue.Add(new WorkItem(new EnumeratedItem(rootHit.Path, true, 0, DateTimeOffset.MinValue, root), PathKey.ToKey(root.Path)), token);
            }

            foreach (var item in enumerator.Enumerate(root, context.RecordSkip, () => Interlocked.Increment(ref context.DirectoriesVisited), token))
            {
                context.Pause?.WaitWhilePaused(token);
                var key = PathKey.ToKey(item.Path);
                if (!seen.Add(key))
                {
                    continue; // Overlapping roots: each item is processed once.
                }

                if (item.IsDirectory)
                {
                    queue.Add(new WorkItem(item, key), token);
                    continue;
                }

                var isCandidate = root.Kind == ScanRootKind.SystemArtifactLocation ||
                                  extensions.Contains(Path.GetExtension(item.Path)) ||
                                  context.KnownLocations.HitsByPathKey.ContainsKey(key);
                if (!isCandidate)
                {
                    Interlocked.Increment(ref context.FilesNotApplicable);
                    continue;
                }

                Interlocked.Increment(ref context.FilesDiscovered);
                context.CurrentPath = item.Path;
                queue.Add(new WorkItem(item, key), token);
            }
        }

        context.Stage = ScanStage.InspectingFiles;
    }

    private void ProcessItem(RunContext context, WorkItem work, CancellationToken token)
    {
        var item = work.Item;
        try
        {
            if (item.IsDirectory)
            {
                Classify(context, CreateObservation(context, item, work.PathKey));
                return;
            }

            ProcessFile(context, item, work.PathKey, token);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Interlocked.Increment(ref context.Errors);
            Interlocked.Increment(ref context.FilesSkipped);
            context.RecordSkip(new SkippedItem
            {
                Path = item.Path,
                Reason = ex is UnauthorizedAccessException ? SkipReason.AccessDenied : SkipReason.Unreadable,
                Detail = ex.Message,
            });
        }
        catch (Exception ex)
        {
            // A single malformed file must never stop the scan.
            _logger.LogWarning(ex, "Unexpected error while inspecting {Path}", item.Path);
            Interlocked.Increment(ref context.Errors);
            Interlocked.Increment(ref context.FilesSkipped);
            context.RecordSkip(new SkippedItem { Path = item.Path, Reason = SkipReason.Unreadable, Detail = $"Unexpected error: {ex.Message}" });
        }
    }

    private void ProcessFile(RunContext context, EnumeratedItem item, string pathKey, CancellationToken token)
    {
        var config = context.Config;
        context.CurrentPath = item.Path;
        var info = new FileInfo(item.Path);
        info.Refresh();
        if (!info.Exists)
        {
            Interlocked.Increment(ref context.FilesSkipped);
            context.RecordSkip(new SkippedItem { Path = item.Path, Reason = SkipReason.NotFound, Detail = "Removed before it could be inspected." });
            return;
        }

        var size = info.Length;
        var lastWrite = new DateTimeOffset(info.LastWriteTimeUtc, TimeSpan.Zero);
        var observation = CreateObservation(context, item, pathKey);
        observation.Size = size;
        observation.LastWriteUtc = lastWrite;

        var maxBytes = config.Scan.MaxFileSizeMegabytes * 1024L * 1024;
        if (size > maxBytes)
        {
            Interlocked.Increment(ref context.FilesSkipped);
            context.RecordSkip(new SkippedItem { Path = item.Path, Reason = SkipReason.TooLarge, Detail = $"{size / (1024 * 1024)} MB exceeds the {config.Scan.MaxFileSizeMegabytes} MB limit. Only its name and location were checked." });
            observation.InspectionProblems.Add($"The file is larger than the {config.Scan.MaxFileSizeMegabytes} MB inspection limit; only its name and location were checked.");
            Classify(context, observation);
            return;
        }

        if (config.Detection.ReuseVerifiedResults && observation.KnownLocationHits.Count == 0 &&
            _cache.IsVerifiedClean(pathKey, size, lastWrite, context.CacheContext))
        {
            Interlocked.Increment(ref context.CacheHits);
            Interlocked.Increment(ref context.FilesInspected);
            return;
        }

        var bufferSize = (config.Performance.LowResourceMode ? 128 : config.Performance.HashBufferKilobytes) * 1024;
        var isArchive = config.Scan.InspectArchives && ArchiveInspector.IsArchiveExtension(observation.Extension);
        using (var stream = new FileStream(item.Path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 4096, FileOptions.SequentialScan))
        {
            if (config.Detection.HashVerification)
            {
                var hashes = FileHasher.Compute(stream, config.Detection.ComputeSha1, bufferSize, token);
                observation.Sha256 = hashes.Sha256;
                observation.Sha1 = hashes.Sha1;
                Interlocked.Increment(ref context.FilesHashed);
                Interlocked.Add(ref context.BytesHashed, hashes.Length);
            }

            if (isArchive)
            {
                stream.Seek(0, SeekOrigin.Begin);
                var archive = context.ArchiveInspector.Inspect(stream, observation.InspectionProblems, token);
                if (archive is null)
                {
                    context.RecordSkip(new SkippedItem
                    {
                        Path = item.Path,
                        Reason = SkipReason.CorruptArchive,
                        Detail = "Not a readable archive. Hash, name and location checks were still applied.",
                    });
                }
                else
                {
                    observation.Archive = archive;
                    Interlocked.Increment(ref context.ArchivesInspected);
                    Interlocked.Add(ref context.ClassFilesInspected, archive.ClassFilesInspected);
                    if (observation.InspectionProblems.Count > 0)
                    {
                        context.RecordSkip(new SkippedItem
                        {
                            Path = item.Path,
                            Reason = SkipReason.ArchiveLimitExceeded,
                            Detail = "Partially inspected: " + string.Join(" ", observation.InspectionProblems.Take(3)),
                        });
                    }
                }
            }
        }

        if (config.Detection.VerifyDigitalSignatures && observation.Extension is ".exe" or ".dll")
        {
            observation.Signature = AuthenticodeVerifier.Verify(item.Path);
        }

        // Make sure the file did not change while it was being read.
        info.Refresh();
        if (!info.Exists || info.Length != size || new DateTimeOffset(info.LastWriteTimeUtc, TimeSpan.Zero) != lastWrite)
        {
            Interlocked.Increment(ref context.FilesSkipped);
            _cache.Invalidate(pathKey);
            context.RecordSkip(new SkippedItem { Path = item.Path, Reason = SkipReason.ChangedDuringScan, Detail = "The file changed while it was being inspected. Scan again to check it." });
            return;
        }

        Interlocked.Increment(ref context.FilesInspected);
        var finding = Classify(context, observation);
        if (finding is null && !observation.InspectionIncomplete && observation.Sha256 is not null)
        {
            _cache.MarkClean(pathKey, size, lastWrite, observation.Sha256, context.CacheContext);
        }
        else
        {
            _cache.Invalidate(pathKey);
        }
    }

    private static ItemObservation CreateObservation(RunContext context, EnumeratedItem item, string pathKey)
    {
        var root = item.Root;
        string? relative = null;
        if (root.InstallationRoot is { } installationRoot && PathKey.IsSameOrWithin(item.Path, installationRoot) &&
            !string.Equals(PathKey.TrimTrailingSeparators(item.Path), PathKey.TrimTrailingSeparators(installationRoot), PathKey.Comparison))
        {
            relative = Path.GetRelativePath(installationRoot, item.Path).Replace('\\', '/');
        }

        var observation = new ItemObservation
        {
            Path = item.Path,
            Name = Path.GetFileName(item.Path),
            IsDirectory = item.IsDirectory,
            IsSystemArtifact = root.Kind == ScanRootKind.SystemArtifactLocation,
            InstallationId = root.InstallationId,
            InstallationName = root.InstallationName,
            InstallationRoot = root.InstallationRoot,
            RelativePath = relative,
            LastWriteUtc = item.IsDirectory && item.LastWriteUtc != DateTimeOffset.MinValue ? item.LastWriteUtc : null,
        };

        if (context.KnownLocations.HitsByPathKey.TryGetValue(pathKey, out var hit))
        {
            observation.KnownLocationHits.UnionWith(hit.IndicatorKeys);
        }

        return observation;
    }

    private static Finding? Classify(RunContext context, ItemObservation observation)
    {
        var evaluations = context.Matcher.Evaluate(observation, context.EnabledCategories);
        if (evaluations.Count == 0)
        {
            return null;
        }

        Interlocked.Add(ref context.DetectionEvents, evaluations.Count(e => e.Rule.Definition.Category != DetectionCategory.LegitimateSoftware));
        var outcome = context.Classifier.Classify(observation, evaluations, context.ClassifierOptions);
        if (outcome.SuppressedByTrustedExclusion)
        {
            context.RecordSkip(new SkippedItem { Path = observation.Path, Reason = SkipReason.TrustedExclusion, Detail = "Matched a rule but is in your trusted exclusions." });
        }

        if (outcome.Finding is { } finding)
        {
            context.Findings[PathKey.ToKey(observation.Path)] = finding;
        }

        return outcome.Finding;
    }

    private void InspectStartupEntries(RunContext context)
    {
        var (entries, error) = _startupReader();
        if (error is not null)
        {
            context.Notes.Add(error);
        }

        foreach (var entry in entries)
        {
            context.Cancellation.ThrowIfCancellationRequested();
            var observation = new ItemObservation
            {
                Path = $@"{entry.Source}\{entry.Name}",
                Name = entry.Name,
                IsSystemArtifact = true,
                StartupEntry = entry,
            };
            Classify(context, observation);
        }

        context.Notes.Add($"{entries.Count} per-user startup entr{(entries.Count == 1 ? "y was" : "ies were")} inspected (read-only).");
    }

    private void InspectRunningProcesses(RunContext context, ScanSession session)
    {
        if (context.Findings.IsEmpty)
        {
            context.Notes.Add("Running processes were not inspected because there were no findings to compare them with.");
            return;
        }

        var flagged = context.Findings.Values.Select(f => f.IsDirectory ? f.Path : Path.GetDirectoryName(f.Path)).Where(p => p is not null).Distinct(PathKey.Comparer).ToList();
        var count = 0;
        foreach (var process in Process.GetProcesses())
        {
            using (process)
            {
                string? path;
                try
                {
                    path = process.MainModule?.FileName;
                }
                catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or InvalidOperationException or NotSupportedException)
                {
                    continue; // Protected or exited processes cannot be inspected; that is expected.
                }

                if (path is null || !flagged.Any(f => PathKey.IsSameOrWithin(path, f!)))
                {
                    continue;
                }

                count++;
                var note = $"Process '{process.ProcessName}' (PID {process.Id}) is running from a location with findings: {path}. Close it before quarantining.";
                context.Notes.Add(note);
                foreach (var finding in context.Findings.Values.Where(f => PathKey.IsSameOrWithin(path, f.IsDirectory ? f.Path : Path.GetDirectoryName(f.Path)!)))
                {
                    finding.Limitations.Add(note);
                }
            }
        }

        context.Notes.Add($"Running processes were inspected (read-only); {count} ran from locations with findings.");
        _ = session;
    }

    private void Finalize(ScanSession session, RunContext context)
    {
        session.CompletedAtUtc = _time.GetUtcNow();
        session.Findings.AddRange(context.Findings.Values
            .OrderBy(f => ClassificationOrder.Rank(f.Classification))
            .ThenByDescending(f => f.Severity)
            .ThenBy(f => f.Path, StringComparer.OrdinalIgnoreCase));
        session.Skipped.AddRange(context.Skipped.Take(MaxRecordedSkips));
        session.SkippedTotal = context.SkippedTotal;
        session.Notes.AddRange(context.KnownLocations.Notes);
        session.Notes.AddRange(context.Notes);
        session.Statistics = context.Statistics(session.Findings);

        session.Limitations.Add("File inspection cannot prove that a player cheated: detected files may be unused or leftovers, and cheats that run only in memory, are injected at runtime, or were deleted before the scan leave nothing to detect.");
        session.Limitations.Add($"Detection is limited to the families and indicators in rule database {context.Database.DisplayVersion}. Unknown or obfuscated cheats may not be found; files without matches are not declared safe.");
        if (!context.Config.Scan.InspectArchives)
        {
            session.Limitations.Add("Archive inspection was disabled, so mod contents were not examined.");
        }

        if (!context.Config.Scan.InspectBytecode)
        {
            session.Limitations.Add("Bytecode inspection was disabled, so infected mods (for example fractureiser stage 0) cannot be recognised.");
        }

        if (!context.Config.Detection.HashVerification)
        {
            session.Limitations.Add("Hash verification was disabled, so hash-based rules could not match.");
        }

        if (session.SkippedTotal > 0)
        {
            session.Limitations.Add($"{session.SkippedTotal} item(s) were skipped or only partially inspected; see the skipped list for reasons.");
        }

        if (context.Database.RulesExcludedByPlatform > 0)
        {
            session.Limitations.Add($"{context.Database.RulesExcludedByPlatform} rule(s) apply to other operating systems and were not used.");
        }
    }

    private sealed class RunContext
    {
        private readonly ConcurrentQueue<SkippedItem> _skipped = new();
        private long _skippedTotal;

        public RunContext(AppConfiguration config, CompiledRuleDatabase database, ScanScope scope, PauseController? pause, CancellationToken cancellation, LocationTemplateResolver resolver)
        {
            Config = config;
            Database = database;
            Scope = scope;
            Pause = pause;
            Cancellation = cancellation;
            EnabledCategories = config.Detection.EnabledCategories.ToHashSet();
            Matcher = new RuleMatcher(database, resolver);
            Classifier = new FindingClassifier();
            ClassifierOptions = new ClassifierOptions
            {
                ReportLikelyLegitimate = config.Detection.ReportLikelyLegitimate,
                TrustedExclusions = config.Detection.TrustedExclusions.Select(e => new TrustedExclusionEntry(e.Sha256, e.Path, e.Note)).ToList(),
            };
            var memory = Math.Clamp(config.Performance.MaxMemoryMegabytes, 64, 8192) * 1024L * 1024;
            ArchiveInspector = new ArchiveInspector(
                ArchiveInspectionOptions.FromConfiguration(config),
                new BytecodeSignatureMatcher(database.BytecodeSignatures.Where(s => EnabledCategories.Contains(RuleCategory(database, s.Key)))),
                new MemoryBudget(memory));
            KnownLocations = scope.IncludeSystemArtifactChecks
                ? SystemArtifactResolver.Resolve(database, resolver, EnabledCategories)
                : new SystemArtifactResolution(new Dictionary<string, KnownLocationHit>(), [], []);
            CacheContext = ComputeCacheContext(config, database);
        }

        public AppConfiguration Config { get; }

        public CompiledRuleDatabase Database { get; }

        public ScanScope Scope { get; }

        public PauseController? Pause { get; }

        public CancellationToken Cancellation { get; }

        public IReadOnlySet<DetectionCategory> EnabledCategories { get; }

        public RuleMatcher Matcher { get; }

        public FindingClassifier Classifier { get; }

        public ClassifierOptions ClassifierOptions { get; }

        public ArchiveInspector ArchiveInspector { get; }

        public SystemArtifactResolution KnownLocations { get; }

        public string CacheContext { get; }

        public ConcurrentDictionary<string, Finding> Findings { get; } = new(StringComparer.Ordinal);

        public ConcurrentBag<string> Notes { get; } = [];

        public IEnumerable<SkippedItem> Skipped => _skipped;

        public long SkippedTotal => Interlocked.Read(ref _skippedTotal);

        public volatile bool EnumerationComplete;

        public volatile string? CurrentPath;

        public ScanStage Stage { get; set; } = ScanStage.DiscoveringLocations;

        public long FilesDiscovered;
        public long FilesInspected;
        public long FilesSkipped;
        public long FilesNotApplicable;
        public long DirectoriesVisited;
        public long ArchivesInspected;
        public long ClassFilesInspected;
        public long FilesHashed;
        public long BytesHashed;
        public long CacheHits;
        public long Errors;
        public long DetectionEvents;

        public void RecordSkip(SkippedItem item)
        {
            Interlocked.Increment(ref _skippedTotal);
            if (_skipped.Count < MaxRecordedSkips)
            {
                _skipped.Enqueue(item);
            }
        }

        public ScanProgress Snapshot(ScanState state) => new()
        {
            Stage = Stage,
            State = state,
            FilesDiscovered = Interlocked.Read(ref FilesDiscovered),
            FilesInspected = Interlocked.Read(ref FilesInspected),
            FilesSkipped = Interlocked.Read(ref FilesSkipped),
            FindingsCount = Findings.Count,
            EnumerationComplete = EnumerationComplete,
            CurrentPath = CurrentPath,
        };

        public ScanStatistics Statistics(IReadOnlyList<Finding> findings) => new()
        {
            FilesDiscovered = Interlocked.Read(ref FilesDiscovered),
            FilesInspected = Interlocked.Read(ref FilesInspected),
            FilesSkipped = Interlocked.Read(ref FilesSkipped),
            FilesNotApplicable = Interlocked.Read(ref FilesNotApplicable),
            DirectoriesVisited = Interlocked.Read(ref DirectoriesVisited),
            ArchivesInspected = Interlocked.Read(ref ArchivesInspected),
            ClassFilesInspected = Interlocked.Read(ref ClassFilesInspected),
            FilesHashed = Interlocked.Read(ref FilesHashed),
            BytesHashed = Interlocked.Read(ref BytesHashed),
            CacheHits = Interlocked.Read(ref CacheHits),
            Errors = Interlocked.Read(ref Errors),
            UniqueFilesFlagged = findings.Count(f => f.Classification != Classification.LikelyLegitimate),
            DetectionEvents = Interlocked.Read(ref DetectionEvents),
        };

        private static DetectionCategory RuleCategory(CompiledRuleDatabase database, string key)
        {
            var ruleId = key[..key.IndexOf('/')];
            return database.Rules.First(r => r.Id == ruleId).Definition.Category;
        }

        private static string ComputeCacheContext(AppConfiguration config, CompiledRuleDatabase database)
        {
            var text = string.Join("|",
                database.Sha256,
                string.Join(",", config.Detection.EnabledCategories.Order()),
                config.Scan.InspectArchives, config.Scan.InspectBytecode, config.Scan.MaxClassFileKilobytes,
                config.Detection.HashVerification, config.Detection.ComputeSha1, config.Detection.ReportLikelyLegitimate,
                config.Scan.ArchiveLimits.MaxEntries, config.Scan.ArchiveLimits.MaxNestedArchiveDepth,
                string.Join(",", config.Detection.TrustedExclusions.Select(e => e.Sha256 + e.Path)));
            return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text)), 0, 16);
        }
    }
}
