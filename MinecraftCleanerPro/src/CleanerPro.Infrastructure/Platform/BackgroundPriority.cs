using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace CleanerPro.Infrastructure.Platform;

/// <summary>
/// Lowers the CPU, I/O and memory priority of the current (dedicated) worker thread on Windows using
/// THREAD_MODE_BACKGROUND_BEGIN. Must be disposed on the same thread. Has no effect elsewhere.
/// </summary>
public sealed partial class BackgroundPriority : IDisposable
{
    private const int ThreadModeBackgroundBegin = 0x00010000;
    private const int ThreadModeBackgroundEnd = 0x00020000;

    private readonly bool _windowsBackgroundMode;
    private readonly ThreadPriority _previousPriority;

    private BackgroundPriority(bool windowsBackgroundMode, ThreadPriority previousPriority)
    {
        _windowsBackgroundMode = windowsBackgroundMode;
        _previousPriority = previousPriority;
    }

    public static BackgroundPriority Enter(bool enabled)
    {
        var previous = Thread.CurrentThread.Priority;
        if (!enabled)
        {
            return new BackgroundPriority(false, previous);
        }

        try
        {
            Thread.CurrentThread.Priority = ThreadPriority.BelowNormal;
        }
        catch (Exception ex) when (ex is ThreadStateException or PlatformNotSupportedException)
        {
        }

        var background = false;
        if (OperatingSystem.IsWindows())
        {
            background = TrySetBackground(ThreadModeBackgroundBegin);
        }

        return new BackgroundPriority(background, previous);
    }

    public void Dispose()
    {
        if (_windowsBackgroundMode && OperatingSystem.IsWindows())
        {
            TrySetBackground(ThreadModeBackgroundEnd);
        }

        try
        {
            Thread.CurrentThread.Priority = _previousPriority;
        }
        catch (Exception ex) when (ex is ThreadStateException or PlatformNotSupportedException)
        {
        }
    }

    [SupportedOSPlatform("windows")]
    private static bool TrySetBackground(int mode)
    {
        try
        {
            return SetThreadPriority(GetCurrentThread(), mode);
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
        {
            return false;
        }
    }

    [LibraryImport("kernel32.dll")]
    [SupportedOSPlatform("windows")]
    private static partial IntPtr GetCurrentThread();

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [SupportedOSPlatform("windows")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool SetThreadPriority(IntPtr thread, int priority);
}
