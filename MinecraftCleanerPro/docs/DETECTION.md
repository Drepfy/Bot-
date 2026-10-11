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
- **No invented indicators.** No hashes, signatures or citations were made up. Closed-source clients (for example
  Vape, Future, RusherHack, Konas, Aristois, Impact, Rise, Novoline) publish nothing that could be verified, so
  they are only recognised **by name**, which is weak evidence and only ever leads to *Needs review*. Clients that
  are injected into the running game, and stand-alone auto-clickers, may leave no file to find at all.

## How cheats are found, and how they could still slip through

| Technique | What it catches | Limitation |
|---|---|---|
| Mod id + class package + mixin/core-mod fingerprints | Open-source clients, even when the jar is renamed | Obfuscated or repackaged builds can change all of them |
| Forge `FMLCorePlugin` / `TweakClass` manifest attributes | 1.8.9 / 1.12.2 clients (KAMI Blue, SalHack, ForgeHax, 3arthh4ck, Seppuku, GameSense, Ares, LiquidBounce legacy and forks) | Same as above |
| `"meteor"` entrypoint | Every Meteor Client add-on, including unknown ones | Only Meteor add-ons |
| `rusherhack-plugin.json` | Every RusherHack plugin | RusherHack itself is closed source (name only) |
| **Impersonation check** (`none` conditions) | A jar claiming to be Sodium, Iris, Lithium, Mod Menu or ImmediatelyFast without any of their real packages — the way Argon hides | Only the listed mods; not used when a jar could not be read completely |
| Content-based jar recognition | Jars renamed to `.disabled`, `.dat`, no extension… | Jars renamed to picture, sound, world or office formats are not opened |
| Java agents in launch settings and `JAVA_TOOL_OPTIONS`/`_JAVA_OPTIONS`/`JDK_JAVA_OPTIONS` | Cheats loaded with `-javaagent` from anywhere on the disk; the loaded file is scanned too | Agents attached to a running game or DLL injection leave no setting |
| Generic module-layout heuristics | Unknown clients organised as `modules/combat/KillAura` etc. | Obfuscated clients; review only |
| Client names in file names (also in Downloads/Desktop on Full scans) | Closed-source clients, installers | Renamed files; review only |
| fractureiser bytecode signatures, hashes and locations | Infected mods and the malware's later stages | Only the documented variants |

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

## Bundled database 2026.10.11.2

63 rules. Generated from `rules/build_rules.py`; the JSON is the authoritative copy.

