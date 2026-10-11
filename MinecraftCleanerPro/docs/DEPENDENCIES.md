# Dependency manifest

All versions are pinned in `Directory.Packages.props`; packages come only from nuget.org (`NuGet.config`).

## Runtime (shipped in the executable)

| Package | Version | Publisher / licence | Used by | Filesystem access | Network access |
|---|---|---|---|---|---|
| .NET 10 runtime + Windows Desktop (WPF) | 10.0.x (self-contained) | Microsoft, MIT | everything | yes (through our code only) | only through `GuardedHttpClient` |
| Microsoft.Extensions.DependencyInjection | 10.0.12 | Microsoft, MIT | App (composition root) | no | no |
| Microsoft.Extensions.Logging | 10.0.12 | Microsoft, MIT | App (logger factory) | no | no |
| Microsoft.Extensions.Logging.Abstractions | 10.0.12 | Microsoft, MIT | libraries (`ILogger`) | no | no |

Everything else is part of the .NET base class library: `System.IO.Compression` (archives, read-only),
`System.Security.Cryptography` (SHA-256/SHA-1, ECDSA, HMAC), `System.Text.Json`, `System.Net.Http`
(only via `GuardedHttpClient`), `Microsoft.Win32.Registry` (read-only `HKCU\…\Run`). Windows APIs called
through P/Invoke: `wintrust.dll!WinVerifyTrust` (offline Authenticode check) and
`kernel32.dll!SetThreadPriority/GetCurrentThread` (background priority).

The only file logging is our own JSON-lines logger (`JsonFileLoggerProvider`); no third-party logging,
telemetry or crash-reporting library is used.

## Test-only (not shipped)

| Package | Version | Licence |
|---|---|---|
| Microsoft.NET.Test.Sdk | 17.14.1 | MIT |
| xunit | 2.9.3 | Apache-2.0 |
| xunit.runner.visualstudio | 3.1.5 | Apache-2.0 |

## Audit

- Network behaviour: none of the runtime packages above performs network I/O. Verified by design review and by
  tests that run full scans with a counting HTTP handler (zero requests).
- Known vulnerabilities: `dotnet list package --vulnerable --include-transitive` should be run before each
  release; its output for this release is recorded in TEST-RESULTS.md.
- No unrelated executables, installers or binary files are bundled. The rule database is a JSON text file
  embedded as a resource.
