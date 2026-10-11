namespace CleanerPro.Scanner.Inspection;

/// <summary>
/// Shared upper bound for in-memory buffers (nested archives, class files) across all scan workers.
/// Requests larger than the whole budget are refused instead of blocking forever.
/// </summary>
public sealed class MemoryBudget
{
    private readonly object _gate = new();
    private long _available;

    public MemoryBudget(long totalBytes)
    {
        TotalBytes = Math.Max(totalBytes, 1);
        _available = TotalBytes;
    }

    public long TotalBytes { get; }

    public long InUse
    {
        get
        {
            lock (_gate)
            {
                return TotalBytes - _available;
            }
        }
    }

    /// <summary>Reserves memory, waiting for other workers to release it. Returns null if the request can never fit.</summary>
    public Lease? Acquire(long bytes, CancellationToken cancellationToken)
    {
        if (bytes > TotalBytes)
        {
            return null;
        }

        lock (_gate)
        {
            while (_available < bytes)
            {
                cancellationToken.ThrowIfCancellationRequested();
                Monitor.Wait(_gate, 100);
            }

            _available -= bytes;
        }

        return new Lease(this, bytes);
    }

    private void Release(long bytes)
    {
        lock (_gate)
        {
            _available = Math.Min(TotalBytes, _available + bytes);
            Monitor.PulseAll(_gate);
        }
    }

    public sealed class Lease : IDisposable
    {
        private readonly MemoryBudget _owner;
        private long _bytes;

        internal Lease(MemoryBudget owner, long bytes)
        {
            _owner = owner;
            _bytes = bytes;
        }

        public void Dispose()
        {
            var bytes = Interlocked.Exchange(ref _bytes, 0);
            if (bytes > 0)
            {
                _owner.Release(bytes);
            }
        }
    }
}
