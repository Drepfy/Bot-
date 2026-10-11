#!/usr/bin/env bash
# Reproducible build on Linux/macOS (cross-compiles the Windows executable).
# The WPF application can be compiled and published here, but it can only run on Windows;
# the Windows-only tests are reported as skipped. Use scripts/build.ps1 on Windows for the full run.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
configuration="${CONFIGURATION:-Release}"
artifacts="$root/artifacts"
mkdir -p "$artifacts"

echo "== .NET SDK"; dotnet --version
echo "== XAML resource check"; python3 scripts/check-xaml-resources.py
echo "== Build"; dotnet build MinecraftCleanerPro.sln -c "$configuration"

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  echo "== Tests"
  dotnet test MinecraftCleanerPro.sln -c "$configuration" --no-build --results-directory "$artifacts/TestResults" \
    --logger "trx" --logger "console;verbosity=minimal"
fi

echo "== Publish (self-contained single-file win-x64)"
dotnet publish src/CleanerPro.App/CleanerPro.App.csproj -c "$configuration" -r win-x64 --self-contained true \
  -p:PublishSingleFile=true -o "$artifacts/publish"

( cd "$artifacts/publish" && sha256sum MinecraftCleanerPro.exe | tee MinecraftCleanerPro.exe.sha256 )
echo "Done. Executable: $artifacts/publish/MinecraftCleanerPro.exe"
