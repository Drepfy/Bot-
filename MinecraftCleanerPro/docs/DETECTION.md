# Detection rules

The detection database is data, not code. It lives in `rules/cleanerpro-rules.json`, is embedded in the
executable at build time, and can be replaced by a newer **signed** database (see [Updates](#signed-updates)).
Nothing in the database is ever executed.

## Principles

- **Evidence over names.** File names are weak evidence and alone can only produce *Needs review* with a
  severity capped at *Low*.
- **Two independent indicators** (for example a mod id *and* a class package) are required for a
  *Known match* on cheat clients.
- **Sourced and dated.** Every non-heuristic rule cites the public source each indicator was checked against,
  and the date it was verified. The loader rejects such rules without sources.
- **Heuristics can never produce a Known match**, and legitimacy evidence (a known legitimate mod's identity,
  or a valid Authenticode signature) overrides heuristic *Needs review* results — never specific rules.
- **No invented indicators.** No hashes, signatures or citations were made up. Families for which nothing
  could be verified from a primary source (for example closed-source ghost clients such as Vape, or
  stand-alone auto-clickers) have **no rules** in this release; that is a documented limitation.

## Classification

| Classification | Meaning | Recommended action |
|---|---|---|
| **Known match** | A validated indicator set matched a documented rule. The indicator and its source are shown. | The rule's action (usually Quarantine) |
| **High-confidence suspicion** | Several meaningful indicators support suspicion. Evidence and limitations are shown. | The rule's action, after reviewing the evidence |
| **Needs review** | Ambiguous evidence. Never recommended for deletion. | Review manually |
| **Likely legitimate** | Identity of known legitimate software, or a valid signature. Not a guarantee. Hidden unless `detection.reportLikelyLegitimate` is on. | None |
| **Unverified** | Weak evidence and the item could not be fully inspected (too large, corrupt, limits). | Review manually |

Four values are kept separate for every finding:

- **Confidence** — how strongly the evidence supports the classification (`Verified` requires a definitive
  indicator such as an exact hash or bytecode signature).
- **Severity** — potential harm of the matched family; capped at *Low* for *Needs review* / *Unverified*.
- **Reputation** — what is known about the file itself (Known malicious, Known cheat, Suspicious, Known legitimate, Trusted signature, Unknown).
- **Recommended action** — No action, Manual review, Quarantine, or Quarantine and check the whole system.
  Permanent deletion is never recommended automatically.

When several rules match one file they are aggregated into **one finding** (unique files are counted once;
the number of rule matches is reported separately as *detection events*).

## Bundled database 2026.10.11.1

| Rule | Family | Category | Severity | Strongest result | Indicator types | Platforms | Sources (retrieved 2026-10-11) |
|---|---|---|---|---|---|---|---|
| `CP-HC-0001` | Wurst Client | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [Wurst7 fabric.mod.json (mod id, entrypoint package)](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/resources/fabric.mod.json); [Wurst7 wurst.mixins.json (mixin package net.wurstclient.mixin)](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/resources/wurst.mixins.json); [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java) |
| `CP-HC-0002` | Meteor Client | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [Meteor Client fabric.mod.json (mod id, entrypoint package)](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/resources/fabric.mod.json); [Meteor Client meteor-client.mixins.json](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/resources/meteor-client.mixins.json); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java) |
| `CP-HC-0003` | LiquidBounce | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [LiquidBounce fabric.mod.json (describes itself as a hacked client)](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/resources/fabric.mod.json); [LiquidBounce liquidbounce.mixins.json](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/resources/liquidbounce.mixins.json); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt) |
| `CP-HC-0004` | BleachHack | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [BleachHack fabric.mod.json](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/resources/fabric.mod.json); [BleachHack bleachhack.mixins.json](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/resources/bleachhack.mixins.json); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java) |
| `CP-HC-0005` | ThunderHack | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [ThunderHack Recode fabric.mod.json](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/resources/fabric.mod.json); [ThunderHack thunderhack.mixins.json](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/resources/thunderhack.mixins.json); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java) |
| `CP-HEUR-0001` | Generic combat cheat modules | CombatAutomation | Medium | High-confidence | ArchiveEntryPattern | all | [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java) |
| `CP-HEUR-0002` | Generic movement and timer cheat modules | MovementOrTimer | Medium | High-confidence | ArchiveEntryPattern | all | [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java) |
| `CP-HEUR-0003` | Generic X-ray and ESP cheat modules | XRayOrEsp | Medium | High-confidence | ArchiveEntryPattern | all | [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java) |
| `CP-HEUR-0004` | Generic hacked-client module layout | HackedClient | Medium | High-confidence | ArchiveEntryPattern | all | [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java) |
| `CP-HEUR-0005` | Known hacked-client name in file name | HackedClient | Medium | Needs review | FileNamePattern | all | heuristic — rationale in rule |
| `CP-HEUR-0006` | X-ray resource pack (name based) | XRayOrEsp | Low | Needs review | ArchiveEntry, FileNamePattern | all | heuristic — rationale in rule |
| `CP-AUTO-0001` | Baritone (pathfinding/automation bot) | GameplayAutomation | Low | Needs review | ArchiveEntry, ModId | all | [Baritone fabric.mod.json](https://github.com/cabaletta/baritone/blob/1.21.1/fabric/src/main/resources/fabric.mod.json) |
| `CP-CFG-0001` | Wurst Client configuration leftovers | CheatConfiguration | Low | Known match | DirectoryName, RelativePath | all | [Wurst7 WurstClient.java (config folder and files)](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/WurstClient.java) |
| `CP-CFG-0002` | Meteor Client data folder | CheatConfiguration | Low | Needs review | DirectoryName | all | [Meteor Client MeteorClient.java (FOLDER)](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/MeteorClient.java) |
| `CP-CFG-0003` | LiquidBounce data folder | CheatConfiguration | Low | Needs review | DirectoryName | all | [LiquidBounce ConfigSystem.kt (rootFolder)](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/config/ConfigSystem.kt); [LiquidBounce.kt (CLIENT_NAME)](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/LiquidBounce.kt) |
| `CP-MAL-0001` | fractureiser stage 0 (infected mod or plugin) | Malware | Critical | Known match | BytecodeSignature | all | [nekodetector Detector.java (stage 0 signatures and stage 2 checks)](https://github.com/MCRcortex/nekodetector/blob/master/src/main/java/me/cortex/jarscanner/Detector.java); [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md); [fractureiser investigation: user guide (Am I infected?)](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/users.md) |
| `CP-MAL-0002` | fractureiser stage 2 (lib.jar / libWebGL64.jar) | Malware | Critical | Known match | Sha1 | all | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md) |
| `CP-MAL-0003` | fractureiser stage 2 persistence folder | Malware | Critical | High-confidence | KnownLocation | windows | [fractureiser investigation: user guide (Am I infected?)](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/users.md); [nekodetector Detector.java (stage 0 signatures and stage 2 checks)](https://github.com/MCRcortex/nekodetector/blob/master/src/main/java/me/cortex/jarscanner/Detector.java) |
| `CP-MAL-0004` | fractureiser stage 2/3 files | Malware | Critical | Known match | KnownLocation | windows | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md); [fractureiser investigation: user guide (Am I infected?)](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/users.md); [nekodetector Detector.java (stage 0 signatures and stage 2 checks)](https://github.com/MCRcortex/nekodetector/blob/master/src/main/java/me/cortex/jarscanner/Detector.java) |
| `CP-MAL-0005` | fractureiser stage 3 client (NekoClient) | Malware | Critical | Known match | ClassPackagePrefix | all | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md) |
| `CP-MAL-0006` | fractureiser stage 3b persistence | Malware | Critical | High-confidence | KnownLocation | windows | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md) |
| `CP-MAL-0007` | fractureiser startup persistence | Malware | Critical | High-confidence | FileName, StartupCommandPattern | windows | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md); [nekodetector Detector.java (stage 0 signatures and stage 2 checks)](https://github.com/MCRcortex/nekodetector/blob/master/src/main/java/me/cortex/jarscanner/Detector.java) |
| `CP-LEGIT-0001` | Sodium | LegitimateSoftware | None | Likely legitimate | ClassPackagePrefix, ModId | all | [Sodium fabric.mod.json](https://github.com/CaffeineMC/sodium/blob/dev/fabric/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0002` | Iris Shaders | LegitimateSoftware | None | Likely legitimate | ClassPackagePrefix, ModId | all | [Iris fabric.mod.json](https://github.com/IrisShaders/Iris/blob/1.21.4/fabric/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0003` | Lithium | LegitimateSoftware | None | Likely legitimate | ClassPackagePrefix, ModId | all | [Lithium fabric.mod.json](https://github.com/CaffeineMC/lithium/blob/develop/fabric/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0004` | Mod Menu | LegitimateSoftware | None | Likely legitimate | ClassPackagePrefix, ModId | all | [Mod Menu fabric.mod.json](https://github.com/TerraformersMC/ModMenu/blob/1.21/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0005` | Fabric Loader | LegitimateSoftware | None | Likely legitimate | ModId | all | [Fabric Loader fabric.mod.json](https://github.com/FabricMC/fabric-loader/blob/master/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0006` | Fabric API | LegitimateSoftware | None | Likely legitimate | ModId | all | [Fabric API fabric.mod.json](https://github.com/FabricMC/fabric/blob/1.21.1/src/main/resources/fabric.mod.json) |
| `CP-TEST-0001` | Minecraft Cleaner Pro harmless test file | TestSignature | Informational | Known match | FileName, Sha256 | all | n/a (test signature) |

### Indicator verification notes

- Cheat clients: `fabric.mod.json` (mod id, entry points), the mixin configuration file and its `package`,
  and module class paths were read from each project's official repository on 2026-10-11.
- fractureiser: stage 0 signatures are the three instruction sequences of `nekodetector` (`SIG1` ordered-filter
  semantics are reproduced exactly; `SIG2` from any start; `SIG3` — the byte array spelling the original
  command-and-control address — is matched **strictly contiguously**, which is at least as specific as
  nekodetector). Stage 2 SHA-1 hashes, file names, the disguised `Microsoft Edge` folder, the stage 3
  `dev.neko.nekoclient` package and the stage 3b persistence paths come from the investigation's documents.
- Legitimate mods: mod ids and packages from the official Sodium, Iris, Lithium, Mod Menu, Fabric Loader and
  Fabric API repositories.

## Harmless test signature

`CP-TEST-0001` matches a text file whose exact content is:

```
MINECRAFT-CLEANER-PRO HARMLESS TEST FILE v1
This file contains no code. It only exists to confirm that detection, quarantine and restore work.
```

(LF line endings; SHA-256 `6fab04ffb2267b6330c4551365755c5dbb072ba7bc0b98d14fde7dc6d27cacae`).
**Scanner → Run detection self-test** creates it in `%TEMP%\MinecraftCleanerPro-SelfTest\` and scans it.

## Database format

```jsonc
{
  "formatVersion": 1,
  "databaseVersion": 2026101101,          // monotonic; used for anti-rollback
  "displayVersion": "2026.10.11.1",
  "publishedAt": "2026-10-11T00:00:00Z",
  "expiresAt": null,                      // required (non-null, future) for downloaded updates
  "rules": [ {
    "id": "CP-HC-0001", "version": 1, "family": "Wurst Client",
    "category": "HackedClient", "severity": "Medium",
    "appliesTo": ["Archive"],              // Archive | File | Directory | StartupEntry
    "fileExtensions": [".jar", ".zip"],   // optional
    "platforms": [],                       // optional: windows | linux | macos
    "heuristic": false,
    "indicators": [
      { "id": "mod-id",  "type": "ModId", "value": "wurst", "strength": "Strong" },
      { "id": "package", "type": "ClassPackagePrefix", "value": "net/wurstclient/", "strength": "Strong" }
    ],
    "classification": {
      "knownMatch":              [ { "all": ["mod-id", "package"] } ],
      "highConfidenceSuspicion": [ { "all": ["package"] } ],
      "needsReview":             [ { "any": ["mod-id"] } ]
      // conditions may also use "counts": [ { "atLeast": 2, "of": [ ... ] } ]
    },
    "recommendedAction": "Quarantine", "reputationOnMatch": "KnownCheat",
    "confidenceRationale": "…", "falsePositiveNotes": "…", "limitations": "…",
    "sources": [ { "title": "…", "url": "https://…", "retrieved": "2026-10-11" } ],
    "verifiedOn": "2026-10-11"
  } ]
}
```

Indicator types: `Sha256`, `Sha1`, `ModId` (Fabric/Quilt/Forge/NeoForge/legacy metadata, optional `loader`),
`ClassPackagePrefix`, `ArchiveEntry`, `ArchiveEntryPattern` (regex), `BytecodeSignature`
(`mode`: `OrderedOpcodeFilter`, `OrderedOpcodeFilterAnyStart`, `Contiguous`), `FileName` and
`FileNamePattern` (optional `locationTemplate`), `RelativePath` (inside an installation),
`DirectoryName` (optional `atInstallationRoot`), `KnownLocation` (`%VARIABLE%\path`, `expect`),
`ManifestAttribute`, `StartupCommandPattern`.

The loader validates everything and rejects the whole database on any error: unique ids, valid regular
expressions (with a 250 ms match timeout), hash formats, conditions referencing existing indicators, sources
and verification dates for non-heuristic rules, no Known match for heuristics, legitimacy rules limited to
*Likely legitimate*, and so on.

## Adding or changing a rule

1. Find a **primary source** (official repository, vendor advisory, published investigation).
2. Add the rule with every indicator you verified, a rationale, false-positive notes, limitations,
   `sources` and `verifiedOn`. Increase `databaseVersion` and `displayVersion`.
3. `dotnet run --project tools/CleanerPro.RuleTool -- validate rules/cleanerpro-rules.json`
4. Add harmless fixtures and tests (see `tests/CleanerPro.Detection.Tests`). Never use real malware.

## Signed updates

- An update is two files served from an HTTPS base URL: `rules.json` and `rules.json.sig`
  (base64 DER ECDSA P-256 / SHA-256 signature over the exact bytes).
- `CleanerPro.RuleTool keygen <key.private.pem>` creates a key pair; `sign` and `verify` handle signatures.
  Keep private keys out of source control (`*.private.pem` is git-ignored).
- The application accepts an update only if: offline mode is off, updates are enabled, the request goes to
  the configured HTTPS host, the response is within the size limit, the signature verifies with a trusted key
  (built-in keys — none in this release — plus `ruleUpdates.additionalTrustedPublicKeys`), the database is
  valid, `expiresAt` is set and in the future, and `databaseVersion` is higher than both the bundled database
  and every version accepted before (**anti-rollback**).
- Installed updates are re-verified on every start; a tampered, expired or rolled-back file is ignored with a
  visible warning and the bundled rules are used.
- **No official update service exists for this release.** Without configuration the application explains
  this and works offline with its bundled rules.
