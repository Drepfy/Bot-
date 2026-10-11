using System.Text.Json.Nodes;
using CleanerPro.Configuration;
using CleanerPro.Infrastructure;
using CleanerPro.TestSupport;

namespace CleanerPro.Core.Tests;

public sealed class ConfigurationTests : IDisposable
{
    private readonly TempDirectory _temp = new();
    private readonly AppPaths _paths;

    public ConfigurationTests()
    {
        _paths = new AppPaths(_temp.Combine("data"));
        _paths.EnsureCreated();
    }

    public void Dispose() => _temp.Dispose();

    private ConfigurationService CreateService(ConfigMigrator? migrator = null) =>
        new(_paths, TestPolicies.Create(), migrator: migrator);

    [Fact]
    public void FirstLaunchCreatesAValidDefaultFile()
    {
        var service = CreateService();
        var result = service.Load();

        Assert.True(result.CreatedDefaultFile);
        Assert.False(result.UsingSafeDefaults);
        Assert.True(File.Exists(_paths.ConfigFile));
        Assert.True(service.ValidateFile().IsValid);
        Assert.True(result.Validation.IsValid);
        Assert.Contains("\"schemaVersion\": 1", File.ReadAllText(_paths.ConfigFile));
    }

    [Fact]
    public void DefaultsAreConservative()
    {
        var config = ConfigurationService.CreateDefault();
        Assert.True(config.Privacy.OfflineMode);
        Assert.False(config.RuleUpdates.Enabled);
        Assert.Null(config.RuleUpdates.Endpoint);
        Assert.False(config.Startup.ScanOnLaunch);
        Assert.False(config.Scan.FollowDirectoryLinks);
        Assert.True(config.Safety.ConfirmPermanentDeletion);
        Assert.True(config.Quarantine.VerifyIntegrity);
        Assert.True(config.Performance.ReducedPriority);
    }

    [Fact]
    public void InvalidJsonFallsBackToSafeDefaultsWithoutOverwritingTheFile()
    {
        File.WriteAllText(_paths.ConfigFile, "{ \"schemaVersion\": 1, \"scan\": { ");
        var service = CreateService();
        var result = service.Load();

        Assert.True(result.UsingSafeDefaults);
        Assert.Contains("not valid JSON", result.FailureMessage);
        Assert.Equal("{ \"schemaVersion\": 1, \"scan\": { ", File.ReadAllText(_paths.ConfigFile));
        Assert.True(service.Current.Privacy.OfflineMode);
    }

    [Fact]
    public void WrongValueTypeIsReportedWithTheSettingName()
    {
        File.WriteAllText(_paths.ConfigFile, """{ "schemaVersion": 1, "performance": { "maxParallelTasks": "lots" } }""");
        var result = CreateService().Load();
        Assert.True(result.UsingSafeDefaults);
        Assert.Contains("maxParallelTasks", result.FailureMessage);
    }

    [Fact]
    public void ConfigurationFromANewerVersionIsNotUsedOrOverwritten()
    {
        File.WriteAllText(_paths.ConfigFile, """{ "schemaVersion": 99 }""");
        var result = CreateService().Load();
        Assert.True(result.UsingSafeDefaults);
        Assert.Contains("newer version", result.FailureMessage);
        Assert.Contains("99", File.ReadAllText(_paths.ConfigFile));
    }

    [Theory]
    [InlineData("""{ "schemaVersion": 1, "safety": { "confirmPermanentDeletion": false } }""", "safety.confirmPermanentDeletion")]
    [InlineData("""{ "schemaVersion": 1, "safety": { "enforcePathValidation": false } }""", "safety.enforcePathValidation")]
    [InlineData("""{ "schemaVersion": 1, "quarantine": { "verifyIntegrity": false } }""", "quarantine.verifyIntegrity")]
    [InlineData("""{ "schemaVersion": 1, "ruleUpdates": { "endpoint": "http://example.com/rules" } }""", "ruleUpdates.endpoint")]
    [InlineData("""{ "schemaVersion": 1, "performance": { "maxParallelTasks": 0 } }""", "performance.maxParallelTasks")]
    [InlineData("""{ "schemaVersion": 1, "scan": { "customDirectories": [ "relative/path" ] } }""", "scan.customDirectories")]
    [InlineData("""{ "schemaVersion": 1, "safety": { "skipConfirmations": true } }""", "safety.skipConfirmations")]
    [InlineData("""{ "schemaVersion": 1, "accessibility": { "fontScale": 5 } }""", "accessibility.fontScale")]
    [InlineData("""{ "schemaVersion": 1, "logging": { "level": "Loud" } }""", "logging.level")]
    [InlineData("""{ "schemaVersion": 1, "ruleUpdates": { "additionalTrustedPublicKeys": [ "not-a-key" ] } }""", "ruleUpdates.additionalTrustedPublicKeys[0]")]
    public void UnsafeOrInvalidValuesAreErrors(string json, string setting)
    {
        File.WriteAllText(_paths.ConfigFile, json);
        var service = CreateService();
        var result = service.Load();

        Assert.True(result.UsingSafeDefaults);
        Assert.Contains(result.Validation.Errors, e => e.Setting == setting);
        Assert.All(result.Validation.Errors, e => Assert.False(string.IsNullOrWhiteSpace(e.HowToFix)));
        Assert.True(service.Current.Safety.ConfirmPermanentDeletion);
    }

