# Test results

This file records which verifications actually ran, where, and with what result. Nothing here is projected or
assumed; anything that was **not** verified is listed under *Not verified* for each version.

## Version 1.1.0

Same environments as 1.0.0 (below). Runs on 2026-10-11.

### Automated test suite — 293 tests

| Project | Tests | Linux | Windows CI run 7 |
|---|---|---|---|
| CleanerPro.Core.Tests | 76 | 75 passed, 1 skipped (`[WindowsFact]`) | 76 passed |
| CleanerPro.Detection.Tests | 114 | 114 passed | 114 passed |
| CleanerPro.Scanner.Tests | 70 | 70 passed | 70 passed |
| CleanerPro.Quarantine.Tests | 22 | 22 passed | 22 passed |
| CleanerPro.Integration.Tests | 11 | 11 passed | 11 passed |
| **Total** | **293** | **292 passed, 1 skipped, 0 failed** | **293 passed, 0 failed** (symbolic links allowed) |

New in this version (89 tests), all with synthetic fixtures:
- **Rules**: every new client and add-on is a known match with its mod id and package; Forge core-mod
  manifests work as a second indicator; Argon's ImmediatelyFast disguise; any Meteor add-on by entrypoint;
  RusherHack plugins; impersonation of Sodium, Iris, Lithium, Mod Menu and ImmediatelyFast is flagged while
  real builds in every official package (including old ones) are not; impersonation is not concluded for jars
  that were not fully read; the client-name heuristic matches distinctive names and ignores ordinary words
  (`future.jar`, `sunrise-shaders.zip`, `impactor.jar`); `none` conditions and their validation; every new rule
  cites a GitHub source verified on 2026-10-11.
- **Weak spots**: renamed or disabled jars (`.jar.disabled`, `.dat`, no extension) are detected by content, and
  not when the setting is off; picture files are not opened; a `-javaagent` in `launcher_profiles.json`, in a
  Prism `instance.cfg` and in `JAVA_TOOL_OPTIONS` is reported for manual removal, the agent jar it loads is
  scanned, and that jar's folder (not the whole scan) is approved for cleanup; Downloads is checked on Full scans only, two levels deep, programs and archives
  only; agent-option parsing (quoted paths, options, INI escaping, `-agentlib`, boot class path).
- **Launchers**: ATLauncher, GDLauncher (both layouts), Feather, Badlion, PolyMC, MultiMC-format forks by
  layout, Technic, Microsoft Store redirected folders, shared launch-settings files, and the folder search
  (finds portable and copied game folders, ignores folders without game data, skips known installations,
  system and excluded folders, stops at its limits).
- **Deleting**: permanent removal from Findings deletes exactly the verified file and logs both steps, keeps a
  file that changed since the scan, and honours path protection; "Delete all application data" removes history,
  reports, quarantine, audit log, logs, backups and other stores, resets the configuration, and leaves Minecraft
  files untouched.
- **Privacy**: user and computer names are found as whole words only, longest first; masking.
- **Coexistence**: while this application reads a file, another program can still write and delete it; hashing
  shares the file with writers; running games and launchers are recognised by process name. Linux does not
  enforce Windows file-sharing modes, so the sharing tests are only meaningful in the Windows CI run.

### Windows CI runs

