# Minecraft Cleaner Pro Ultimate

A Windows 10/11 desktop application that inspects Minecraft installations for known cheat clients,
their leftovers and documented Minecraft malware, explains every finding with traceable evidence,
lets you quarantine files safely (reversibly) and verifies the result afterwards.

It is built to be **transparent and conservative**: it never executes scanned files, never touches
process memory, never modifies the registry or system folders, keeps everything on your computer and
works fully offline. It does not claim to find every cheat — see [Known limitations](#known-limitations).

| | |
|---|---|
| Platform | Windows 10 and 11, x64 |
| Technology | C# / .NET 10 (LTS) / WPF |
| Distribution | One self-contained `MinecraftCleanerPro.exe` (no .NET install needed) |
| Network | None by default (offline mode on) |
| Privileges | Runs as a normal user (`asInvoker`); never asks for administrator rights |
| Code signing | **Not signed** — verify the SHA-256 in the release notes |

## What it does

1. **Discovers installations** from launcher metadata: the official launcher (including custom
   profile game directories in `launcher_profiles.json`), Prism Launcher / PolyMC / MultiMC
   instances, Modrinth App, CurseForge, ATLauncher, GDLauncher, and the data folders of Lunar,
   Feather and Badlion. Loaders (Fabric, Quilt, Forge, NeoForge) are identified from metadata.
   Unparseable metadata is reported, never guessed. You can add any other folder.
2. **Shows the exact scope** (every folder, why it is included, how deep) before a Quick, Full or
   Custom scan starts.
3. **Scans read-only** with a bounded, cancellable, pausable pipeline at reduced priority:
   enumeration without following links → type/size checks → metadata → SHA-256/SHA-1 →
   static ZIP/JAR inspection (bomb-safe, nested jars) → static Java bytecode inspection →
   rule matching → evidence-based classification.
4. **Explains each finding**: classification (Known match / High-confidence suspicion / Needs review /
   Likely legitimate / Unverified), separate confidence, severity, reputation and recommended
   action, every evidence item, the rule id and version, its public sources and verification date,
   false-positive notes and limitations.
5. **Quarantines** approved files: re-validates the path, checks the file is unchanged, copies it
   into an encoded payload, verifies the copy by SHA-256 and only then removes the original —
   journaled so a crash or power loss never loses data. Restore never overwrites another file.
   Permanent deletion is only possible from quarantine, after confirming the exact list.
6. **Verifies** cleanup by rescanning the affected folders and comparing by path and hash.
7. **Reports** in HTML, TXT and JSON, with personal-path redaction, and keeps a searchable history.

## What it detects (rule database 2026.10.11.1)

Indicators were verified on 2026-10-11 against the projects' official repositories and published
investigations; every rule cites its sources. Details: [docs/DETECTION.md](docs/DETECTION.md).

- Hacked clients: **Wurst**, **Meteor Client**, **LiquidBounce**, **BleachHack**, **ThunderHack**
  (mod id + class package + mixin config; two independent indicators required for a known match).
- **fractureiser** malware: stage 0 bytecode signatures (from nekodetector), published stage 2
  SHA-1 hashes, stage 2/3/3b persistence files and folders, stage 3 `dev.neko.nekoclient` classes,
  startup persistence.
- Leftover configuration of Wurst, Meteor Client and LiquidBounce.
- Generic heuristics (review only): combat/movement/render cheat-module class layouts, known client
  names in file names, x-ray resource packs.
- **Baritone** (automation; reported for review only — allowed on some servers).
- Legitimacy safeguards for Sodium, Iris, Lithium, Mod Menu, Fabric Loader and Fabric API.
- A harmless test signature for the built-in **detection self-test**.

## Quick start

1. Download `MinecraftCleanerPro.exe` and check its SHA-256 against [docs/RELEASE-NOTES.md](docs/RELEASE-NOTES.md)
   or the `.sha256` file that accompanies the build.
2. Run it. On first launch it creates `%LocalAppData%\MinecraftCleanerPro\config.json`.
3. Close Minecraft and all launchers.
4. **Scanner** → choose *Quick Scan* → review the scope → **Start scan**.
5. **Findings** → read the evidence → tick items → **Quarantine selected** → **Verify cleanup**.

See the [user guide](docs/USER-GUIDE.md).

## Building

```powershell
# Windows: build, run all tests, publish the single-file exe and self-test it
pwsh scripts/build.ps1 -SmokeUi
```
```bash
# Linux/macOS: cross-compile and test (Windows-only tests are skipped)
./scripts/build.sh
```
Requires the .NET 10 SDK. Output: `artifacts/publish/MinecraftCleanerPro.exe`. Details, including the
self-contained decision and reproducibility: [docs/BUILD.md](docs/BUILD.md).

## Project structure

```
MinecraftCleanerPro/
├── src/
│   ├── CleanerPro.App/             WPF application (MVVM, DI composition root, self-test mode)
│   ├── CleanerPro.Core/            Domain models, path normalisation, PathSafetyPolicy
│   ├── CleanerPro.Infrastructure/  App paths, atomic writes, hashing, JSON logging, Windows helpers
│   ├── CleanerPro.Configuration/   Typed config, validation, migration, backups
│   ├── CleanerPro.Privacy/         Network gate, guarded HTTP client, network activity log
│   ├── CleanerPro.Detection/       Rule database, signatures/updates, bytecode reader, matcher, classifier
│   ├── CleanerPro.Scanner/         Discovery, safe enumeration, archive inspection, scan pipeline
│   ├── CleanerPro.Quarantine/      Journaled quarantine, restore, confirmed deletion, recovery
│   └── CleanerPro.Reporting/       History, verification, reports, dashboard statistics
├── tests/                          xUnit: Core, Detection, Scanner, Quarantine, Integration
├── tools/CleanerPro.RuleTool/      Maintainer tool: keygen / validate / sign / verify rule databases
├── rules/cleanerpro-rules.json     Bundled rule database (embedded in the executable)
├── scripts/                        build.ps1, build.sh, check-xaml-resources.py
└── docs/                           Architecture, configuration, detection, privacy, build, tests, release notes
```

## Documentation

- [User guide](docs/USER-GUIDE.md)
- [Architecture and safety design](docs/ARCHITECTURE.md)
- [Configuration reference](docs/CONFIGURATION.md)
- [Detection rules and database format](docs/DETECTION.md)
- [Privacy and network policy](docs/PRIVACY.md)
- [Build and release](docs/BUILD.md) · [Dependencies](docs/DEPENDENCIES.md)
- [Test results](docs/TEST-RESULTS.md) · [Release notes](docs/RELEASE-NOTES.md)

## Known limitations

- A file scan **cannot prove that a player cheated**. Files may be unused leftovers; cheats that run
  only in memory, are injected at runtime, or were deleted before the scan leave nothing to find.
- Only the families in the rule database are recognised. "No findings" does not mean "safe".
  Renamed, repackaged or obfuscated cheats can avoid specific rules; heuristics only flag them for review.
- No bundled rules exist yet for closed-source "ghost" clients (for example Vape) or standalone
  auto-clickers, because no indicator could be verified from a primary source for this release.
- There is no official online rule-update service; updates only work with a source and signing key you configure.
- Registry startup entries and scheduled tasks are reported, never modified.
- Authenticode checks are offline (no revocation check); jar signatures are not verified.
- Quarantine encoding (XOR) prevents accidental execution; it is not encryption.
- The executable is **not code-signed**.
- The graphical interface was compiled and statically checked in a Linux container, and the
  executable's headless self-test passed under Wine; the GUI itself is verified on Windows by the
  CI workflow. See [docs/TEST-RESULTS.md](docs/TEST-RESULTS.md) for exactly what ran where.
- This is not a replacement for antivirus software. If malware is found, change your passwords from a
  clean device and run a full antivirus scan.
