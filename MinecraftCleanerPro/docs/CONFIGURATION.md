# Configuration reference

File: `%LocalAppData%\MinecraftCleanerPro\config.json` (created with safe defaults on first launch).
Format: JSON (comments and trailing commas are tolerated). Schema version: **1**.

## How the file is handled

- **Open Configuration File** opens the real file in your default editor (Notepad if `.json` has no association).
- After editing it by hand, choose **Reload** (Configuration page). **Validate** checks both the form and the file.
- **Save** validates first, backs up the current file to `config-backups\` (last 20 kept) and writes atomically.
- **Restore Defaults** backs up and resets. **Export** writes the effective configuration elsewhere.
- **View Effective Configuration** shows what is actually in use.
- If the file is not valid JSON, has a wrong value type, has a newer schema version, or fails validation,
  the application **uses safe defaults, shows a warning and does not overwrite your file**, so you can fix it.
- **Migrations**: when a future schema version is introduced, older files are backed up
  (`config-…-pre-migration.json`) and upgraded step by step. Schema 1 is the first release, so no
  production migrations exist yet; the mechanism is covered by tests.
- Unknown settings produce a **warning**, except in the security-critical sections `safety`,
  `quarantine`, `privacy` and `ruleUpdates`, where they are **errors** (so a typo cannot silently weaken a protection).

## Mandatory protections

These cannot be disabled; setting them to `false` is a validation error:
`safety.confirmPermanentDeletion`, `safety.enforcePathValidation`, `quarantine.verifyIntegrity`.

## Settings

### `scan`
| Setting | Default | Range / values | Meaning |
|---|---|---|---|
| `includeDiscoveredInstallations` | `true` | bool | Scan installations found by discovery. |
| `disabledInstallationIds` | `[]` | ids | Discovered installations you unticked on the Installations page. |
| `customDirectories` | `[]` | absolute paths | Extra folders scanned in Quick and Full scans. Missing folders are warnings; whole drives are warnings. |
| `excludedDirectories` | `[]` | absolute paths | Never scanned. |
| `excludedDirectoryNames` | `["saves","screenshots"]` | plain names | Folder names skipped anywhere. |
| `fileExtensions` | `.jar .zip .litemod .json .toml .cfg .txt .properties .exe .dll .bat .cmd .ref` | `.ext` | Files whose content is inspected; others are only counted. Removing `.jar` is a warning. Documented system locations ignore this filter. |
| `maxFileSizeMegabytes` | `256` | 1–4096 | Larger files are checked by name/location only and listed as skipped. |
| `maxDirectoryDepth` | `24` | 1–256 | |
| `followDirectoryLinks` | `false` | bool | If enabled, links are followed **only** into other approved scan locations. |
| `inspectArchives` | `true` | bool | Read ZIP/JAR metadata and entry names (never extracted to disk). |
| `detectArchivesByContent` | `true` | bool | Also recognise jars by their first four bytes, so renamed or disabled jars (`x.jar.disabled`, `x.dat`) are inspected. Pictures, sounds, world data and office documents are never opened for this. |
| `inspectLaunchSettings` | `true` | bool | Read launcher settings (`launcher_profiles.json`, `instance.cfg`, `minecraftinstance.json`, `profile.json`, `instance.json`, MultiMC-format `*.cfg`) and `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS`, `JDK_JAVA_OPTIONS` for Java agents, and scan the files they load. Read-only. |
| `includeDownloadLocations` | `true` | bool | Full scans also check the top two levels of Downloads and Desktop; only `.jar`, `.zip`, `.exe`, `.dll`, `.rar`, `.7z` files. |
| `searchForUnlistedInstallations` | `true` | bool | Search (in the background, folder names only, 20 s / 60,000 folders at most) the user profile, AppData and the top three levels of local drives for game folders no known launcher lists. |
| `archiveLimits.maxEntries` | `50000` | 100–1,000,000 | |
| `archiveLimits.maxTotalUncompressedMegabytes` | `1024` | 1–16384 | Per archive. |
| `archiveLimits.maxEntryUncompressedMegabytes` | `64` | 1–2048 | |
| `archiveLimits.maxCompressionRatio` | `250` | 10–10000 | Entries above this ratio are treated as possible archive bombs. |
| `archiveLimits.maxNestedArchiveDepth` | `2` | 0–4 | Jar-in-jar depth. |
| `archiveLimits.maxNestedArchiveMegabytes` | `64` | 1–512 | |
| `inspectBytecode` | `true` | bool | Parse class files for documented signatures (never loaded/executed). |
| `maxClassFileKilobytes` | `2048` | 16–65536 | |
| `inspectSystemArtifacts` | `true` | bool | Check documented malware persistence locations (read-only). |
| `inspectStartupEntries` | `true` | bool | Read `HKCU\…\Run` (read-only). |
| `inspectRunningProcesses` | `false` | bool | List processes started from flagged locations (read-only). |

### `detection`
| Setting | Default | Meaning |
|---|---|---|
| `enabledCategories` | all | `HackedClient, GhostClient, CombatAutomation, AimAssistance, AutoClicker, ReachModification, VelocityManipulation, XRayOrEsp, MovementOrTimer, InventoryAutomation, InjectedModule, Malware, MaliciousLauncher, CheatConfiguration, GameplayAutomation, LegitimateSoftware, TestSignature`. Empty list is a warning. |
| `hashVerification` | `true` | Compute SHA-256 (hash rules need it). Quarantine always hashes. |
| `computeSha1` | `true` | Also SHA-1 (used by public advisories). |
| `metadataInspection` | `true` | Read mod metadata. |
| `verifyDigitalSignatures` | `true` | Authenticode for `.exe`/`.dll` (offline). |
| `reportLikelyLegitimate` | `false` | Show likely-legitimate files in Findings. |
| `reuseVerifiedResults` | `true` | Skip files unchanged since a clean result with identical rules and settings. |
| `trustedExclusions` | `[]` | `{ "sha256": "…", "path": "…", "note": "…" }`. Malware rules ignore exclusions. Invalid hashes/paths are errors. |

### `performance`
| Setting | Default | Range | Meaning |
|---|---|---|---|
| `lowResourceMode` | `false` | | One worker, 128 KB hash buffer, 1 ms pause per file, queue of 32. |
| `maxParallelTasks` | `2` | 1–64 | More than 2× logical processors is a warning. |
| `maxQueuedFiles` | `512` | 16–100,000 | Bounded queue between enumeration and inspection. |
| `maxMemoryMegabytes` | `512` | 64–8192 | Shared budget for nested-archive and class-file buffers. |
| `reducedPriority` | `true` | | Below-normal thread priority and Windows background mode (CPU, I/O, memory priority). |
| `hashBufferKilobytes` | `1024` | 64–16384 | |

### `ruleUpdates`
| Setting | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Also requires `privacy.offlineMode = false`. |
| `endpoint` | `null` | HTTPS base URL serving `rules.json` and `rules.json.sig`. `http://` or embedded credentials are errors. No trusted source is configured by default. |
| `timeoutSeconds` | `30` | 5–300 |
| `maxDownloadKilobytes` | `4096` | 16–65536 |
| `additionalTrustedPublicKeys` | `[]` | Base64 ECDSA P-256 SubjectPublicKeyInfo. Each entry produces a warning reminding you to only trust keys you added. |

