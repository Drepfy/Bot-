using System.Text;
using System.Text.Json;
using CleanerPro.Core;
using CleanerPro.Core.Models;

namespace CleanerPro.Infrastructure;

/// <summary>Append-only audit log of every quarantine, restore and permanent deletion.</summary>
public sealed class OperationLog
{
    private readonly string _path;
    private readonly object _gate = new();

    public OperationLog(string path)
    {
        _path = path;
    }

    public string FilePath => _path;

    public void Append(OperationRecord record)
    {
        var line = JsonSerializer.Serialize(record, CleanerJson.Compact) + "\n";
        lock (_gate)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_path)!);
            using var stream = new FileStream(_path, FileMode.Append, FileAccess.Write, FileShare.Read);
            var bytes = Encoding.UTF8.GetBytes(line);
            stream.Write(bytes);
            stream.Flush(flushToDisk: true);
        }
    }

    public IReadOnlyList<OperationRecord> ReadAll()
    {
        lock (_gate)
        {
            if (!File.Exists(_path))
            {
                return [];
            }

            var records = new List<OperationRecord>();
            foreach (var line in File.ReadLines(_path))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                try
                {
                    var record = JsonSerializer.Deserialize<OperationRecord>(line, CleanerJson.Compact);
                    if (record is not null)
                    {
                        records.Add(record);
                    }
                }
                catch (JsonException)
                {
                    // A torn final line (for example after a power loss) is ignored rather than failing the whole log.
                }
            }

            return records;
        }
    }

    public void Clear()
    {
        lock (_gate)
        {
            AtomicFile.TryDelete(_path);
        }
    }
}
