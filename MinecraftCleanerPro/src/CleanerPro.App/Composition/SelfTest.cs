using System.IO.Compression;
using System.Text;
using System.Text.Json;
using CleanerPro.Configuration;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Core.Safety;
using CleanerPro.Detection.Rules;
using CleanerPro.Infrastructure;
using CleanerPro.Privacy;
using CleanerPro.Quarantine;
using CleanerPro.Reporting;
using CleanerPro.Scanner;
using Microsoft.Extensions.DependencyInjection;

namespace CleanerPro.App.Composition;

/// <summary>
/// Headless end-to-end check of the published executable, using only harmless fixtures in a temporary
/// folder: configuration, rules, scanning, quarantine, restore, reports, path protection and offline mode.
/// </summary>
public static class SelfTest
{
    public sealed record Step(string Name, bool Passed, string Detail);

    public static int Run(string outputPath, string? dataRoot)
    {
        var steps = new List<Step>();
        // Normalised, so a folder given as "C:/x" or with a trailing separator matches the paths the scanner reports.
        var root = PathKey.NormalizeFullPath(dataRoot ?? Path.Combine(Path.GetTempPath(), "MinecraftCleanerPro-SelfTest-" + Guid.NewGuid().ToString("N")[..8]));
        Directory.CreateDirectory(root);

        void Check(string name, Func<string> action)
        {
            try
            {
                steps.Add(new Step(name, true, action()));
            }
            catch (Exception ex)
            {
                steps.Add(new Step(name, false, ex.GetType().Name + ": " + ex.Message));
            }
        }

        static void Assert(bool condition, string message)
        {
            if (!condition)
            {
                throw new InvalidOperationException(message);
            }
        }

        using var services = AppServices.Build(Path.Combine(root, "data"));
        var configuration = services.GetRequiredService<ConfigurationService>();
        var rules = services.GetRequiredService<RuleRepository>();
        var engine = services.GetRequiredService<ScanEngine>();
        var scopes = services.GetRequiredService<ScanScopeBuilder>();
        var quarantine = services.GetRequiredService<QuarantineService>();
        var reports = services.GetRequiredService<ReportService>();
        var history = services.GetRequiredService<HistoryStore>();
        var networkLog = services.GetRequiredService<NetworkActivityLog>();

        Check("Configuration created and valid", () =>
        {
            Assert(File.Exists(configuration.FilePath), "config.json was not created");
            var validation = configuration.ValidateFile();
            Assert(validation.IsValid, string.Join("; ", validation.Errors.Select(e => e.Message)));
            return configuration.FilePath;
        });

        Check("Bundled rules loaded", () =>
        {
            var database = rules.Active.Database;
            Assert(database.Rules.Count > 0, "no rules");
            return $"{database.DisplayVersion}, {database.Rules.Count} rules, SHA-256 {database.Sha256}";
        });

        var game = Path.Combine(root, "game");
        var testFile = Path.Combine(game, "cleanerpro-harmless-test.txt");
        var jar = Path.Combine(game, "mods", "wurst-fixture.jar");
        Check("Harmless fixtures created", () =>
        {
            Directory.CreateDirectory(Path.Combine(game, "mods"));
            File.WriteAllText(testFile, ViewModels.ScannerViewModel.SelfTestContent);
            using (var zip = ZipFile.Open(jar, ZipArchiveMode.Create))
            {
                using (var writer = new StreamWriter(zip.CreateEntry("fabric.mod.json").Open()))
                {
                    writer.Write("""{ "schemaVersion": 1, "id": "wurst", "version": "0" }""");
                }

                zip.CreateEntry("net/wurstclient/WurstInitializer.class"); // empty placeholder entry, not runnable
            }

            return game;
        });

        ScanSession? session = null;
        Check("Scan detects the fixtures with evidence", () =>
        {
            var scope = scopes.Build(ScanMode.Custom, new DiscoveryResult(), [game]);
            session = engine.RunAsync(scope, null, null, CancellationToken.None).GetAwaiter().GetResult();
            history.Save(session);
            Assert(session.State == ScanState.Completed, $"state {session.State}");
            var test = session.Findings.SingleOrDefault(f => f.Path == testFile);
            var cheat = session.Findings.SingleOrDefault(f => f.Path == jar);
            Assert(test?.Classification == Classification.KnownMatch, "test file not detected as known match");
            Assert(cheat?.Classification == Classification.KnownMatch, "fixture jar not detected as known match");
            Assert(cheat!.Evidence.Count >= 2, "missing evidence");
            return $"{session.Statistics.FilesInspected} files inspected, {session.Findings.Count} findings";
        });

        QuarantineEntry? entry = null;
        Check("Quarantine with integrity verification", () =>
        {
            var finding = session!.Findings.Single(f => f.Path == testFile);
            var result = quarantine.Quarantine(new QuarantineRequest { Path = testFile, ApprovedRoots = [game], ExpectedSha256 = finding.Sha256, SessionId = session.Id, FindingId = finding.Id });
            Assert(result.Succeeded, result.Message);
            Assert(!File.Exists(testFile), "original still present");
            entry = result.Entry;
            Assert(quarantine.VerifyIntegrity(entry!.Id) == IntegrityStatus.Verified, "integrity check failed");
            return entry.Id;
        });

        Check("Restore returns identical content", () =>
        {
            var result = quarantine.Restore(new RestoreRequest(entry!.Id, RestoreMode.OriginalLocation));
            Assert(result.Succeeded, result.Message);
            Assert(FileHasher.Compute(testFile, false).Sha256 == entry.Sha256, "hash mismatch after restore");
            return result.Message;
        });

        Check("Protected system paths cannot be targeted", () =>
        {
            var policy = services.GetRequiredService<PathSafetyPolicy>();
            var system = Environment.GetFolderPath(Environment.SpecialFolder.System);
            if (string.IsNullOrEmpty(system))
            {
                return "Not applicable on this platform.";
            }

            var target = Path.Combine(system, "drivers", "etc", "hosts");
            var check = policy.ValidateCleanupTarget(target, [Path.GetPathRoot(system)!], PathTargetKind.File);
            Assert(!check.IsAllowed && check.Code == PathBlockCode.ProtectedLocation, $"expected ProtectedLocation, got {check.Code}");
            return check.Reason ?? "blocked";
        });

        Check("Reports in HTML, TXT and JSON", () =>
        {
            var paths = new[] { ReportFormat.Html, ReportFormat.Txt, ReportFormat.Json }
                .Select(f => reports.Export(session!, f, RedactionLevel.PersonalPaths, Path.Combine(root, "report" + ReportExporter.Extension(f))))
                .ToList();
            Assert(paths.All(File.Exists), "a report is missing");
            using var json = JsonDocument.Parse(File.ReadAllText(paths[2]));
            Assert(json.RootElement.GetProperty("findings").GetArrayLength() == session!.Findings.Count, "report findings mismatch");
            return string.Join(", ", paths.Select(Path.GetFileName));
        });

        Check("Offline by default, no network activity", () =>
        {
            Assert(configuration.Current.Privacy.OfflineMode, "offline mode is off");
            Assert(networkLog.ReadAll().All(r => !r.Allowed), "a network request was made");
            return "No network requests were made.";
        });

        var passed = steps.All(s => s.Passed);
        var output = new
        {
            product = AppInfo.ProductName,
            version = AppInfo.Version,
            rules = rules.Active.Database.DisplayVersion,
            os = Environment.OSVersion.VersionString,
            framework = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
            processPath = Environment.ProcessPath,
            completedAtUtc = DateTimeOffset.UtcNow,
            passed,
            steps,
        };
        File.WriteAllText(outputPath, JsonSerializer.Serialize(output, CleanerJson.Default), Encoding.UTF8);
        return passed ? 0 : 1;
    }
}
