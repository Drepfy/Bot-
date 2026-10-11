using System.Text;
using System.Text.Json;
using CleanerPro.Core;
using Microsoft.Extensions.Logging;

namespace CleanerPro.Infrastructure.Logging;

public sealed record FileLoggerOptions
{
    public required string Directory { get; init; }

    public LogLevel MinimumLevel { get; init; } = LogLevel.Information;

    public int RetentionDays { get; init; } = 14;

    public long MaxFileBytes { get; init; } = 10L * 1024 * 1024;

    public long MaxTotalBytes { get; init; } = 100L * 1024 * 1024;
}

/// <summary>
/// Structured (JSON lines) file logger with size-capped files and retention. Logs stay on this computer
/// and never contain file contents.
/// </summary>
public sealed class JsonFileLoggerProvider : ILoggerProvider
{
    private static readonly JsonSerializerOptions LogJson = new() { WriteIndented = false };

    private readonly object _gate = new();
    private FileLoggerOptions _options;
    private StreamWriter? _writer;
    private string? _currentFile;
    private long _currentSize;
    private bool _disposed;

    public JsonFileLoggerProvider(FileLoggerOptions options)
    {
        _options = options;
        System.IO.Directory.CreateDirectory(options.Directory);
        ApplyRetention();
    }

    public FileLoggerOptions Options => _options;

    public void UpdateOptions(FileLoggerOptions options)
    {
        lock (_gate)
        {
            _options = options;
            System.IO.Directory.CreateDirectory(options.Directory);
            CloseWriter();
        }

        ApplyRetention();
    }

    public ILogger CreateLogger(string categoryName) => new JsonFileLogger(this, categoryName);

    internal bool IsEnabled(LogLevel level) => level != LogLevel.None && level >= _options.MinimumLevel;

    internal void Write(LogLevel level, string category, EventId eventId, string message, Exception? exception, IReadOnlyList<KeyValuePair<string, object?>>? state)
    {
        var entry = new Dictionary<string, object?>
        {
            ["timestamp"] = DateTimeOffset.UtcNow.ToString("O"),
            ["level"] = level.ToString(),
            ["category"] = category,
            ["message"] = message,
        };
        if (eventId.Id != 0)
        {
            entry["eventId"] = eventId.Id;
        }

        if (state is not null)
        {
            foreach (var (key, value) in state)
            {
                if (key != "{OriginalFormat}")
                {
                    entry[key] = value?.ToString();
                }
            }
        }

        if (exception is not null)
        {
            entry["exception"] = exception.ToString();
        }

        string line;
        try
        {
            line = JsonSerializer.Serialize(entry, LogJson);
        }
        catch (Exception ex) when (ex is NotSupportedException or JsonException)
        {
            line = JsonSerializer.Serialize(new { timestamp = DateTimeOffset.UtcNow, level = level.ToString(), category, message }, LogJson);
        }

        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            try
            {
                EnsureWriter(Encoding.UTF8.GetByteCount(line) + 1);
                _writer!.WriteLine(line);
                _writer.Flush();
                _currentSize += Encoding.UTF8.GetByteCount(line) + 1;
            }
            catch (IOException)
            {
                // Logging must never crash the application (for example when the disk is full).
                CloseWriter();
            }
            catch (UnauthorizedAccessException)
            {
                CloseWriter();
            }
        }
    }

    private void EnsureWriter(int nextBytes)
    {
        var today = DateTime.UtcNow.ToString("yyyyMMdd");
        if (_writer is not null && _currentFile is not null &&
            Path.GetFileName(_currentFile).Contains(today, StringComparison.Ordinal) &&
            _currentSize + nextBytes <= _options.MaxFileBytes)
        {
            return;
        }

        CloseWriter();
        for (var index = 0; index < 1000; index++)
        {
            var candidate = Path.Combine(_options.Directory, index == 0 ? $"cleanerpro-{today}.log" : $"cleanerpro-{today}-{index}.log");
            var size = File.Exists(candidate) ? new FileInfo(candidate).Length : 0;
            if (size + nextBytes <= _options.MaxFileBytes || size == 0)
            {
                var stream = new FileStream(candidate, FileMode.Append, FileAccess.Write, FileShare.ReadWrite | FileShare.Delete);
                _writer = new StreamWriter(stream, new UTF8Encoding(false));
                _currentFile = candidate;
                _currentSize = size;
                return;
            }
        }

        throw new IOException("Too many log files for today.");
    }

    /// <summary>Deletes logs older than the retention period and trims the oldest files above the total size cap.</summary>
    public void ApplyRetention()
    {
        lock (_gate)
        {
            try
            {
                var files = new DirectoryInfo(_options.Directory).GetFiles("cleanerpro-*.log")
                    .OrderByDescending(f => f.LastWriteTimeUtc)
                    .ToList();
                var cutoff = DateTime.UtcNow.AddDays(-Math.Max(1, _options.RetentionDays));
                long total = 0;
                foreach (var file in files)
                {
                    total += file.Length;
                    var isCurrent = _currentFile is not null && string.Equals(file.FullName, _currentFile, PathKey.Comparison);
                    if (!isCurrent && (file.LastWriteTimeUtc < cutoff || total > _options.MaxTotalBytes))
                    {
                        file.Delete();
                    }
                }
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }

    private void CloseWriter()
    {
        _writer?.Dispose();
        _writer = null;
        _currentFile = null;
        _currentSize = 0;
    }

    public void Dispose()
    {
        lock (_gate)
        {
            _disposed = true;
            CloseWriter();
        }
    }

    private sealed class JsonFileLogger(JsonFileLoggerProvider provider, string category) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => provider.IsEnabled(logLevel);

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel))
            {
                return;
            }

            provider.Write(logLevel, category, eventId, formatter(state, exception), exception, state as IReadOnlyList<KeyValuePair<string, object?>>);
        }
    }
}
