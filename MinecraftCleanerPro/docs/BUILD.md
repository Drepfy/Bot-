# Build and release

## Requirements

- .NET 10 SDK, **10.0.100 or newer**. `global.json` uses `rollForward: latestFeature`, so newer 10.0 feature bands
  are accepted; the build log records the exact version used. .NET 10 is an LTS release.
- Windows 10/11 to run the application and the Windows-only tests. Linux/macOS can compile, test the
  platform-independent code and publish the Windows executable (`EnableWindowsTargeting`).
- Python 3 for the XAML resource check. `scripts/build.ps1` and `scripts/build.sh` require it; it is only optional
  if you run the `dotnet` commands yourself.

Packages are restored only from nuget.org (`NuGet.config`), with versions pinned centrally in
`Directory.Packages.props`. Warnings are treated as errors.

## Commands

```powershell
pwsh scripts/build.ps1            # check XAML, build, test, publish, SHA-256, self-test the exe
pwsh scripts/build.ps1 -SmokeUi   # additionally open every page of the GUI once
pwsh scripts/build.ps1 -SkipTests
```
```bash
./scripts/build.sh                # Linux/macOS equivalent (no self-test; the exe needs Windows)
SKIP_TESTS=1 ./scripts/build.sh
```

Manual steps:
```bash
dotnet build MinecraftCleanerPro.sln -c Release
dotnet test  MinecraftCleanerPro.sln -c Release
dotnet publish src/CleanerPro.App/CleanerPro.App.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o artifacts/publish
```

## Distribution decision: self-contained single file

The release is **one self-contained `MinecraftCleanerPro.exe`** (win-x64, compressed, ~62 MB) that includes
the .NET 10 runtime and WPF, so users do not need to install .NET and cannot end up on an unsupported runtime.
The trade-off is size and that runtime security fixes require a new build. A framework-dependent build is
possible with `--self-contained false` if you prefer servicing through Windows Update / the .NET installer.
Symbols are embedded (`DebugType=embedded`), so no extra files are published.

## Verifying a published executable

```powershell
# It is a windowed program, so wait for it to exit before reading the exit code.
$p = Start-Process .\MinecraftCleanerPro.exe -ArgumentList '--self-test', "`"$env:TEMP\mcp-selftest.json`"", '--data-root', "`"$env:TEMP\mcp-selftest`"" -Wait -PassThru; $p.ExitCode
$p = Start-Process .\MinecraftCleanerPro.exe -ArgumentList '--smoke-ui', "`"$env:TEMP\mcp-smoke.log`"", '--data-root', "`"$env:TEMP\mcp-smoke`"" -Wait -PassThru; $p.ExitCode
```
`--self-test` runs headlessly against harmless fixtures in a temporary folder (configuration, rules, scan,
quarantine, restore, path protection, reports, offline mode) and writes a JSON result; exit code 0 = passed.
`--smoke-ui` opens the main window, visits every page and exits; exit code 0 = no UI error.
`--data-root` keeps test data away from your real `%LocalAppData%\MinecraftCleanerPro`.

## Reproducibility

Builds are deterministic: publishing twice on the same machine with the same SDK produced byte-identical
executables (see TEST-RESULTS.md). Different SDK patch versions or source paths can change the bytes; the
CI workflow records the SHA-256 of every build it produces.

## Continuous integration and releases

- `.github/workflows/build.yml` runs on every push to `main` and every pull request, on `windows-latest`: XAML
  check, Release build, all tests (including Windows-only ones), single-file publish, SHA-256, the executable's
  `--self-test` and `--smoke-ui`. The executable, hash, self-test result, smoke log and test results are kept as
  the `MinecraftCleanerPro-win-x64` artifact (downloadable by anyone signed in to GitHub, for GitHub's artifact
  retention period). For a download that needs no account, use a release.
- `.github/workflows/release.yml` publishes the `Version` in `Directory.Build.props` when it has no release yet:
  when such a commit reaches `main`, when a tag `v<version>` is pushed (it refuses a tag that does not match the
  version), or when it is started by hand from the Actions page. Pushes of a version that is already released do
  nothing. It runs the same build and every verification, and only if all of them pass creates the tag and a
  public GitHub Release with `MinecraftCleanerPro.exe`, its `.sha256` and the release notes for that version from
  `docs/RELEASE-NOTES.md`. Anyone can download it without a GitHub account; the newest is
  always at `https://github.com/Drepfy/MinecraftCleanerPro/releases/latest/download/MinecraftCleanerPro.exe`.

## Code signing

This release is **unsigned** — no code-signing certificate was available. Do not present it as signed.
To sign: `signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256 /f <cert.pfx> artifacts\publish\MinecraftCleanerPro.exe`
and publish the new SHA-256.

## Release checklist

1. Update `Version` in `Directory.Build.props` and `docs/RELEASE-NOTES.md`.
2. If rules changed: bump `databaseVersion`/`displayVersion`, run `CleanerPro.RuleTool validate`.
3. `pwsh scripts/build.ps1 -SmokeUi` on Windows (or let CI run).
4. Push the commit to `main`. Because the new version has no release yet, the release workflow builds, verifies
   and publishes the download.
