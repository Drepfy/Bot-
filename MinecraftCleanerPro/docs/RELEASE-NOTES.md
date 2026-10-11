# Release notes

## 1.0.0 — 2026-10-11

First release of Minecraft Cleaner Pro Ultimate.

### Deliverable

| File | Details |
|---|---|
| `MinecraftCleanerPro.exe` | Windows 10/11 x64, self-contained single file (includes .NET 10 + WPF), ~62 MB, **unsigned** |
| SHA-256 | Recorded in the `.sha256` file produced next to every build (`scripts/build.ps1` / `build.sh`, and the CI artifact). Always verify the hash of the exact file you received. |

Build it yourself with `pwsh scripts/build.ps1` (see [BUILD.md](BUILD.md)) or download the
`MinecraftCleanerPro-win-x64` artifact from the GitHub Actions run of the commit you trust.

### Features

- Installation discovery for the official launcher (including custom profile directories), Prism Launcher,
  PolyMC, MultiMC, Modrinth App, CurseForge, ATLauncher, GDLauncher, Lunar, Feather, Badlion and custom folders,
  with loader detection (Fabric, Quilt, Forge, NeoForge).
- Quick, Full and Custom scans with an explicit scope preview, pause/resume/cancel, real progress counters,
  bounded concurrency and reduced priority.
- Static inspection: hashes, mod metadata, archive structure (bomb-safe, jar-in-jar), Java bytecode signatures.
- Evidence-based classification with separate confidence, severity, reputation and recommended action; every
  finding cites its rules, indicators, sources and verification dates.
- Bundled rule database 2026.10.11.1 (29 rules): Wurst, Meteor Client, LiquidBounce, BleachHack, ThunderHack,
  fractureiser (stages 0–3b), client leftovers, generic module heuristics, Baritone (review only), legitimacy
  safeguards and a harmless self-test signature.
- Journaled, integrity-verified quarantine; restore without overwriting; permanent deletion only with an exact,
  typed confirmation; automatic recovery of interrupted operations.
- Post-cleanup verification by path and hash.
- HTML/TXT/JSON reports with personal-path redaction; searchable history and audit log.
- Full configuration system with validation, backups, migration support, export and "open in editor".
- Offline by default; optional signed (ECDSA P-256) rule updates with expiry and anti-rollback.
- Light, dark and high-contrast themes, text scaling, access keys, screen-reader names.
- `--self-test` and `--smoke-ui` modes for verifying a published executable.

### Known limitations

- File scanning cannot prove cheating; memory-only, injected or deleted cheats are not detectable this way.
- Only the listed families are detected; no rules for closed-source ghost clients or stand-alone auto-clickers
  (no verifiable indicators were available). "No findings" does not mean "safe".
- No official online update service; updates require your own HTTPS source and signing key.
- Registry startup entries and scheduled tasks are reported, never modified.
- Authenticode checks are offline (no revocation); jar signatures are not verified.
- Quarantine encoding is not encryption.
- The executable is not code-signed.
- See [TEST-RESULTS.md](TEST-RESULTS.md) for exactly which verifications ran on Windows, under Wine and on Linux.