| Run | Commit | Result |
|---|---|---|
| [6](https://github.com/Drepfy/Bot-/actions/runs/38168431164) | `69bb54c` (new rules, weak spots, launchers, deleting) | **Passed**: 280/280 tests, symbolic links allowed, self-test 9/9, smoke UI OK (all 9 pages). |
| [7](https://github.com/Drepfy/Bot-/actions/runs/38169202194) | `ee22fd4` (black bars, coexistence, docs) | **Passed**: 293/293 tests, symbolic links allowed, self-test 9/9 on Windows NT 10.0.26100 with rule database 2026.10.11.2, smoke UI OK (all 9 pages rendered with the new black-bar controls). Executable SHA-256 `b3dce77182783e11a763c084439a59029774864dbf6c99cfa2493ec854896f74`. |

These hashes belong to development builds. The executable's bytes include the commit id, so every commit
produces a different file; to check a download, compare it with the SHA-256 on its release page.

### Published executable (Linux build, run under Wine 9.0)

| Check | Result |
|---|---|
| `--self-test` (9 steps) | **9/9 passed**: version 1.1.0, rule database 2026.10.11.2 with 63 rules (SHA-256 `b55bca7ab15082d742706d7c89478924f6630abbaebb0f35827bfba4640f2dec`) |
| Problem found and fixed | The first Wine run passed `--data-root` with forward slashes (`Z:/tmp/...`); the self-test compared that raw path with the scanner's normalised paths and reported 3 failed steps. The self-test now normalises its folder; the re-run with the same arguments passed 9/9. |

### Not verified for 1.1.0

- The new interface elements (black bars, delete buttons, folder search button, manual-removal box) are only
  covered by the UI smoke test, which opens each page; nobody has clicked through them on Windows.
- The folder search and the Java-environment reading were tested with synthetic folders and injected values,
  not on a real computer with real launchers.
- As before: no real cheat clients or malware were scanned, and real-world detection and false-positive rates
  are unknown.

## Version 1.0.0

### Environments

| Environment | Details | Used for |
|---|---|---|
| Linux (development container) | Ubuntu 24.04.5, .NET SDK 10.0.112 | build, all platform-independent tests, publishing, reproducibility check, vulnerability audit |
| Wine 9.0 on the same Linux machine (headless, Xvfb) | reports itself as Windows NT 10.0.19043, .NET 10.0.12 runtime from the self-contained exe | `--self-test` of the published executable |
| GitHub Actions `windows-latest` | Windows NT 10.0.26100, SDK from `global.json` | build, **all** tests incl. Windows-only ones, publish, `--self-test`, `--smoke-ui` (real WPF rendering) |

### Automated test suite

204 tests in five projects. Runs on 2026-10-11:

| Project | Tests | Linux | Windows CI (runs 2, 3, 4) |
|---|---|---|---|
| CleanerPro.Core.Tests | 63 | 62 passed, 1 skipped | 63 passed |
| CleanerPro.Detection.Tests | 67 | 67 passed | 67 passed |
| CleanerPro.Scanner.Tests | 45 | 45 passed | 45 passed |
| CleanerPro.Quarantine.Tests | 19 | 19 passed | 19 passed |
| CleanerPro.Integration.Tests | 10 | 10 passed | 10 passed |
| **Total** | **204** | **203 passed, 1 skipped, 0 failed** | **204 passed, 0 failed** |

- The test skipped on Linux is `WindowsSystemFolderIsProtectedOnRealSystem` (`[WindowsFact]`); it needs a real
  Windows system folder and passed on Windows.
- Six tests that need symbolic links (`PathSafetyPolicyTests`, `EnumerationAndDiscoveryTests`,
  `QuarantineServiceTests`) **return early and count as passed** when the account is not allowed to create
  links (Windows without Developer Mode or administrator rights). On Linux they executed fully. In Windows
  CI runs 3 and 4 the "Report symbolic link permission" step logged `Symbolic links: allowed`, so they
  executed fully on Windows too (run 2 predates that step).
- No test uses real malware or a real cheat client. Detection tests use synthetic jars and synthetic class
  files that reproduce only the documented byte patterns (`tests/Shared/TestHelpers.cs`).

Coverage by area: path safety (protected roots, device/UNC/ADS/trailing-dot/8.3/reserved names, relative
segments, symbolic links); configuration (defaults, validation, unknown keys, wrong types, migration, backup,
invalid JSON, newer versions, export, reload); rule database loading and validation; indicator matching,
conditions and classification including conflicting and legitimacy evidence; class-file parsing and the
three fractureiser bytecode signatures; signed rule updates (valid, tampered, expired, rollback, untrusted
or missing key, size limit, offline) through an in-memory HTTP handler; archive inspection (nested jars,
compression-ratio, entry-count, size and nesting limits, corrupt archives, metadata parsing); safe
enumeration; discovery for the official launcher, Prism, Modrinth, CurseForge, Lunar Client and custom folders; the scan
engine (cancellation, pause, cache, memory budget, size limits, overlapping roots, files never modified);
quarantine (integrity, interrupted operations, simulated disk-full, files changed since the scan, restore
without overwrite, deletion confirmations); reports and redaction; history; logging; end-to-end flows.

### Published executable

### Self-test (`--self-test`)

The nine steps in `src/CleanerPro.App/Composition/SelfTest.cs` run against harmless fixtures in a temporary
data root: configuration created and valid; bundled rules loaded; fixtures created; scan detects the fixtures
with evidence; quarantine with integrity verification; restore returns identical content; protected system
paths cannot be targeted (`C:\Windows\System32\drivers\etc\hosts`); HTML/TXT/JSON reports; offline by
default with no network activity.

| Where | Executable | Result |
|---|---|---|
| Wine 9.0 | folder publish | 9/9 passed |
| Wine 9.0 | compressed self-contained single file | 9/9 passed |
| Windows CI runs 2, 3, 4 | compressed self-contained single file | 9/9 passed |

### UI smoke test (`--smoke-ui`)

Opens the main window and navigates to every page (Dashboard, Installations, Scanner, Findings, Quarantine,
History, Configuration, Privacy & Updates, About), failing on any unhandled exception (for example a missing
resource or invalid XAML). WPF data-binding errors are not exceptions and are not detected by this test.

| Where | Result |
|---|---|
| Windows CI runs 2, 3, 4 | all 9 pages rendered, log ends with `SMOKE-UI: OK` |
| Wine 9.0 | **not possible**: WPF terminates inside its font-fallback code under this Wine build, also for a minimal one-window WPF program with no application code, so this is an environment limitation, not an application error |

### Windows CI runs

| Run | Commit | Result |
|---|---|---|
| [1](https://github.com/Drepfy/Bot-/actions/runs/38164308767) | `d4c8c07` | **Failed**: `UnchangedCleanFilesAreReusedOnTheNextScan`. The scan cache stored its path keys through a camelCase dictionary-key policy, so `C:\USERS\…` was saved as `c:\USERS\…` and never matched again. Linux paths start with `/`, which is why it only appeared on Windows. |
| [2](https://github.com/Drepfy/Bot-/actions/runs/38164580037) | `9e89812` | **Passed**: fix plus regression test `CacheKeysRoundTripExactly` (confirmed failing before and passing after the fix). 204/204 tests, self-test 9/9, smoke UI OK. Executable SHA-256 `9bee2cc55e3d7b9284224d271064a748905608acda0b2b408efe2019124905bb`. |
| [3](https://github.com/Drepfy/Bot-/actions/runs/38165127174) | `b9268f7` | **Passed**: 204/204 tests, symbolic links allowed, self-test 9/9, smoke UI OK. |
| [4](https://github.com/Drepfy/Bot-/actions/runs/38165168546) | `549113b` | **Passed**: 204/204 tests, symbolic links allowed, self-test 9/9, smoke UI OK. Executable SHA-256 `d7df637ddb97227726b3fc01e8e9e4207e4df6d1a925e9eaabb0400a2e69804b`. The self-test reported rule-database SHA-256 `64b09c45325ed7d10a0113402d94513ff2e6e2c71e17cbdade6187678f0e3981`, identical to Linux. |

Every later commit gets its own run; the run's artifact contains the executable, its `.sha256`,
`selftest.json`, `smoke-ui.log` and the test result files. The executable's bytes include the commit
id, so the hash changes with every commit — always compare against the `.sha256` from the same run.

### Other checks

- **XAML resource check** (`scripts/check-xaml-resources.py`): 17 XAML files, 75 resource keys, all three
  themes define the same keys — passed.
- **Warnings**: the solution builds with `TreatWarningsAsErrors`; 0 warnings, 0 errors.
- **Vulnerability audit**: `dotnet list package --vulnerable --include-transitive` reported "no vulnerable
  packages given the current sources" for all 15 projects (2026-10-11, nuget.org advisory data).
- **Reproducibility**: two consecutive publishes of the same source on the Linux machine produced
  byte-identical single-file executables.
- **Rule tool**: `keygen`, `sign`, `verify` and `validate` were run on the bundled database; a modified copy
  of the signed file was rejected by `verify`.
- **Line endings**: `.gitattributes` pins LF, so the embedded rule database has the same bytes and SHA-256 on
  every platform. Before this, a Windows checkout produced CRLF and a different hash; since run 3 the
  Windows self-test reports the same hash as Linux.

### Not verified

- **No manual, interactive use of the GUI** by a person (clicking through dialogs, screen readers, high-DPI
  monitors, keyboard-only use). The smoke test proves that each page loads and renders, not that every
  workflow is pleasant.
- **No real Minecraft installations or launchers** were scanned. Discovery was tested against synthetic
  folder layouts for the official launcher, Prism, Modrinth, CurseForge, Lunar Client and custom folders;
  the MultiMC, PolyMC, ATLauncher, GDLauncher, Feather and Badlion layouts have no dedicated test.
- **No real cheat clients or malware samples** were scanned (by design). Rules were exercised only against
  synthetic fixtures built from the public indicators cited in [DETECTION.md](DETECTION.md) (all rules are
  loaded and validated; matching tests use representative families). Real-world false-positive and
  false-negative rates are unknown.
- **No performance benchmarks** on large real-world modpacks; bounded-concurrency and memory-budget
  behaviour is covered by unit tests only.
- **Windows 10 and desktop Windows 11** were not tested directly; CI uses GitHub's `windows-latest`
  runner image (NT build 26100).
- **Signed rule updates over the network** were tested with a local fake HTTP handler, not against a real
  server; there is no official update server.
- **Code signing**: the executable is unsigned.
