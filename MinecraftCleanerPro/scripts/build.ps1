<#
.SYNOPSIS
  Reproducible build for Minecraft Cleaner Pro Ultimate on Windows.

.DESCRIPTION
  1. Checks XAML resource references.
  2. Builds the solution in Release.
  3. Runs every automated test (results in artifacts/TestResults).
  4. Publishes a self-contained, single-file win-x64 executable (no .NET install needed) to artifacts/publish.
  5. Writes the SHA-256 of the executable.
  6. Runs the executable's headless self-test (and, with -SmokeUi, opens every page once).

.EXAMPLE
  pwsh scripts/build.ps1
  pwsh scripts/build.ps1 -SkipTests -SmokeUi
#>
param(
    [switch]$SkipTests,
    [switch]$SmokeUi,
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$artifacts = Join-Path $root "artifacts"
New-Item -ItemType Directory -Force -Path $artifacts | Out-Null

Write-Host "== .NET SDK" -ForegroundColor Cyan
dotnet --version

Write-Host "== XAML resource check" -ForegroundColor Cyan
python scripts/check-xaml-resources.py
if ($LASTEXITCODE -ne 0) { throw "XAML resource check failed" }

Write-Host "== Build" -ForegroundColor Cyan
dotnet build MinecraftCleanerPro.sln -c $Configuration
if ($LASTEXITCODE -ne 0) { throw "Build failed" }

if (-not $SkipTests) {
    Write-Host "== Tests" -ForegroundColor Cyan
    dotnet test MinecraftCleanerPro.sln -c $Configuration --no-build --results-directory "$artifacts/TestResults" --logger "trx" --logger "console;verbosity=normal"
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
}

Write-Host "== Publish (self-contained single-file win-x64)" -ForegroundColor Cyan
$publish = Join-Path $artifacts "publish"
dotnet publish src/CleanerPro.App/CleanerPro.App.csproj -c $Configuration -r win-x64 --self-contained true -p:PublishSingleFile=true -o $publish
if ($LASTEXITCODE -ne 0) { throw "Publish failed" }

$exe = Join-Path $publish "MinecraftCleanerPro.exe"
$hash = (Get-FileHash -Algorithm SHA256 $exe).Hash.ToLowerInvariant()
"$hash  MinecraftCleanerPro.exe" | Set-Content -Encoding ascii (Join-Path $publish "MinecraftCleanerPro.exe.sha256")
Write-Host "SHA-256: $hash"

Write-Host "== Self-test of the published executable" -ForegroundColor Cyan
$selfTest = Join-Path $artifacts "selftest.json"
$dataRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("mcp-selftest-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$process = Start-Process -FilePath $exe -ArgumentList @("--self-test", "`"$selfTest`"", "--data-root", "`"$dataRoot`"") -Wait -PassThru
Get-Content $selfTest
if ($process.ExitCode -ne 0) { throw "Self-test failed with exit code $($process.ExitCode)" }

if ($SmokeUi) {
    Write-Host "== UI smoke test" -ForegroundColor Cyan
    $smokeLog = Join-Path $artifacts "smoke-ui.log"
    $uiData = Join-Path ([System.IO.Path]::GetTempPath()) ("mcp-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    $ui = Start-Process -FilePath $exe -ArgumentList @("--smoke-ui", "`"$smokeLog`"", "--data-root", "`"$uiData`"") -Wait -PassThru
    Get-Content $smokeLog
    if ($ui.ExitCode -ne 0) { throw "UI smoke test failed with exit code $($ui.ExitCode)" }
}

Write-Host "Done. Executable: $exe" -ForegroundColor Green
