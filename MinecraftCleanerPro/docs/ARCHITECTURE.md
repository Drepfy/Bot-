# Architecture and safety design

## Modules

```
CleanerPro.App ──► Reporting ──► Quarantine ──► Configuration ──► Infrastructure ──► Core
        │              │                                               ▲
        ├──► Scanner ──┴──► Detection ──► Privacy ─────────────────────┘
        └──► (DI composition root, MVVM view models, WPF views, self-test)
```

| Project | Responsibility | Notes |
|---|---|---|
| `CleanerPro.Core` | Domain models (Finding, Evidence, ScanSession…), `PathKey`, **`PathSafetyPolicy`** | No dependencies |
| `CleanerPro.Infrastructure` | `AppPaths`, atomic writes, streaming hashes, JSON-lines logger with retention, operations audit log, Windows helpers (Authenticode, background priority, read-only startup inspection, shell launcher) | P/Invoke guarded by `OperatingSystem.IsWindows()` |
| `CleanerPro.Configuration` | Typed model, validator, migrator, service (load/save/backup/export/restore) | |
| `CleanerPro.Privacy` | `NetworkAccessPolicy`, `GuardedHttpClient`, `NetworkActivityLog`, privacy statement | The only code that can use the network |
| `CleanerPro.Detection` | Rule model, loader/validator, compiled indexes, `RuleMatcher`, `FindingClassifier`, Java class-file reader and bytecode signature matcher, signed updates with anti-rollback | Separates *matching* from *classification* |
| `CleanerPro.Scanner` | Launcher discovery, scope builder, safe enumerator, archive and mod-metadata inspection, documented system locations, scan pipeline, result cache | Read-only |
| `CleanerPro.Quarantine` | Journaled quarantine, restore, confirmed deletion, integrity checks, crash recovery | All writes pass `PathSafetyPolicy` |
| `CleanerPro.Reporting` | History store, post-cleanup verification, report builder/exporters (HTML/TXT/JSON), redaction, dashboard statistics | |
| `CleanerPro.App` | WPF views and view models, theming, dialogs, composition root, `--self-test`, `--smoke-ui` | |

Detection is deliberately split into three steps: the **scanner** produces an `ItemObservation`
(what was seen), the **matcher** evaluates rules into `RuleEvaluation`s (which indicators matched and which
classification level each rule reaches), and the **classifier** turns those into a single `Finding`
(classification, confidence, severity, reputation, action, rationale, limitations). Cleanup is a separate
module that only acts on user-approved findings.

## Scan pipeline

1. **Discover** permitted locations (installations, user folders, documented system locations).
2. **Enumerate** with a manual walk: no link/junction is followed (unless explicitly enabled, and then only
   into other approved roots), exclusions and depth limits apply, every unreadable folder is recorded.
   Overlapping roots are de-duplicated by normalised path.
3. **Type and size checks**: only configured extensions (plus documented system locations) are opened;
   larger files are checked by name and location only.
4. **Metadata**: size and timestamps; the file is checked again after reading and skipped if it changed.
5. **Hashing**: SHA-256 (+ SHA-1) in one streaming pass with a configurable buffer.
6. **Archive inspection** (`System.IO.Compression`, nothing written to disk): entry names, class packages,
   mod metadata (`fabric.mod.json`, `quilt.mod.json`, `mods.toml`, `neoforge.mods.toml`, `mcmod.info`),
   manifest, jar-in-jar up to a depth limit. Entry count, per-entry size, total size, compression ratio and
   declared-vs-actual size are bounded to defeat archive bombs.
7. **Bytecode inspection**: a bounds-checked class-file parser decodes method instructions with symbolic
   operands; signatures are pre-filtered by required constant-pool strings or raw byte sequences.
8. **Rule matching** through index lookups (hash, mod id, package, entry, name, path, location, signature).
9. **Classification** with false-positive safeguards and trusted exclusions.
10. Unique findings are recorded; clean, fully inspected files are cached (path + size + timestamp + rule hash
    + settings fingerprint) so unchanged files can be skipped next time.

