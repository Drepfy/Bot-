namespace CleanerPro.App.Composition;

/// <summary>
/// Supported command-line options (all optional):
///   --data-root &lt;folder&gt;     use a different data folder (for testing; default %LocalAppData%\MinecraftCleanerPro)
///   --self-test &lt;result.json&gt; run the headless self-test and exit (0 = passed)
///   --smoke-ui &lt;log.txt&gt;      open every page once, write a log and exit (used by CI on Windows)
/// </summary>
public sealed record CommandLine(string? DataRoot, string? SelfTestOutput, string? SmokeUiLog)
{
    public static CommandLine Parse(IReadOnlyList<string> args)
    {
        string? dataRoot = null, selfTest = null, smoke = null;
        for (var i = 0; i < args.Count; i++)
        {
            string? Next() => i + 1 < args.Count ? args[++i] : null;
            switch (args[i].ToLowerInvariant())
            {
                case "--data-root":
                    dataRoot = Next();
                    break;
                case "--self-test":
                    selfTest = Next() ?? "selftest-result.json";
                    break;
                case "--smoke-ui":
                    smoke = Next() ?? "smoke-ui.log";
                    break;
            }
        }

        return new CommandLine(dataRoot, selfTest, smoke);
    }
}
