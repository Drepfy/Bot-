using System.Text.Json.Nodes;

namespace CleanerPro.Configuration;

/// <summary>Upgrades a configuration document from one schema version to the next.</summary>
public interface IConfigMigration
{
    int FromVersion { get; }

    int ToVersion { get; }

    string Description { get; }

    void Apply(JsonObject document);
}

public sealed record MigrationOutcome(int FromVersion, int ToVersion, IReadOnlyList<string> AppliedSteps);

/// <summary>
/// Runs schema migrations in order. Schema 1 is the first released schema, so the production
/// migration list is currently empty; the mechanism is exercised by unit tests and is ready for
/// future schema changes.
/// </summary>
public sealed class ConfigMigrator
{
    private readonly IReadOnlyList<IConfigMigration> _migrations;

    public ConfigMigrator(IEnumerable<IConfigMigration>? migrations = null, int targetVersion = AppConfiguration.CurrentSchemaVersion)
    {
        _migrations = (migrations ?? []).OrderBy(m => m.FromVersion).ToList();
        TargetVersion = targetVersion;
    }

    public int TargetVersion { get; }

    public MigrationOutcome Migrate(JsonObject document)
    {
        var version = ReadVersion(document);
        var start = version;
        var applied = new List<string>();
        while (version < TargetVersion)
        {
            var step = _migrations.FirstOrDefault(m => m.FromVersion == version)
                       ?? throw new InvalidOperationException($"No migration is available from schema version {version}.");
            if (step.ToVersion <= step.FromVersion)
            {
                throw new InvalidOperationException($"Migration '{step.Description}' does not advance the schema version.");
            }

            step.Apply(document);
            version = step.ToVersion;
            document["schemaVersion"] = version;
            applied.Add($"{step.FromVersion} → {step.ToVersion}: {step.Description}");
        }

        return new MigrationOutcome(start, version, applied);
    }

    public static int ReadVersion(JsonObject document)
    {
        if (document.TryGetPropertyValue("schemaVersion", out var node) && node is JsonValue value && value.TryGetValue<int>(out var version))
        {
            return version;
        }

        // Treat a document without a version as the first schema; validation will report anything that does not fit.
        return 1;
    }
}
