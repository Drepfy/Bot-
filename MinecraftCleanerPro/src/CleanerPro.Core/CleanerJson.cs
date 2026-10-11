using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CleanerPro.Core;

/// <summary>Shared JSON settings so every persisted file uses the same, readable format.</summary>
public static class CleanerJson
{
    /// <summary>Indented, camelCase, enums as strings. Used for configuration, reports and history.</summary>
    public static JsonSerializerOptions Default { get; } = Create(writeIndented: true);

    /// <summary>Single-line variant for append-only JSON-lines logs.</summary>
    public static JsonSerializerOptions Compact { get; } = Create(writeIndented: false);

    private static JsonSerializerOptions Create(bool writeIndented)
    {
        var options = new JsonSerializerOptions
        {
            WriteIndented = writeIndented,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            // DictionaryKeyPolicy is intentionally not set: dictionary keys are data (file paths,
            // display names) and must round-trip unchanged.
            ReadCommentHandling = JsonCommentHandling.Skip,
            AllowTrailingCommas = true,
            PropertyNameCaseInsensitive = true,
            MaxDepth = 64,
        };
        options.Converters.Add(new JsonStringEnumConverter());
        options.MakeReadOnly(populateMissingResolver: true);
        return options;
    }
}

/// <summary>Application identity information.</summary>
public static class AppInfo
{
    public const string ProductName = "Minecraft Cleaner Pro Ultimate";

    public const string DataFolderName = "MinecraftCleanerPro";

    public static string Version { get; } =
        typeof(AppInfo).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "1.1.0";
}
