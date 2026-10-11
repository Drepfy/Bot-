using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Cryptography.X509Certificates;

namespace CleanerPro.Infrastructure.Platform;

public enum SignatureStatus
{
    NotChecked,
    NotSigned,
    Valid,
    Invalid,
    Unsupported,
}

public sealed record SignatureInfo(SignatureStatus Status, string? Subject, string Detail);

/// <summary>
/// Verifies Windows Authenticode signatures with WinVerifyTrust. The check is performed offline
/// (no revocation lookup), so a valid result means "signed and untampered", not "revocation verified".
/// </summary>
public static partial class AuthenticodeVerifier
{
    private static readonly Guid GenericVerifyV2 = new("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");

    public static SignatureInfo Verify(string path)
    {
        if (!OperatingSystem.IsWindows())
        {
            return new SignatureInfo(SignatureStatus.Unsupported, null, "Authenticode verification is only available on Windows.");
        }

        return VerifyWindows(path);
    }

    [SupportedOSPlatform("windows")]
    private static SignatureInfo VerifyWindows(string path)
    {
        var fileInfoPtr = IntPtr.Zero;
        var trustDataPtr = IntPtr.Zero;
        var pathPtr = Marshal.StringToCoTaskMemUni(path);
        try
        {
            var fileInfo = new WinTrustFileInfo
            {
                cbStruct = (uint)Marshal.SizeOf<WinTrustFileInfo>(),
                pcwszFilePath = pathPtr,
            };
            fileInfoPtr = Marshal.AllocCoTaskMem(Marshal.SizeOf<WinTrustFileInfo>());
            Marshal.StructureToPtr(fileInfo, fileInfoPtr, false);

            var trustData = new WinTrustData
            {
                cbStruct = (uint)Marshal.SizeOf<WinTrustData>(),
                dwUIChoice = 2, // WTD_UI_NONE
                fdwRevocationChecks = 0, // WTD_REVOKE_NONE: offline, no network access
                dwUnionChoice = 1, // WTD_CHOICE_FILE
                pFile = fileInfoPtr,
                dwStateAction = 0,
                dwProvFlags = 0x00000080 | 0x00001000, // WTD_REVOCATION_CHECK_NONE | WTD_CACHE_ONLY_URL_RETRIEVAL
            };
            trustDataPtr = Marshal.AllocCoTaskMem(Marshal.SizeOf<WinTrustData>());
            Marshal.StructureToPtr(trustData, trustDataPtr, false);

            var action = GenericVerifyV2;
            var result = WinVerifyTrust(new IntPtr(-1), ref action, trustDataPtr);
            var subject = TryGetSubject(path);
            return result switch
            {
                0 => new SignatureInfo(SignatureStatus.Valid, subject, "Authenticode signature is valid (revocation not checked)."),
                unchecked((int)0x800B0100) => new SignatureInfo(SignatureStatus.NotSigned, null, "The file is not digitally signed."),
                _ => new SignatureInfo(SignatureStatus.Invalid, subject, $"The signature did not verify (WinVerifyTrust 0x{result:X8})."),
            };
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException or ExternalException)
        {
            return new SignatureInfo(SignatureStatus.NotChecked, null, $"Signature verification failed to run: {ex.Message}");
        }
        finally
        {
            if (trustDataPtr != IntPtr.Zero)
            {
                Marshal.FreeCoTaskMem(trustDataPtr);
            }

            if (fileInfoPtr != IntPtr.Zero)
            {
                Marshal.FreeCoTaskMem(fileInfoPtr);
            }

            Marshal.FreeCoTaskMem(pathPtr);
        }
    }

    private static string? TryGetSubject(string path)
    {
        try
        {
#pragma warning disable SYSLIB0057 // There is no X509CertificateLoader equivalent for reading a certificate from an Authenticode-signed file.
            using var certificate = X509Certificate.CreateFromSignedFile(path);
#pragma warning restore SYSLIB0057
            return certificate.Subject;
        }
        catch (Exception ex) when (ex is System.Security.Cryptography.CryptographicException or IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    [LibraryImport("wintrust.dll", EntryPoint = "WinVerifyTrust")]
    [SupportedOSPlatform("windows")]
    private static partial int WinVerifyTrust(IntPtr hwnd, ref Guid pgActionId, IntPtr pWvtData);

    [StructLayout(LayoutKind.Sequential)]
    private struct WinTrustFileInfo
    {
        public uint cbStruct;
        public IntPtr pcwszFilePath;
        public IntPtr hFile;
        public IntPtr pgKnownSubject;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct WinTrustData
    {
        public uint cbStruct;
        public IntPtr pPolicyCallbackData;
        public IntPtr pSIPClientData;
        public uint dwUIChoice;
        public uint fdwRevocationChecks;
        public uint dwUnionChoice;
        public IntPtr pFile;
        public uint dwStateAction;
        public IntPtr hWVTStateData;
        public IntPtr pwszURLReference;
        public uint dwProvFlags;
        public uint dwUIContext;
        public IntPtr pSignatureSettings;
    }
}
