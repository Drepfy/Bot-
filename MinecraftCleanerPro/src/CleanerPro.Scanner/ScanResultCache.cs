using System.Text.Json;
using CleanerPro.Core;
using CleanerPro.Infrastructure;

namespace CleanerPro.Scanner;

/// <summary>
/// Remembers files that were fully inspected and produced no finding, keyed by path, size and
/// timestamp, and only for the exact rule database and detection settings used. Unchanged files can
/// then be skipped on the next scan. Files with findings or problems are never cached.
/// </summary>
public sealed class ScanResultCache
{
    private const int MaxEntries = 200_000;

    private readonly string _path;
    private readonly object _gate = new();
    private Dictionary<string, CacheEntry> _entries = new(StringComparer.Ordinal);
    private bool _dirty;

    public ScanResultCache(string path)
    {
        _path = path;
    }

    public int Count
    {
        get
        {
            lock (_gate)
            {
                return _entries.Count;
            }
        }
    }

    public sealed record CacheEntry(long Size, long LastWriteTicks, string Sha256, string Context);

    public void Load()
    {
        lock (_gate)
        {
            try
            {
                _entries = File.Exists(_path)
                    ? JsonSerializer.Deserialize<Dictionary<string, CacheEntry>>(File.ReadAllText(_path), CleanerJson.Compact) ?? new(StringComparer.Ordinal)
                    : new(StringComparer.Ordinal);
            }
            catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
            {
                _entries = new(StringComparer.Ordinal); // A damaged cache is simply discarded.
            }

            _dirty = false;
        }
    }

    public bool IsVerifiedClean(string pathKey, long size, DateTimeOffset lastWrite, string context)
    {
        lock (_gate)
        {
            return _entries.TryGetValue(pathKey, out var entry) && entry.Size == size &&
                   entry.LastWriteTicks == lastWrite.UtcTicks && entry.Context == context;
        }
    }

    public void MarkClean(string pathKey, long size, DateTimeOffset lastWrite, string sha256, string context)
    {
        lock (_gate)
        {
            if (_entries.Count >= MaxEntries && !_entries.ContainsKey(pathKey))
            {
                return;
            }

            _entries[pathKey] = new CacheEntry(size, lastWrite.UtcTicks, sha256, context);
            _dirty = true;
        }
    }

    public void Invalidate(string pathKey)
    {
        lock (_gate)
        {
            _dirty |= _entries.Remove(pathKey);
        }
    }

    public void Save()
    {
        lock (_gate)
        {
            if (!_dirty)
            {
                return;
            }

            try
            {
                AtomicFile.WriteAllText(_path, JsonSerializer.Serialize(_entries, CleanerJson.Compact));
                _dirty = false;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                // The cache is an optimisation only.
            }
        }
    }

    public void Clear()
    {
        lock (_gate)
        {
            _entries.Clear();
            _dirty = false;
            AtomicFile.TryDelete(_path);
        }
    }
}

/// <summary>Pause/resume signal shared by the scan producer and workers.</summary>
public sealed class PauseController : IDisposable
{
    private readonly ManualResetEventSlim _running = new(initialState: true);

    public bool IsPaused => !_running.IsSet;

    public void Pause() => _running.Reset();

    public void Resume() => _running.Set();

    public void WaitWhilePaused(CancellationToken cancellationToken) => _running.Wait(cancellationToken);

    public void Dispose() => _running.Dispose();
}
