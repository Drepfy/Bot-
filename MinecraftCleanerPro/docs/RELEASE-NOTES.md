# Release notes

## 1.1.0 — 2026-10-11

### Detection (rule database 2026.10.11.2, 63 rules)
- New clients, each verified from its own source repository: Aoba, Argon (a ghost client that disguises itself as
  the ImmediatelyFast mod), Jex, AnarchyClient, Ares, KAMI Blue, Lambda (legacy and Fabric), SalHack, ForgeHax,
  3arthh4ck, Seppuku, GameSense, FDPClient and MinusBounce; LiquidBounce legacy (Forge) through its core-mod
  manifest.
- Every Meteor Client add-on (by its `"meteor"` entrypoint), nine named add-ons, and every RusherHack plugin.
- Impersonation check: a jar that claims to be Sodium, Iris, Lithium, Mod Menu or ImmediatelyFast without their
  real code is flagged.
- Java agents: `-javaagent`, `-agentpath`, `-agentlib` and `-Xbootclasspath` in launcher settings and in
  `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS`, `JDK_JAVA_OPTIONS` are reported, and the files they load are scanned.
- Advanced XRay is reported for review; the client-name heuristic now includes closed-source clients.
- Rule engine: `none` conditions and `ModEntrypoint` indicators; the database is generated from
  `rules/build_rules.py`.

### Fewer weak spots
- Jars are recognised by their content, so renamed or disabled jars are inspected.
- Full scans check the top two levels of Downloads and Desktop (programs and archives only).
- Findings that cannot be moved safely (registry, environment variables, launcher settings) explain how to remove
  them yourself.

### Launchers
- Any MultiMC-format launcher (PollyMC, Fjord, UltimMC…), Technic Launcher, Microsoft Store redirected folders, and a
  background folder search for game folders no launcher lists (portable launchers, copies, other drives).

### Deleting
- Findings: **Delete permanently…**. Quarantine: **Tick all**, **Delete all permanently…**. Privacy & Updates:
  **Delete all application data…**. Every permanent deletion needs the exact list, an acknowledgement and `DELETE`.

### Privacy and coexistence
- Your user name and computer name are covered by black bars in the interface; click a bar to reveal it.
- Other programs' files are read with full sharing, so launchers and the game are never blocked; a running game or
  launcher is detected (by process name, read-only) and you are warned before cleanup.

### Not changed
- The executable is still unsigned, and no file scanner can guarantee finding every cheat (see Known limitations).

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
- Only the listed families are detected; closed-source clients are matched by name only, and stand-alone
  auto-clickers or clients injected into the running game may leave no file. "No findings" does not mean "safe".
- No official online update service; updates require your own HTTPS source and signing key.
- Registry startup entries and scheduled tasks are reported, never modified.
- Authenticode checks are offline (no revocation); jar signatures are not verified.
- Quarantine encoding is not encryption.
- The executable is not code-signed.
- See [TEST-RESULTS.md](TEST-RESULTS.md) for exactly which verifications ran on Windows, under Wine and on Linux.