Concurrency: one producer thread and N worker threads (configurable, 1 in low-resource mode) connected by a
**bounded** `BlockingCollection`; workers run at below-normal priority with Windows *background mode*
(lower CPU, I/O and memory priority). A shared `MemoryBudget` bounds in-memory archive buffers. Pause blocks
producer and workers on a `ManualResetEventSlim`; cancellation is cooperative everywhere and produces a
*Cancelled* session with the partial results. Progress reports real counters; a percentage is shown only
once enumeration has finished (no invented progress).

## Path safety policy

Every filesystem modification (quarantine, directory cleanup, restore) goes through `PathSafetyPolicy`,
which cannot be turned off by configuration:

- Rejects empty, relative, wildcard, device (`\\?\`, `\\.\`), UNC, alternate-data-stream, trailing dot/space,
  reserved device name (`CON`, `NUL`…) and 8.3 short-name alias paths, and any path that changes when
  normalised (`..` tricks).
- **Protected locations always win** over approved roots: Windows, System, Program Files (both),
  Common Files, `ProgramData\Microsoft`, Recovery, `$Recycle.Bin`, System Volume Information, Boot, EFI, the
  application's own data/quarantine/report folders. Exact protected paths: drive roots, the user profile,
  `AppData`, `Local`, `Roaming`, `LocalLow`, Desktop, Documents, Downloads, Start Menu, Startup, the running
  executable.
- The target must lie inside the scan's approved roots, must not be a root itself (no "delete the whole
  installation"), must exist with the expected type, must not be a driver/OS file type, and neither the
  target nor any ancestor below the approved root may be a link or junction. Checks are repeated right
  before the original is removed.

## Quarantine design

Layout: `quarantine\entries\<id>\manifest.json` + `payload.bin`, and `quarantine\journal\<id>.json`.

1. Validate the path; check size and SHA-256 against the scan.
2. Journal `Started`; copy the original into `payload.bin.tmp`, XOR-encoded with a random per-entry key,
   hashing exactly what was read (the copy is rejected if the file changed).
3. Rename, then **independently re-read and verify** the payload's decoded SHA-256.
4. Write the manifest (original path, size, hashes, timestamps, attributes, approved roots, finding and
   rule ids); journal `PayloadVerified`.
5. Re-validate and confirm the file is unchanged, then delete the original (clearing read-only if needed).
   If deletion fails (file in use), everything is rolled back and the original is untouched.
6. Journal `OriginalDeleted`, mark the manifest *Quarantined*, remove the journal, append to the audit log.

On startup `RecoverInterruptedOperations` reads the journal: if the original still exists the partial entry
is rolled back; if it is gone and the payload verifies, the quarantine is completed; otherwise the data is
kept and a warning is shown. A disk-full error at any point leaves the original in place.

Restore verifies the payload, validates the destination inside the original approved roots, **never
overwrites** (a conflict is reported and the user chooses *new name* or *another folder*), writes to a
temporary file, verifies its hash, renames, and restores timestamps/attributes. Permanent deletion requires a
plan listing the exact items, a short-lived HMAC token bound to that exact set, a typed `DELETE` and an
acknowledgement in the UI.

## Post-cleanup verification

The verification scan re-reads the folders that contained findings (plus documented system locations) and
compares with the original session using normalised paths and SHA-256, together with the operations audit
log. Outcomes per finding: Quarantined, Deleted, No longer present, Still present, Present elsewhere (same
hash at another path), Not accessible, Operation failed, Inconclusive — plus new related detections. A missing
file is explicitly *not* treated as proof that every component was removed.

## Data integrity

All persisted JSON is written atomically (temp file + flush + rename). The operations log is append-only JSON
lines that tolerates a torn final line. History ids are validated before use as file names.