| Rule | Family | Category | Severity | Strongest result | Indicator types | Platforms | Sources (retrieved 2026-10-11) |
|---|---|---|---|---|---|---|---|
| `CP-ADDON-0001` | Meteor Client add-on | HackedClient | Medium | High-confidence | ModEntrypoint | all | [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0002` | Meteor Rejects | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModEntrypoint, ModId | all | [Meteor Rejects fabric.mod.json (entrypoint anticope.rejects.MeteorRejectsAddon)](https://github.com/AntiCope/meteor-rejects/blob/master/src/main/resources/fabric.mod.json); [Meteor Rejects meteor-rejects.mixins.json](https://github.com/AntiCope/meteor-rejects/blob/master/src/main/resources/meteor-rejects.mixins.json); [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0003` | Meteor Crash Addon | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModEntrypoint, ModId | all | [Meteor Crash Addon fabric.mod.json ('help you crash servers')](https://github.com/AntiCope/meteor-crash-addon/blob/main/src/main/resources/fabric.mod.json); [Meteor Crash Addon meteorcrashaddon.mixins.json](https://github.com/AntiCope/meteor-crash-addon/blob/main/src/main/resources/meteorcrashaddon.mixins.json); [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0004` | Trouser-Streak | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModEntrypoint, ModId | all | [Trouser-Streak fabric.mod.json ('optimized for maximum grief')](https://github.com/etianl/Trouser-Streak/blob/main/src/main/resources/fabric.mod.json); [Trouser-Streak streak.mixins.json](https://github.com/etianl/Trouser-Streak/blob/main/src/main/resources/streak.mixins.json); [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0005` | Meteor+ (MeteorPlus) | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModEntrypoint, ModId | all | [Meteor+ (MeteorPlus) fabric.mod.json ('adds many blatant features')](https://github.com/Nekiplay/MeteorPlus/blob/main/src/main/resources/fabric.mod.json); [Meteor+ (MeteorPlus) meteorplus.mixins.json](https://github.com/Nekiplay/MeteorPlus/blob/main/src/main/resources/meteorplus.mixins.json); [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0006` | Numby Hack | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModEntrypoint, ModId | all | [Numby Hack fabric.mod.json (Meteor add-on)](https://github.com/cqb13/Numby-hack/blob/main/src/main/resources/fabric.mod.json); [Numby Hack NumbyHack.mixins.json](https://github.com/cqb13/Numby-hack/blob/main/src/main/resources/NumbyHack.mixins.json); [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0007` | Meteorist | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModEntrypoint, ModId | all | [Meteorist fabric.mod.json (Meteor add-on)](https://github.com/Zgoly/Meteorist/blob/main/src/main/resources/fabric.mod.json); [Meteorist meteorist.mixins.json](https://github.com/Zgoly/Meteorist/blob/main/src/main/resources/meteorist.mixins.json); [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0008` | Vector Addon | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModEntrypoint, ModId | all | [Vector Addon fabric.mod.json ('combat and many utility modules')](https://github.com/cally72jhb/vector-addon/blob/main/src/main/resources/fabric.mod.json); [Vector Addon vector-addon.mixins.json](https://github.com/cally72jhb/vector-addon/blob/main/src/main/resources/vector-addon.mixins.json); [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0009` | BlackOut | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModEntrypoint, ModId | all | [BlackOut fabric.mod.json ('Epik cheetos addon')](https://github.com/KassuK1/BlackOut/blob/main/src/main/resources/fabric.mod.json); [BlackOut blackout.mixins.json](https://github.com/KassuK1/BlackOut/blob/main/src/main/resources/blackout.mixins.json); [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0010` | Orion | HackedClient | Medium | Known match | ClassPackagePrefix, ModEntrypoint, ModId | all | [Orion fabric.mod.json ('A combat addon for Meteor Client')](https://github.com/AntiCope/orion/blob/main/src/main/resources/fabric.mod.json); [Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)](https://github.com/MeteorDevelopment/meteor-addon-template/blob/master/src/main/resources/fabric.mod.json) |
| `CP-ADDON-0011` | RusherHack plugin | HackedClient | Medium | High-confidence | ArchiveEntry | all | [RusherHack example plugin rusherhack-plugin.json](https://github.com/RusherDevelopment/example-plugin/blob/master/src/main/resources/rusherhack-plugin.json) |
| `CP-AUTO-0001` | Baritone (pathfinding/automation bot) | GameplayAutomation | Low | Needs review | ArchiveEntry, ModId | all | [Baritone fabric.mod.json](https://github.com/cabaletta/baritone/blob/1.21.1/fabric/src/main/resources/fabric.mod.json) |
| `CP-CFG-0001` | Wurst Client configuration leftovers | CheatConfiguration | Low | Known match | DirectoryName, RelativePath | all | [Wurst7 WurstClient.java (config folder and files)](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/WurstClient.java) |
| `CP-CFG-0002` | Meteor Client data folder | CheatConfiguration | Low | Needs review | DirectoryName | all | [Meteor Client MeteorClient.java (FOLDER)](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/MeteorClient.java) |
| `CP-CFG-0003` | LiquidBounce data folder | CheatConfiguration | Low | Needs review | DirectoryName | all | [LiquidBounce ConfigSystem.kt (rootFolder)](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/config/ConfigSystem.kt); [LiquidBounce.kt (CLIENT_NAME)](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/LiquidBounce.kt) |
| `CP-HC-0001` | Wurst Client | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [Wurst7 fabric.mod.json (mod id, entrypoint package)](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/resources/fabric.mod.json); [Wurst7 wurst.mixins.json (mixin package net.wurstclient.mixin)](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/resources/wurst.mixins.json); [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java) |
| `CP-HC-0002` | Meteor Client | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [Meteor Client fabric.mod.json (mod id, entrypoint package)](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/resources/fabric.mod.json); [Meteor Client meteor-client.mixins.json](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/resources/meteor-client.mixins.json); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java) |
| `CP-HC-0003` | LiquidBounce | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ManifestAttribute, ModId | all | [LiquidBounce fabric.mod.json (describes itself as a hacked client)](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/resources/fabric.mod.json); [LiquidBounce liquidbounce.mixins.json](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/resources/liquidbounce.mixins.json); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt); [LiquidBounce legacy (Forge 1.8.9) mcmod.info](https://github.com/CCBlueX/LiquidBounce/blob/legacy/src/main/resources/mcmod.info); [LiquidBounce legacy build.gradle (FMLCorePlugin, MixinConfigs)](https://github.com/CCBlueX/LiquidBounce/blob/legacy/build.gradle) |
| `CP-HC-0004` | BleachHack | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [BleachHack fabric.mod.json](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/resources/fabric.mod.json); [BleachHack bleachhack.mixins.json](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/resources/bleachhack.mixins.json); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java) |
| `CP-HC-0005` | ThunderHack | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [ThunderHack Recode fabric.mod.json](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/resources/fabric.mod.json); [ThunderHack thunderhack.mixins.json](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/resources/thunderhack.mixins.json); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java); [ThunderHack Recode README (lists malicious renamed copies)](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/README.md) |
| `CP-HC-0006` | Aoba Client | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [Aoba Client fabric.mod.json (mod id, entrypoint net.aoba.Aoba)](https://github.com/coltonk9043/Aoba-Client/blob/master/src/main/resources/fabric.mod.json); [Aoba Client aoba.mixins.json (package net.aoba.mixin)](https://github.com/coltonk9043/Aoba-Client/blob/master/src/main/resources/aoba.mixins.json) |
| `CP-HC-0007` | Argon (ghost client) | GhostClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [Argon fabric.mod.json (id 'immediatelyfast', entrypoint dev.lvstrng.argon.Main)](https://github.com/LvStrnggg/argon/blob/main/src/main/resources/fabric.mod.json); [Argon client.mixins.json (package dev.lvstrng.argon.mixin)](https://github.com/LvStrnggg/argon/blob/main/src/main/resources/client.mixins.json); [Argon README ('Argon Minecraft Ghost Client')](https://github.com/LvStrnggg/argon/blob/main/README.md) |
| `CP-HC-0008` | Jex Client | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [Jex Client fabric.mod.json (mod id, entrypoint me.dustin.jex.load.JexLoad)](https://github.com/DustinRepo/JexClient/blob/main/src/main/resources/fabric.mod.json); [Jex Client jex.mixins.json](https://github.com/DustinRepo/JexClient/blob/main/src/main/resources/jex.mixins.json) |
| `CP-HC-0009` | AnarchyClient (6b6t) | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [AnarchyClient fabric.mod.json (mod id, entrypoint net.blockhost.anarchyclient.AnarchyClient)](https://github.com/6b6t/AnarchyClient/blob/main/src/main/resources/fabric.mod.json) |
| `CP-HC-0010` | Ares | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ManifestAttribute, ModId | all | [Ares mcmod.info ('Ares is a minecraft cheat client')](https://github.com/AresClient/ares/blob/master/ares-forge/src/main/resources/mcmod.info); [Ares Forge build.gradle (FMLCorePlugin, MixinConfigs)](https://github.com/AresClient/ares/blob/master/ares-forge/build.gradle); [Ares Fabric fabric.mod.json](https://github.com/AresClient/ares/blob/master/ares-fabric/src/main/resources/fabric.mod.json); [Ares gradle.properties (modGroup dev.tigr.ares)](https://github.com/AresClient/ares/blob/master/gradle.properties) |
| `CP-HC-0011` | KAMI Blue | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ManifestAttribute, ModId | all | [KAMI Blue mcmod.info](https://github.com/kami-blue/client/blob/master/src/main/resources/mcmod.info); [KAMI Blue build.gradle (FMLCorePlugin, MixinConfigs)](https://github.com/kami-blue/client/blob/master/build.gradle) |
| `CP-HC-0012` | Lambda (legacy, Forge 1.12.2) | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ManifestAttribute, ModId | all | [Lambda legacy mcmod.info](https://github.com/lambda-client/lambda-legacy/blob/master/src/main/resources/mcmod.info); [Lambda legacy build.gradle (FMLCorePlugin com.lambda.client.LambdaCoreMod)](https://github.com/lambda-client/lambda-legacy/blob/master/build.gradle) |
| `CP-HC-0013` | Lambda (Fabric) | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ModId | all | [Lambda fabric.mod.json (entrypoint com.lambda.Lambda, mixins ${modId}.mixins.json)](https://github.com/lambda-client/lambda/blob/master/src/main/resources/fabric.mod.json); [Lambda gradle.properties (modId=lambda, mavenGroup=com.lambda)](https://github.com/lambda-client/lambda/blob/master/gradle.properties) |
| `CP-HC-0014` | SalHack | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ManifestAttribute, ModId | all | [SalHack mcmod.info](https://github.com/ionar2/salhack/blob/master/src/main/resources/mcmod.info); [SalHack build.gradle (FMLCorePlugin, MixinConfigs)](https://github.com/ionar2/salhack/blob/master/build.gradle) |
| `CP-HC-0015` | ForgeHax | HackedClient | Medium | Known match | ClassPackagePrefix, ManifestAttribute, ModId | all | [ForgeHax mcmod.info ('Hax 4 forge')](https://github.com/fr1kin/ForgeHax/blob/master/src/main/resources/mcmod.info); [ForgeHax build.gradle (group com.matt.forgehax, FMLCorePlugin)](https://github.com/fr1kin/ForgeHax/blob/master/build.gradle) |
| `CP-HC-0016` | 3arthh4ck | HackedClient | Medium | Known match | ClassPackagePrefix, ManifestAttribute, ModId | all | [3arthh4ck mcmod.info ('A 1.12.2 Anarchy Client')](https://github.com/3arthqu4ke/3arthh4ck/blob/main/src/main/resources/mcmod.info); [3arthh4ck build.gradle (TweakClass me.earth.earthhack.tweaker.EarthhackTweaker)](https://github.com/3arthqu4ke/3arthh4ck/blob/main/build.gradle) |
| `CP-HC-0017` | Seppuku | HackedClient | Medium | Known match | ClassPackagePrefix, ManifestAttribute, ModId | all | [Seppuku mcmod.info ('a hacked client built on forge')](https://github.com/seppukudevelopment/seppuku/blob/master/src/main/resources/mcmod.info); [Seppuku build.gradle (FMLCorePlugin)](https://github.com/seppukudevelopment/seppuku/blob/master/build.gradle) |
| `CP-HC-0018` | GameSense | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ManifestAttribute, ModId | all | [GameSense mcmod.info ('1.12.2 Anarchy Client')](https://github.com/IUDevman/gamesense-client/blob/master/src/main/resources/mcmod.info); [GameSense build.gradle (FMLCorePlugin, MixinConfigs)](https://github.com/IUDevman/gamesense-client/blob/master/build.gradle) |
| `CP-HC-0019` | FDPClient (LiquidBounce fork) | HackedClient | Medium | Known match | ArchiveEntry, ClassPackagePrefix, ManifestAttribute, ModId | all | [FDPClient mcmod.info ('A free mixin-based injection hacked-client')](https://github.com/SkidderMC/FDPClient/blob/main/src/main/resources/mcmod.info); [FDPClient build.gradle (FMLCorePlugin, MixinConfigs fdpclient.forge.mixins.json)](https://github.com/SkidderMC/FDPClient/blob/main/build.gradle) |
| `CP-HC-0020` | MinusBounce (LiquidBounce fork) | HackedClient | Medium | Known match | ClassPackagePrefix, ModId | all | [MinusBounce mcmod.info (authors CCBlueX, MinusMC)](https://github.com/Rylazius/MinusBounce/blob/main/src/main/resources/mcmod.info) |
| `CP-HEUR-0001` | Generic combat cheat modules | CombatAutomation | Medium | High-confidence | ArchiveEntryPattern | all | [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java) |
| `CP-HEUR-0002` | Generic movement and timer cheat modules | MovementOrTimer | Medium | High-confidence | ArchiveEntryPattern | all | [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java) |
| `CP-HEUR-0003` | Generic X-ray and ESP cheat modules | XRayOrEsp | Medium | High-confidence | ArchiveEntryPattern | all | [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java) |
| `CP-HEUR-0004` | Generic hacked-client module layout | HackedClient | Medium | High-confidence | ArchiveEntryPattern | all | [Wurst7 hack modules, e.g. KillauraHack](https://github.com/Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java); [Meteor Client combat module KillAura](https://github.com/MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java); [LiquidBounce ModuleKillAura](https://github.com/CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt); [BleachHack Killaura module](https://github.com/BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java); [ThunderHack combat module Aura](https://github.com/Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java) |
| `CP-HEUR-0005` | Known hacked-client name in file name | HackedClient | Medium | Needs review | FileNamePattern | all | heuristic — rationale in rule |
| `CP-HEUR-0006` | X-ray resource pack (name based) | XRayOrEsp | Low | Needs review | ArchiveEntry, FileNamePattern | all | heuristic — rationale in rule |
| `CP-IMP-0001` | Impersonation of Sodium | GhostClient | Medium | High-confidence | ClassPackagePrefix, ModId | all | [Sodium fabric.mod.json](https://github.com/CaffeineMC/sodium/blob/dev/fabric/src/main/resources/fabric.mod.json); [Sodium 1.20.1 fabric.mod.json (entrypoint me.jellysquid.mods.sodium.client.SodiumClientMod)](https://github.com/CaffeineMC/sodium/blob/1.20.1/stable/src/main/resources/fabric.mod.json) |
| `CP-IMP-0002` | Impersonation of Iris Shaders | GhostClient | Medium | High-confidence | ClassPackagePrefix, ModId | all | [Iris fabric.mod.json](https://github.com/IrisShaders/Iris/blob/1.21.4/fabric/src/main/resources/fabric.mod.json); [Iris 1.18.2 fabric.mod.json (net.coderbot.iris)](https://github.com/IrisShaders/Iris/blob/1.18.2/src/main/resources/fabric.mod.json) |
| `CP-IMP-0003` | Impersonation of Lithium | GhostClient | Medium | High-confidence | ClassPackagePrefix, ModId | all | [Lithium fabric.mod.json](https://github.com/CaffeineMC/lithium/blob/develop/fabric/src/main/resources/fabric.mod.json); [Lithium 1.20.1 fabric.mod.json (entrypoint me.jellysquid.mods.lithium.common.LithiumMod)](https://github.com/CaffeineMC/lithium/blob/1.20.1/src/main/resources/fabric.mod.json) |
| `CP-IMP-0004` | Impersonation of Mod Menu | GhostClient | Medium | High-confidence | ClassPackagePrefix, ModId | all | [Mod Menu fabric.mod.json](https://github.com/TerraformersMC/ModMenu/blob/1.21/src/main/resources/fabric.mod.json); [Mod Menu 1.15 fabric.mod.json (io.github.prospector.modmenu)](https://github.com/TerraformersMC/ModMenu/blob/1.15/src/main/resources/fabric.mod.json) |
| `CP-IMP-0005` | Impersonation of ImmediatelyFast | GhostClient | Medium | High-confidence | ClassPackagePrefix, ModId | all | [ImmediatelyFast fabric.mod.json](https://github.com/RaphiMC/ImmediatelyFast/blob/master/fabric/src/main/resources/fabric.mod.json); [ImmediatelyFast mixins (package net.raphimc.immediatelyfast.injection.mixins)](https://github.com/RaphiMC/ImmediatelyFast/blob/master/common/src/main/resources/immediatelyfast-common.mixins.json) |
| `CP-LEGIT-0001` | Sodium | LegitimateSoftware | None | Likely legitimate | ClassPackagePrefix, ModId | all | [Sodium fabric.mod.json](https://github.com/CaffeineMC/sodium/blob/dev/fabric/src/main/resources/fabric.mod.json); [Sodium 1.20.1 fabric.mod.json (entrypoint me.jellysquid.mods.sodium.client.SodiumClientMod)](https://github.com/CaffeineMC/sodium/blob/1.20.1/stable/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0002` | Iris Shaders | LegitimateSoftware | None | Likely legitimate | ClassPackagePrefix, ModId | all | [Iris fabric.mod.json](https://github.com/IrisShaders/Iris/blob/1.21.4/fabric/src/main/resources/fabric.mod.json); [Iris 1.18.2 fabric.mod.json (net.coderbot.iris)](https://github.com/IrisShaders/Iris/blob/1.18.2/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0003` | Lithium | LegitimateSoftware | None | Likely legitimate | ClassPackagePrefix, ModId | all | [Lithium fabric.mod.json](https://github.com/CaffeineMC/lithium/blob/develop/fabric/src/main/resources/fabric.mod.json); [Lithium 1.20.1 fabric.mod.json (entrypoint me.jellysquid.mods.lithium.common.LithiumMod)](https://github.com/CaffeineMC/lithium/blob/1.20.1/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0004` | Mod Menu | LegitimateSoftware | None | Likely legitimate | ClassPackagePrefix, ModId | all | [Mod Menu fabric.mod.json](https://github.com/TerraformersMC/ModMenu/blob/1.21/src/main/resources/fabric.mod.json); [Mod Menu 1.15 fabric.mod.json (io.github.prospector.modmenu)](https://github.com/TerraformersMC/ModMenu/blob/1.15/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0005` | Fabric Loader | LegitimateSoftware | None | Likely legitimate | ModId | all | [Fabric Loader fabric.mod.json](https://github.com/FabricMC/fabric-loader/blob/master/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0006` | Fabric API | LegitimateSoftware | None | Likely legitimate | ModId | all | [Fabric API fabric.mod.json](https://github.com/FabricMC/fabric/blob/1.21.1/src/main/resources/fabric.mod.json) |
| `CP-LEGIT-0007` | ImmediatelyFast | LegitimateSoftware | None | Likely legitimate | ClassPackagePrefix, ModId | all | [ImmediatelyFast fabric.mod.json](https://github.com/RaphiMC/ImmediatelyFast/blob/master/fabric/src/main/resources/fabric.mod.json); [ImmediatelyFast mixins (package net.raphimc.immediatelyfast.injection.mixins)](https://github.com/RaphiMC/ImmediatelyFast/blob/master/common/src/main/resources/immediatelyfast-common.mixins.json) |
| `CP-LOAD-0001` | Code loaded through JVM options (Java agent) | InjectedModule | Medium | Needs review | StartupCommandPattern | all | [OpenJDK launcher help (-javaagent, -agentpath, -agentlib, -Xbootclasspath/a)](https://github.com/openjdk/jdk/blob/master/src/java.base/share/classes/sun/launcher/resources/launcher.properties); [OpenJDK 8 launcher help (-Xbootclasspath/p)](https://github.com/openjdk/jdk8u/blob/master/jdk/src/share/classes/sun/launcher/resources/launcher.properties); [OpenJDK HotSpot arguments.cpp (reads JAVA_TOOL_OPTIONS and _JAVA_OPTIONS)](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/runtime/arguments.cpp); [OpenJDK launcher args.c (reads JDK_JAVA_OPTIONS)](https://github.com/openjdk/jdk/blob/master/src/java.base/share/native/libjli/args.c) |
| `CP-MAL-0001` | fractureiser stage 0 (infected mod or plugin) | Malware | Critical | Known match | BytecodeSignature | all | [nekodetector Detector.java (stage 0 signatures and stage 2 checks)](https://github.com/MCRcortex/nekodetector/blob/master/src/main/java/me/cortex/jarscanner/Detector.java); [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md); [fractureiser investigation: user guide (Am I infected?)](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/users.md) |
| `CP-MAL-0002` | fractureiser stage 2 (lib.jar / libWebGL64.jar) | Malware | Critical | Known match | Sha1 | all | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md) |
| `CP-MAL-0003` | fractureiser stage 2 persistence folder | Malware | Critical | High-confidence | KnownLocation | windows | [fractureiser investigation: user guide (Am I infected?)](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/users.md); [nekodetector Detector.java (stage 0 signatures and stage 2 checks)](https://github.com/MCRcortex/nekodetector/blob/master/src/main/java/me/cortex/jarscanner/Detector.java) |
| `CP-MAL-0004` | fractureiser stage 2/3 files | Malware | Critical | Known match | KnownLocation | windows | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md); [fractureiser investigation: user guide (Am I infected?)](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/users.md); [nekodetector Detector.java (stage 0 signatures and stage 2 checks)](https://github.com/MCRcortex/nekodetector/blob/master/src/main/java/me/cortex/jarscanner/Detector.java) |
| `CP-MAL-0005` | fractureiser stage 3 client (NekoClient) | Malware | Critical | Known match | ClassPackagePrefix | all | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md) |
| `CP-MAL-0006` | fractureiser stage 3b persistence | Malware | Critical | High-confidence | KnownLocation | windows | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md) |
| `CP-MAL-0007` | fractureiser startup persistence | Malware | Critical | High-confidence | FileName, StartupCommandPattern | windows | [fractureiser investigation: technical analysis](https://github.com/fractureiser-investigation/fractureiser/blob/main/docs/tech.md); [nekodetector Detector.java (stage 0 signatures and stage 2 checks)](https://github.com/MCRcortex/nekodetector/blob/master/src/main/java/me/cortex/jarscanner/Detector.java) |
| `CP-TEST-0001` | Minecraft Cleaner Pro harmless test file | TestSignature | Informational | Known match | FileName, Sha256 | all | n/a (test signature) |
| `CP-XRAY-0001` | Advanced XRay (x-ray mod) | XRayOrEsp | Medium | High-confidence | ClassPackagePrefix, ModId | all | [Advanced XRay fabric.mod.json (id 'xray', entrypoint pro.mikey.xray.fabric.XRayFabric)](https://github.com/AdvancedXRay/XRay-Mod/blob/main/fabric/src/main/resources/fabric.mod.json); [Advanced XRay xray.mixins.json (package pro.mikey.xray.mixins)](https://github.com/AdvancedXRay/XRay-Mod/blob/main/fabric/src/main/resources/xray.mixins.json) |

### Indicator verification notes

- Cheat clients: `fabric.mod.json` (mod id, entry points), the mixin configuration file and its `package`,
  and module class paths were read from each project's official repository on 2026-10-11.
- fractureiser: stage 0 signatures are the three instruction sequences of `nekodetector` (`SIG1` ordered-filter
  semantics are reproduced exactly; `SIG2` from any start; `SIG3` — the byte array spelling the original
  command-and-control address — is matched **strictly contiguously**, which is at least as specific as
  nekodetector). Stage 2 SHA-1 hashes, file names, the disguised `Microsoft Edge` folder, the stage 3
  `dev.neko.nekoclient` package and the stage 3b persistence paths come from the investigation's documents.
- Legitimate mods: mod ids and packages from the official Sodium, Iris, Lithium, Mod Menu, ImmediatelyFast,
  Fabric Loader and Fabric API repositories, including the older package names (for example
  `me.jellysquid.mods.sodium`, `net.coderbot.iris`, `io.github.prospector.modmenu`) read from older release branches,
  so old versions of these mods are not mistaken for impersonations.
- Forge clients: `mcmod.info` for the mod id, and `build.gradle` for the manifest attributes (`FMLCorePlugin`,
  `TweakClass`, `MixinConfigs`) that end up in every released jar.
- Argon: its `fabric.mod.json` declares the id and name of ImmediatelyFast while its entry point is
  `dev.lvstrng.argon.Main`.
- Java agent options: the OpenJDK launcher help (`-javaagent`, `-agentpath`, `-agentlib`, `-Xbootclasspath/a`, and
  `-Xbootclasspath/p` in JDK 8) and the OpenJDK sources that read `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS` and
  `JDK_JAVA_OPTIONS`.
- Repositories that could not be verified (for example Raven B+, Coffee Client, MatHax) are not covered by specific
  rules; only their names are in the name heuristic where they are distinctive enough.

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
  "databaseVersion": 2026101102,          // monotonic; used for anti-rollback
  "displayVersion": "2026.10.11.2",
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
      // and "none": [ ... ] (indicators that must be absent; needs a positive part, never in knownMatch,
      // and never satisfied for items that could not be fully inspected)
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
`ManifestAttribute`, `StartupCommandPattern` (also applied to Java options found in launcher settings and
environment variables), `ModEntrypoint` (a Fabric/Quilt entrypoint key such as `meteor`).

The loader validates everything and rejects the whole database on any error: unique ids, valid regular
expressions (with a 250 ms match timeout), hash formats, conditions referencing existing indicators, sources
and verification dates for non-heuristic rules, no Known match for heuristics, legitimacy rules limited to
*Likely legitimate*, and so on.

## Adding or changing a rule

1. Find a **primary source** (official repository, vendor advisory, published investigation).
2. Add the rule to `rules/build_rules.py` with every indicator you verified, a rationale, false-positive notes,
   limitations, `sources` and `verifiedOn`. Increase `databaseVersion` and `displayVersion`.
3. `python3 rules/build_rules.py rules/cleanerpro-rules.json --doc docs/DETECTION.md` (regenerates the JSON and
   the table above), then `dotnet run --project tools/CleanerPro.RuleTool -- validate rules/cleanerpro-rules.json`
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
