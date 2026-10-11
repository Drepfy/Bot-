using System.Security.Cryptography;
using System.Text;

namespace CleanerPro.Detection.Rules;

/// <summary>
/// Detached ECDSA P-256 / SHA-256 signatures for rule databases. The signature file contains the
/// base64 DER-encoded signature over the exact bytes of rules.json.
/// </summary>
public static class RuleSignature
{
    /// <summary>
    /// Public keys compiled into the application that are trusted to sign rule updates.
    /// This release ships without an official update service, so the list is intentionally empty;
    /// organisations can trust their own key through ruleUpdates.additionalTrustedPublicKeys.
    /// </summary>
    public static IReadOnlyList<string> BuiltInTrustedPublicKeys { get; } = [];

    public static string Sign(byte[] data, ECDsa privateKey) =>
        Convert.ToBase64String(privateKey.SignData(data, HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence));

    /// <summary>Verifies the signature against any trusted key. Returns the fingerprint of the key that verified it.</summary>
    public static bool Verify(byte[] data, string signatureText, IEnumerable<string> trustedPublicKeys, out string? keyFingerprint)
    {
        keyFingerprint = null;
        byte[] signature;
        try
        {
            signature = Convert.FromBase64String(signatureText.Trim());
        }
        catch (FormatException)
        {
            return false;
        }

        foreach (var key in trustedPublicKeys)
        {
            try
            {
                using var ecdsa = ECDsa.Create();
                ecdsa.ImportSubjectPublicKeyInfo(Convert.FromBase64String(key), out _);
                if (ecdsa.KeySize != 256)
                {
                    continue;
                }

                if (ecdsa.VerifyData(data, signature, HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence))
                {
                    keyFingerprint = Fingerprint(key);
                    return true;
                }
            }
            catch (Exception ex) when (ex is FormatException or CryptographicException)
            {
                // An invalid key cannot verify anything; configuration validation reports it separately.
            }
        }

        return false;
    }

    public static string Fingerprint(string publicKeyBase64)
    {
        var bytes = SHA256.HashData(Encoding.ASCII.GetBytes(publicKeyBase64.Trim()));
        return Convert.ToHexString(bytes, 0, 8).ToLowerInvariant();
    }

    public static (string PrivateKeyPem, string PublicKeyBase64) GenerateKeyPair()
    {
        using var ecdsa = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        return (ecdsa.ExportPkcs8PrivateKeyPem(), Convert.ToBase64String(ecdsa.ExportSubjectPublicKeyInfo()));
    }
}