    [Fact]
    public void UnknownNonCriticalSettingsAreWarnings()
    {
        File.WriteAllText(_paths.ConfigFile, """{ "schemaVersion": 1, "scan": { "colourOfMods": "blue" } }""");
        var result = CreateService().Load();
        Assert.False(result.UsingSafeDefaults);
        Assert.Contains(result.Validation.Warnings, w => w.Setting == "scan.colourOfMods");
    }

    [Fact]
    public void SaveCreatesABackupAndWritesAtomically()
    {
        var service = CreateService();
        service.Load();
        var config = service.CloneCurrent();
        config.Performance.MaxParallelTasks = 1;

        var save = service.Save(config, "test");

        Assert.True(save.Succeeded, save.Message);
        Assert.NotNull(save.BackupPath);
        Assert.True(File.Exists(save.BackupPath));
        Assert.Equal(1, service.Current.Performance.MaxParallelTasks);
        Assert.Contains("\"maxParallelTasks\": 1", File.ReadAllText(_paths.ConfigFile));
        Assert.Empty(Directory.GetFiles(_paths.DataRoot, "*.tmp"));
    }

    [Fact]
    public void InvalidConfigurationIsNotSaved()
    {
        var service = CreateService();
        service.Load();
        var before = File.ReadAllText(_paths.ConfigFile);
        var config = service.CloneCurrent();
        config.Safety.ConfirmPermanentDeletion = false;

        var save = service.Save(config, "test");

        Assert.False(save.Succeeded);
        Assert.Equal(before, File.ReadAllText(_paths.ConfigFile));
    }

    [Fact]
    public void RestoreDefaultsBacksUpAndResets()
    {
        var service = CreateService();
        service.Load();
        var config = service.CloneCurrent();
        config.Scan.MaxFileSizeMegabytes = 10;
        service.Save(config, "change");

        var result = service.RestoreDefaults();

        Assert.True(result.Succeeded);
        Assert.Equal(256, service.Current.Scan.MaxFileSizeMegabytes);
        Assert.NotEmpty(service.ListBackups());
    }

    [Fact]
    public void ReloadPicksUpExternalEdits()
    {
        var service = CreateService();
        service.Load();
        var text = File.ReadAllText(_paths.ConfigFile).Replace("\"maxParallelTasks\": 2", "\"maxParallelTasks\": 3");
        File.WriteAllText(_paths.ConfigFile, text);

        service.Load();

        Assert.Equal(3, service.Current.Performance.MaxParallelTasks);
    }

    [Fact]
    public void ExportWritesTheEffectiveConfiguration()
    {
        var service = CreateService();
        service.Load();
        var export = _temp.Combine("exported.json");
        service.Export(export);
        Assert.Equal(service.SerializeEffective(), File.ReadAllText(export));
    }

    [Fact]
    public void MigrationRunsInOrderAndBacksUpTheOriginal()
    {
        File.WriteAllText(_paths.ConfigFile, """{ "schemaVersion": 1, "oldThreads": 3 }""");
        var migrator = new ConfigMigrator([new TestMigration()], targetVersion: 2);
        var service = new ConfigurationService(_paths, TestPolicies.Create(), migrator: migrator);

        var result = service.Load();

        Assert.NotNull(result.Migration);
        Assert.Equal(1, result.Migration!.FromVersion);
        Assert.Equal(2, result.Migration.ToVersion);
        Assert.NotNull(result.BackupPath);
        Assert.Contains("oldThreads", File.ReadAllText(result.BackupPath!));
        var migrated = JsonNode.Parse(File.ReadAllText(_paths.ConfigFile))!.AsObject();
        Assert.Equal(2, (int)migrated["schemaVersion"]!);
        Assert.Equal(3, (int)migrated["performance"]!["maxParallelTasks"]!);
        Assert.False(migrated.ContainsKey("oldThreads"));
    }

    [Fact]
    public void MissingMigrationStepIsReported()
    {
        File.WriteAllText(_paths.ConfigFile, """{ "schemaVersion": 1 }""");
        var service = new ConfigurationService(_paths, TestPolicies.Create(), migrator: new ConfigMigrator([], targetVersion: 3));
        var result = service.Load();
        Assert.True(result.UsingSafeDefaults);
        Assert.Contains("No migration", result.FailureMessage);
    }

    private sealed class TestMigration : IConfigMigration
    {
        public int FromVersion => 1;

        public int ToVersion => 2;

        public string Description => "Move oldThreads to performance.maxParallelTasks";

        public void Apply(JsonObject document)
        {
            var threads = document["oldThreads"]?.GetValue<int>() ?? 2;
            document.Remove("oldThreads");
            document["performance"] = new JsonObject { ["maxParallelTasks"] = threads };
        }
    }
}