### `quarantine`
| Setting | Default | Meaning |
|---|---|---|
| `directory` | `null` → `%LocalAppData%\MinecraftCleanerPro\quarantine` | Must be absolute and outside protected system locations. |
| `verifyIntegrity` | `true` | **Mandatory.** |

### `reports`
| Setting | Default | Range |
|---|---|---|
| `directory` | `null` → `…\reports` | absolute |
| `defaultFormat` | `Html` | `Html`, `Txt`, `Json` |
| `redactPersonalPathsByDefault` | `true` | |
| `retentionDays` | `180` | 1–3650 |
| `maxReports` | `200` | 1–10000 |
| `historyRetentionDays` | `365` | 1–3650 |
| `maxHistorySessions` | `200` | 1–10000 |

### `logging`
| Setting | Default | Range |
|---|---|---|
| `level` | `Information` | Trace, Debug, Information, Warning, Error, Critical, None |
| `retentionDays` | `14` | 1–365 |
| `maxFileMegabytes` | `10` | 1–100 |
| `maxTotalMegabytes` | `100` | 1–2048 |

### `privacy`
| Setting | Default | Meaning |
|---|---|---|
| `offlineMode` | `true` | Blocks every network request. |
| `includeUserNameInReports` | `false` | |
| `includeMachineNameInReports` | `false` | |

### `safety`
| Setting | Default | Meaning |
|---|---|---|
| `confirmQuarantine` | `true` | May be turned off (quarantine is reversible); turning it off is a warning. |
| `confirmRestore` | `true` | |
| `confirmPermanentDeletion` | `true` | **Mandatory.** |
| `enforcePathValidation` | `true` | **Mandatory.** |

### `startup`
| Setting | Default | Meaning |
|---|---|---|
| `scanOnLaunch` | `false` | Automatic scanning (manual by default). |
| `scanModeOnLaunch` | `Quick` | `Quick` or `Full`. |
| `checkRuleUpdatesOnLaunch` | `false` | Only when online and configured. |

### `interface`
| Setting | Default | Values |
|---|---|---|
| `theme` | `System` | `System`, `Light`, `Dark` |
| `showScanScopeBeforeScan` | `true` | Confirmation dialog listing the scope. |
| `confirmExitDuringScan` | `true` | |
| `hidePrivateInformation` | `true` | Cover the Windows user name, user-profile folder name and computer name with black bars in the interface (click to reveal). Text viewers mask them until "Show private information" is pressed. Editable text boxes on the Configuration page show paths in full. |

### `accessibility`
| Setting | Default | Range / meaning |
|---|---|---|
| `fontScale` | `1.0` | 0.8–2.0 (all text) |
| `highContrast` | `false` | Force the high-contrast palette (it is also used automatically when Windows high contrast is on). |
| `reduceMotion` | `true` | The application uses no animations; kept for future use. |
| `showTooltips` | `true` | |
