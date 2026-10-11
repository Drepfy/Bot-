using System.Security.Cryptography;

namespace CleanerPro.Infrastructure;

public sealed record FileHashes(string Sha256, string? Sha1, long Length);

/// <summary>Streams a file once and computes SHA-256 (and optionally SHA-1) without loading it into memory.</summary>
public static class FileHasher
{
    public const int DefaultBufferSize = 1024 * 1024;

    public static FileHashes Compute(string path, bool includeSha1, int bufferSize = DefaultBufferSize, CancellationToken cancellationToken = default)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete, 4096, FileOptions.SequentialScan);
        return Compute(stream, includeSha1, bufferSize, cancellationToken);
    }

    public static FileHashes Compute(Stream stream, bool includeSha1, int bufferSize = DefaultBufferSize, CancellationToken cancellationToken = default)
    {
        using var sha256 = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        using var sha1 = includeSha1 ? IncrementalHash.CreateHash(HashAlgorithmName.SHA1) : null;
        var buffer = new byte[Math.Clamp(bufferSize, 4096, 16 * 1024 * 1024)];
        long total = 0;
        int read;
        while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
        {
            cancellationToken.ThrowIfCancellationRequested();
            sha256.AppendData(buffer, 0, read);
            sha1?.AppendData(buffer, 0, read);
            total += read;
        }

        return new FileHashes(
            Convert.ToHexString(sha256.GetHashAndReset()).ToLowerInvariant(),
            sha1 is null ? null : Convert.ToHexString(sha1.GetHashAndReset()).ToLowerInvariant(),
            total);
    }

    public static string Sha256Hex(ReadOnlySpan<byte> data) => Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();
}
