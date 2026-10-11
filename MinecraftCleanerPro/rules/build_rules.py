"""Source of the bundled rule database (rules/cleanerpro-rules.json).

Every identifier below was copied from the public source it cites, on the date in `D`. Nothing is guessed:
mod ids, package names, mixin configuration names and manifest attributes come from each project's own
fabric.mod.json, mcmod.info, mixin JSON or build.gradle; malware indicators come from the fractureiser
investigation and nekodetector; JVM options come from the OpenJDK sources.

Regenerate after editing:  python3 rules/build_rules.py rules/cleanerpro-rules.json --doc docs/DETECTION.md
Then validate:            dotnet run --project tools/CleanerPro.RuleTool -- validate rules/cleanerpro-rules.json
"""
import json
D = "2026-10-11"
def src(title, url): return {"title": title, "url": url, "retrieved": D}

GH = "https://github.com/"
WURST = [src("Wurst7 fabric.mod.json (mod id, entrypoint package)", GH+"Wurst-Imperium/Wurst7/blob/master/src/main/resources/fabric.mod.json"),
         src("Wurst7 wurst.mixins.json (mixin package net.wurstclient.mixin)", GH+"Wurst-Imperium/Wurst7/blob/master/src/main/resources/wurst.mixins.json"),
         src("Wurst7 hack modules, e.g. KillauraHack", GH+"Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/hacks/KillauraHack.java")]
METEOR = [src("Meteor Client fabric.mod.json (mod id, entrypoint package)", GH+"MeteorDevelopment/meteor-client/blob/master/src/main/resources/fabric.mod.json"),
          src("Meteor Client meteor-client.mixins.json", GH+"MeteorDevelopment/meteor-client/blob/master/src/main/resources/meteor-client.mixins.json"),
          src("Meteor Client combat module KillAura", GH+"MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/systems/modules/combat/KillAura.java")]
LB = [src("LiquidBounce fabric.mod.json (describes itself as a hacked client)", GH+"CCBlueX/LiquidBounce/blob/nextgen/src/main/resources/fabric.mod.json"),
      src("LiquidBounce liquidbounce.mixins.json", GH+"CCBlueX/LiquidBounce/blob/nextgen/src/main/resources/liquidbounce.mixins.json"),
      src("LiquidBounce ModuleKillAura", GH+"CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/features/module/modules/combat/killaura/ModuleKillAura.kt")]
BLEACH = [src("BleachHack fabric.mod.json", GH+"BleachDev/BleachHack/blob/1.19.4/src/main/resources/fabric.mod.json"),
          src("BleachHack bleachhack.mixins.json", GH+"BleachDev/BleachHack/blob/1.19.4/src/main/resources/bleachhack.mixins.json"),
          src("BleachHack Killaura module", GH+"BleachDev/BleachHack/blob/1.19.4/src/main/java/org/bleachhack/module/mods/Killaura.java")]
THUNDER = [src("ThunderHack Recode fabric.mod.json", GH+"Pan4ur/ThunderHack-Recode/blob/main/src/main/resources/fabric.mod.json"),
           src("ThunderHack thunderhack.mixins.json", GH+"Pan4ur/ThunderHack-Recode/blob/main/src/main/resources/thunderhack.mixins.json"),
           src("ThunderHack combat module Aura", GH+"Pan4ur/ThunderHack-Recode/blob/main/src/main/java/thunder/hack/features/modules/combat/Aura.java")]
FR_USERS = src("fractureiser investigation: user guide (Am I infected?)", GH+"fractureiser-investigation/fractureiser/blob/main/docs/users.md")
FR_TECH = src("fractureiser investigation: technical analysis", GH+"fractureiser-investigation/fractureiser/blob/main/docs/tech.md")
NEKO = src("nekodetector Detector.java (stage 0 signatures and stage 2 checks)", GH+"MCRcortex/nekodetector/blob/master/src/main/java/me/cortex/jarscanner/Detector.java")

FP_CLIENT = "Third-party addons for this client reuse its package names. Renamed or repackaged builds may not match. A matching file proves the client is installed, not that it was used on a server."
LIM_CLIENT = "Only installed files are detected. Builds that were obfuscated or relocated to other packages are not covered by this rule."

def cheat_rule(rid, family, modid, pkg, mixins, sources, extra_note="", coremod=None, category="HackedClient", version=1,
               extra_indicators=None, package_alone="highConfidenceSuspicion"):
    """A client identified by its mod id, its class package and its mixin configuration (plus, for Forge 1.8/1.12
    clients, the FMLCorePlugin/TweakClass named in the jar manifest). Two independent indicators make a known match."""
    indicators = [
        {"id": "mod-id", "type": "ModId", "value": modid, "strength": "Strong", "description": f"Mod metadata uses the {family} mod id"},
        {"id": "package", "type": "ClassPackagePrefix", "value": pkg, "strength": "Strong", "description": f"Classes in the {family} package"},
    ]
    known = [{"all": ["mod-id", "package"]}]
    high = []
    review = [{"any": ["mod-id"]}]
    if mixins:
        indicators.append({"id": "mixins", "type": "ArchiveEntry", "value": mixins, "strength": "Moderate", "description": f"{family} mixin configuration"})
        known.append({"all": ["package", "mixins"]})
        high.append({"all": ["mod-id", "mixins"]})
        review = [{"any": ["mod-id", "mixins"]}]
    if coremod:
        attribute, value = coremod
        indicators.append({"id": "coremod", "type": "ManifestAttribute", "attribute": attribute, "value": value, "strength": "Strong",
                           "description": f"JAR manifest {attribute} names the {family} loader class"})
        known.append({"all": ["package", "coremod"]})
        known.append({"all": ["mod-id", "coremod"]})
        high.append({"all": ["coremod"]})
    for indicator, condition in (extra_indicators or []):
        indicators.append(indicator)
        if condition:
            known.append(condition)
    if package_alone == "highConfidenceSuspicion":
        high.insert(0, {"all": ["package"]})
    else:
        review.append({"all": ["package"]})
    return {
        "id": rid, "version": version, "family": family, "category": category, "severity": "Medium",
        "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip"],
        "indicators": indicators,
        "classification": {"knownMatch": known, "highConfidenceSuspicion": high, "needsReview": review},
        "recommendedAction": "Quarantine", "reputationOnMatch": "KnownCheat",
        "confidenceRationale": f"The identifiers were taken from the official {family} source repository (see sources). Two independent indicators are required for a known match; a single indicator is reported as a suspicion or for review." + extra_note,
        "falsePositiveNotes": FP_CLIENT, "limitations": LIM_CLIENT, "sources": sources, "verifiedOn": D,
    }

RAW = "https://github.com/"
def gh(repo, branch, path, title):
    return src(title, f"{GH}{repo}/blob/{branch}/{path}")

def module_regex(names):
    return r"(?i)(^|/)(module|modules|hack|hacks|cheat|cheats|features)/([^/]+/){0,4}(module)?(" + names + r")(hack|module)?(\$[^/]*)?\.class$"

COMBAT = [("killaura", r"(kill_?)?aura"), ("aim", r"aim_?(assist|bot)"), ("triggerbot", r"trigger_?bot"), ("autoclicker", r"auto_?clicker"),
          ("reach", r"reach"), ("velocity", r"velocity|anti_?knockback|anti_?kb"), ("criticals", r"criticals?"),
          ("crystalaura", r"crystal_?aura|auto_?crystal"), ("hitbox", r"hit_?box(es)?")]
MOVEMENT = [("fly", r"fly|flight"), ("speed", r"speed"), ("timer", r"timer"), ("scaffold", r"scaffold(walk)?"), ("nofall", r"no_?fall"),
            ("noslow", r"no_?slow(down)?"), ("step", r"step"), ("spider", r"spider"), ("jesus", r"jesus"), ("blink", r"blink"), ("longjump", r"long_?jump")]
RENDER = [("xray", r"x_?ray"), ("esp", r"(player_?|chest_?|storage_?)?esp"), ("tracers", r"tracers?"), ("wallhack", r"wall_?hack"), ("chams", r"chams")]
INVENTORY = [("autototem", r"auto_?totem"), ("cheststealer", r"chest_?stealer|stealer"), ("autoarmor", r"auto_?armou?r"), ("invmanager", r"(inventory|inv)_?manager")]

def module_indicators(group, prefix=""):
    return [{"id": prefix + i, "type": "ArchiveEntryPattern", "value": module_regex(rx), "strength": "Weak",
             "description": f"Class named like a '{i}' cheat module inside a module/hack package"} for i, rx in group]

HEUR_FP = "Legitimate mods occasionally use these words for class names inside 'features' or 'modules' packages. Several distinct module names must appear together before anything is reported, and legitimacy evidence overrides this heuristic."
HEUR_RATIONALE = "Generic heuristic: hacked clients organise cheats as one class per module inside 'module(s)'/'hack(s)' packages. The verified examples are Meteor Client (systems/modules/combat/KillAura), Wurst (hacks/KillauraHack), BleachHack (module/mods/Killaura), ThunderHack (features/modules/combat/Aura) and LiquidBounce (features/module/modules/combat/killaura/ModuleKillAura). Class names alone are weak evidence."
HEUR_SOURCES = [WURST[2], METEOR[2], LB[2], BLEACH[2], THUNDER[2]]

rules = []
LB_LEGACY = [gh("CCBlueX/LiquidBounce", "legacy", "src/main/resources/mcmod.info", "LiquidBounce legacy (Forge 1.8.9) mcmod.info"),
             gh("CCBlueX/LiquidBounce", "legacy", "build.gradle", "LiquidBounce legacy build.gradle (FMLCorePlugin, MixinConfigs)")]
THUNDER_README = gh("Pan4ur/ThunderHack-Recode", "main", "README.md", "ThunderHack Recode README (lists malicious renamed copies)")
LB_COREMOD = ("FMLCorePlugin", "net.ccbluex.liquidbounce.injection.forge.MixinLoader")

rules += [
    cheat_rule("CP-HC-0001", "Wurst Client", "wurst", "net/wurstclient/", "wurst.mixins.json", WURST),
    cheat_rule("CP-HC-0002", "Meteor Client", "meteor-client", "meteordevelopment/meteorclient/", "meteor-client.mixins.json", METEOR),
    cheat_rule("CP-HC-0003", "LiquidBounce", "liquidbounce", "net/ccbluex/liquidbounce/", "liquidbounce.mixins.json", LB + LB_LEGACY, version=2,
               coremod=LB_COREMOD,
               extra_indicators=[({"id": "forge-mixins", "type": "ArchiveEntry", "value": "liquidbounce.forge.mixins.json", "strength": "Moderate",
                                   "description": "LiquidBounce legacy (Forge) mixin configuration"}, {"all": ["package", "forge-mixins"]})],
               extra_note=" Covers the Fabric client and the legacy Forge 1.8.9 client. Many forks (for example FDPClient, MinusBounce, NightX, LiquidBounce+) keep the net.ccbluex.liquidbounce package and are matched by it too."),
    cheat_rule("CP-HC-0004", "BleachHack", "bleachhack", "org/bleachhack/", "bleachhack.mixins.json", BLEACH),
    cheat_rule("CP-HC-0005", "ThunderHack", "thunderhack", "thunder/hack/", "thunderhack.mixins.json", THUNDER + [THUNDER_README], version=2,
               extra_note=" The ThunderHack README warns that renamed copies (for example Expensive, DoxWare 2.0 and Deluxe Client) are malicious; copies that keep the thunder.hack package are matched by this rule."),

    # Fabric clients and anarchy clients (verified 2026-10-11 from each repository).
    cheat_rule("CP-HC-0006", "Aoba Client", "aoba", "net/aoba/", "aoba.mixins.json",
               [gh("coltonk9043/Aoba-Client", "master", "src/main/resources/fabric.mod.json", "Aoba Client fabric.mod.json (mod id, entrypoint net.aoba.Aoba)"),
                gh("coltonk9043/Aoba-Client", "master", "src/main/resources/aoba.mixins.json", "Aoba Client aoba.mixins.json (package net.aoba.mixin)")]),
    cheat_rule("CP-HC-0008", "Jex Client", "jex", "me/dustin/jex/", "jex.mixins.json",
               [gh("DustinRepo/JexClient", "main", "src/main/resources/fabric.mod.json", "Jex Client fabric.mod.json (mod id, entrypoint me.dustin.jex.load.JexLoad)"),
                gh("DustinRepo/JexClient", "main", "src/main/resources/jex.mixins.json", "Jex Client jex.mixins.json")]),
    cheat_rule("CP-HC-0009", "AnarchyClient (6b6t)", "anarchyclient", "net/blockhost/anarchyclient/", "anarchyclient.mixins.json",
               [gh("6b6t/AnarchyClient", "main", "src/main/resources/fabric.mod.json", "AnarchyClient fabric.mod.json (mod id, entrypoint net.blockhost.anarchyclient.AnarchyClient)")],
               extra_note=" AnarchyClient is published for the 6b6t anarchy server, where its combat and movement modules are allowed; on other servers they count as cheats."),
    cheat_rule("CP-HC-0010", "Ares", "ares", "dev/tigr/ares/", "mixins.ares.json",
               [gh("AresClient/ares", "master", "ares-forge/src/main/resources/mcmod.info", "Ares mcmod.info ('Ares is a minecraft cheat client')"),
                gh("AresClient/ares", "master", "ares-forge/build.gradle", "Ares Forge build.gradle (FMLCorePlugin, MixinConfigs)"),
                gh("AresClient/ares", "master", "ares-fabric/src/main/resources/fabric.mod.json", "Ares Fabric fabric.mod.json"),
                gh("AresClient/ares", "master", "gradle.properties", "Ares gradle.properties (modGroup dev.tigr.ares)")],
               coremod=("FMLCorePlugin", "dev.tigr.ares.forge.mixin.MixinLoader"),
               extra_indicators=[({"id": "fabric-mixins", "type": "ArchiveEntry", "value": "ares.mixins.json", "strength": "Moderate", "description": "Ares Fabric mixin configuration"},
                                  {"all": ["package", "fabric-mixins"]})]),

    # Forge 1.12.2 anarchy clients: the manifest names their core-mod class, which is a second independent fingerprint.
    cheat_rule("CP-HC-0011", "KAMI Blue", "kamiblue", "org/kamiblue/client/", "mixins.kami.json",
               [gh("kami-blue/client", "master", "src/main/resources/mcmod.info", "KAMI Blue mcmod.info"),
                gh("kami-blue/client", "master", "build.gradle", "KAMI Blue build.gradle (FMLCorePlugin, MixinConfigs)")],
               coremod=("FMLCorePlugin", "org.kamiblue.client.mixin.MixinLoaderForge")),
    cheat_rule("CP-HC-0012", "Lambda (legacy, Forge 1.12.2)", "lambda", "com/lambda/client/", "mixins.lambda.json",
               [gh("lambda-client/lambda-legacy", "master", "src/main/resources/mcmod.info", "Lambda legacy mcmod.info"),
                gh("lambda-client/lambda-legacy", "master", "build.gradle", "Lambda legacy build.gradle (FMLCorePlugin com.lambda.client.LambdaCoreMod)")],
               coremod=("FMLCorePlugin", "com.lambda.client.LambdaCoreMod")),
    cheat_rule("CP-HC-0013", "Lambda (Fabric)", "lambda", "com/lambda/", "lambda.mixins.json",
               [gh("lambda-client/lambda", "master", "src/main/resources/fabric.mod.json", "Lambda fabric.mod.json (entrypoint com.lambda.Lambda, mixins ${modId}.mixins.json)"),
                gh("lambda-client/lambda", "master", "gradle.properties", "Lambda gradle.properties (modId=lambda, mavenGroup=com.lambda)")],
               package_alone="needsReview",
               extra_note=" The com.lambda package name is generic, so on its own it is only reported for review."),
    cheat_rule("CP-HC-0014", "SalHack", "salhack", "me/ionar/salhack/", "mixins.salhack.json",
               [gh("ionar2/salhack", "master", "src/main/resources/mcmod.info", "SalHack mcmod.info"),
                gh("ionar2/salhack", "master", "build.gradle", "SalHack build.gradle (FMLCorePlugin, MixinConfigs)")],
               coremod=("FMLCorePlugin", "me.ionar.salhack.mixin.MixinLoaderForge")),
    cheat_rule("CP-HC-0015", "ForgeHax", "forgehax", "com/matt/forgehax/", None,
               [gh("fr1kin/ForgeHax", "master", "src/main/resources/mcmod.info", "ForgeHax mcmod.info ('Hax 4 forge')"),
                gh("fr1kin/ForgeHax", "master", "build.gradle", "ForgeHax build.gradle (group com.matt.forgehax, FMLCorePlugin)")],
               coremod=("FMLCorePlugin", "com.matt.forgehax.asm.ForgeHaxCoreMod")),
    cheat_rule("CP-HC-0016", "3arthh4ck", "earthhack", "me/earth/earthhack/", None,
               [gh("3arthqu4ke/3arthh4ck", "main", "src/main/resources/mcmod.info", "3arthh4ck mcmod.info ('A 1.12.2 Anarchy Client')"),
                gh("3arthqu4ke/3arthh4ck", "main", "build.gradle", "3arthh4ck build.gradle (TweakClass me.earth.earthhack.tweaker.EarthhackTweaker)")],
               coremod=("TweakClass", "me.earth.earthhack.tweaker.EarthhackTweaker")),
    cheat_rule("CP-HC-0017", "Seppuku", "seppukumod", "me/rigamortis/seppuku/", None,
               [gh("seppukudevelopment/seppuku", "master", "src/main/resources/mcmod.info", "Seppuku mcmod.info ('a hacked client built on forge')"),
                gh("seppukudevelopment/seppuku", "master", "build.gradle", "Seppuku build.gradle (FMLCorePlugin)")],
               coremod=("FMLCorePlugin", "me.rigamortis.seppuku.impl.fml.core.SeppukuLoadingPlugin")),
    cheat_rule("CP-HC-0018", "GameSense", "gamesense", "com/gamesense/", "mixins.gamesense.json",
               [gh("IUDevman/gamesense-client", "master", "src/main/resources/mcmod.info", "GameSense mcmod.info ('1.12.2 Anarchy Client')"),
                gh("IUDevman/gamesense-client", "master", "build.gradle", "GameSense build.gradle (FMLCorePlugin, MixinConfigs)")],
               coremod=("FMLCorePlugin", "com.gamesense.mixin.GameSenseMixinLoader")),

    # LiquidBounce forks with their own mod id (the shared package is also matched by CP-HC-0003).
    cheat_rule("CP-HC-0019", "FDPClient (LiquidBounce fork)", "fdpclient", "net/ccbluex/liquidbounce/", "fdpclient.forge.mixins.json",
               [gh("SkidderMC/FDPClient", "main", "src/main/resources/mcmod.info", "FDPClient mcmod.info ('A free mixin-based injection hacked-client')"),
                gh("SkidderMC/FDPClient", "main", "build.gradle", "FDPClient build.gradle (FMLCorePlugin, MixinConfigs fdpclient.forge.mixins.json)")],
               coremod=LB_COREMOD),
    cheat_rule("CP-HC-0020", "MinusBounce (LiquidBounce fork)", "minusbounce", "net/ccbluex/liquidbounce/", None,
               [gh("Rylazius/MinusBounce", "main", "src/main/resources/mcmod.info", "MinusBounce mcmod.info (authors CCBlueX, MinusMC)")]),
]

# Argon is a ghost client whose fabric.mod.json reuses the mod id of the legitimate ImmediatelyFast mod as a disguise.
rules.append({
    "id": "CP-HC-0007", "version": 1, "family": "Argon (ghost client)", "category": "GhostClient", "severity": "Medium",
    "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip"],
    "indicators": [
        {"id": "package", "type": "ClassPackagePrefix", "value": "dev/lvstrng/argon/", "strength": "Strong", "description": "Classes in the Argon package (entrypoint dev.lvstrng.argon.Main)"},
        {"id": "disguise", "type": "ModId", "value": "immediatelyfast", "strength": "Moderate", "description": "Declares the mod id of the legitimate ImmediatelyFast mod"},
        {"id": "mixins", "type": "ArchiveEntry", "value": "client.mixins.json", "strength": "Weak", "description": "Argon mixin configuration (a generic name)"},
    ],
    "classification": {"knownMatch": [{"all": ["package", "disguise"]}, {"all": ["package", "mixins"]}], "highConfidenceSuspicion": [{"all": ["package"]}]},
    "recommendedAction": "Quarantine", "reputationOnMatch": "KnownCheat",
    "confidenceRationale": "Argon's source declares the mod id 'immediatelyfast' and the name 'ImmediatelyFast' in fabric.mod.json, so it appears as a performance mod in mod lists, while its code lives in dev.lvstrng.argon. The package together with the borrowed identity is a known match.",
    "falsePositiveNotes": "The real ImmediatelyFast mod uses the net.raphimc.immediatelyfast package and is not matched.",
    "limitations": "Renamed builds that move the code to another package are caught only by the impersonation check (CP-IMP-0005).",
    "sources": [gh("LvStrnggg/argon", "main", "src/main/resources/fabric.mod.json", "Argon fabric.mod.json (id 'immediatelyfast', entrypoint dev.lvstrng.argon.Main)"),
                gh("LvStrnggg/argon", "main", "src/main/resources/client.mixins.json", "Argon client.mixins.json (package dev.lvstrng.argon.mixin)"),
                gh("LvStrnggg/argon", "main", "README.md", "Argon README ('Argon Minecraft Ghost Client')")],
    "verifiedOn": D,
})

# Meteor Client add-ons: every add-on declares a "meteor" entrypoint (Meteor's own add-on template does).
METEOR_TEMPLATE = gh("MeteorDevelopment/meteor-addon-template", "master", "src/main/resources/fabric.mod.json",
                     "Meteor add-on template fabric.mod.json ('meteor' entrypoint, depends on meteor-client)")
rules.append({
    "id": "CP-ADDON-0001", "version": 1, "family": "Meteor Client add-on", "category": "HackedClient", "severity": "Medium",
    "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip"],
    "indicators": [{"id": "meteor-entrypoint", "type": "ModEntrypoint", "value": "meteor", "strength": "Strong",
                    "description": "Declares a 'meteor' entrypoint, which only Meteor Client loads"}],
    "classification": {"highConfidenceSuspicion": [{"all": ["meteor-entrypoint"]}]},
    "recommendedAction": "Quarantine", "reputationOnMatch": "Suspicious",
    "confidenceRationale": "Meteor Client add-ons register themselves through a 'meteor' entrypoint in fabric.mod.json, as shown in Meteor's official add-on template. Such a jar only works together with Meteor Client and extends it with more modules. The specific add-on rules (CP-ADDON-0002 and later) name well-known add-ons.",
    "falsePositiveNotes": "A few add-ons only add cosmetic or utility features, but all of them require Meteor Client.",
    "limitations": "Add-ons for other clients (for example RusherHack plugins) are covered by their own rules.",
    "sources": [METEOR_TEMPLATE], "verifiedOn": D,
})

def addon_rule(rid, family, modid, pkg, mixins, repo, branch, description):
    sources = [gh(repo, branch, "src/main/resources/fabric.mod.json", f"{family} fabric.mod.json ({description})")]
    if mixins:
        sources.append(gh(repo, branch, f"src/main/resources/{mixins}", f"{family} {mixins}"))
    rule = cheat_rule(rid, family, modid, pkg, mixins, sources,
                      extra_note=" It is a Meteor Client add-on, so Meteor Client itself is usually installed as well.")
    rule["indicators"].append({"id": "meteor-entrypoint", "type": "ModEntrypoint", "value": "meteor", "strength": "Moderate", "description": "Meteor add-on entrypoint"})
    rule["classification"]["knownMatch"].append({"all": ["mod-id", "meteor-entrypoint"]})
    rule["sources"].append(METEOR_TEMPLATE)
    return rule

rules += [
    addon_rule("CP-ADDON-0002", "Meteor Rejects", "meteor-rejects", "anticope/rejects/", "meteor-rejects.mixins.json", "AntiCope/meteor-rejects", "master", "entrypoint anticope.rejects.MeteorRejectsAddon"),
    addon_rule("CP-ADDON-0003", "Meteor Crash Addon", "meteor-crash-addon", "widecat/meteorcrashaddon/", "meteorcrashaddon.mixins.json", "AntiCope/meteor-crash-addon", "main", "'help you crash servers'"),
    addon_rule("CP-ADDON-0004", "Trouser-Streak", "streak-addon", "pwn/noobs/trouserstreak/", "streak.mixins.json", "etianl/Trouser-Streak", "main", "'optimized for maximum grief'"),
    addon_rule("CP-ADDON-0005", "Meteor+ (MeteorPlus)", "meteorplus", "nekiplay/meteorplus/", "meteorplus.mixins.json", "Nekiplay/MeteorPlus", "main", "'adds many blatant features'"),
    addon_rule("CP-ADDON-0006", "Numby Hack", "numbyhack", "cqb13/NumbyHack/", "NumbyHack.mixins.json", "cqb13/Numby-hack", "main", "Meteor add-on"),
    addon_rule("CP-ADDON-0007", "Meteorist", "meteorist", "zgoly/meteorist/", "meteorist.mixins.json", "Zgoly/Meteorist", "main", "Meteor add-on"),
    addon_rule("CP-ADDON-0008", "Vector Addon", "vector-addon", "cally72jhb/addon/", "vector-addon.mixins.json", "cally72jhb/vector-addon", "main", "'combat and many utility modules'"),
    addon_rule("CP-ADDON-0009", "BlackOut", "blackout", "kassuk/addon/blackout/", "blackout.mixins.json", "KassuK1/BlackOut", "main", "'Epik cheetos addon'"),
    addon_rule("CP-ADDON-0010", "Orion", "orion", "me/ghosttypes/orion/", None, "AntiCope/orion", "main", "'A combat addon for Meteor Client'"),
]

rules.append({
    "id": "CP-ADDON-0011", "version": 1, "family": "RusherHack plugin", "category": "HackedClient", "severity": "Medium",
    "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip"],
    "indicators": [{"id": "plugin-manifest", "type": "ArchiveEntry", "value": "rusherhack-plugin.json", "strength": "Strong",
                    "description": "RusherHack plugin manifest"}],
    "classification": {"highConfidenceSuspicion": [{"all": ["plugin-manifest"]}]},
    "recommendedAction": "Quarantine", "reputationOnMatch": "Suspicious",
    "confidenceRationale": "RusherHack plugins carry a rusherhack-plugin.json manifest (with Plugin-Class, Name and Minecraft-Versions), as in the official example plugin. A plugin only runs inside the RusherHack hacked client, so finding one strongly suggests RusherHack is used. RusherHack itself is closed source and is matched by name only (CP-HEUR-0005).",
    "falsePositiveNotes": "None known: the manifest name is specific to RusherHack.",
    "limitations": "The closed-source RusherHack client itself has no published indicators.",
    "sources": [gh("RusherDevelopment/example-plugin", "master", "src/main/resources/rusherhack-plugin.json", "RusherHack example plugin rusherhack-plugin.json")],
    "verifiedOn": D,
})

rules.append({
    "id": "CP-XRAY-0001", "version": 1, "family": "Advanced XRay (x-ray mod)", "category": "XRayOrEsp", "severity": "Medium",
    "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip"],
    "indicators": [{"id": "mod-id", "type": "ModId", "value": "xray", "strength": "Moderate", "description": "Mod metadata uses the Advanced XRay mod id"},
                   {"id": "package", "type": "ClassPackagePrefix", "value": "pro/mikey/xray/", "strength": "Strong", "description": "Classes in the Advanced XRay package"}],
    "classification": {"highConfidenceSuspicion": [{"all": ["mod-id", "package"]}, {"all": ["package"]}], "needsReview": [{"all": ["mod-id"]}]},
    "recommendedAction": "ManualReview", "reputationOnMatch": "Suspicious",
    "confidenceRationale": "Advanced XRay shows ores through other blocks ('An Advanced XRay mod ... with all your block finding needs'). That is fine in single-player but counts as a cheat on nearly every multiplayer server, so it is reported for your decision.",
    "falsePositiveNotes": "Allowed in single-player and on servers that permit it.", "limitations": "Other x-ray mods are covered only by the generic heuristics.",
    "sources": [gh("AdvancedXRay/XRay-Mod", "main", "fabric/src/main/resources/fabric.mod.json", "Advanced XRay fabric.mod.json (id 'xray', entrypoint pro.mikey.xray.fabric.XRayFabric)"),
                gh("AdvancedXRay/XRay-Mod", "main", "fabric/src/main/resources/xray.mixins.json", "Advanced XRay xray.mixins.json (package pro.mikey.xray.mixins)")],
    "verifiedOn": D,
})

rules.append({
    "id": "CP-HEUR-0001", "version": 1, "family": "Generic combat cheat modules", "category": "CombatAutomation", "severity": "Medium",
    "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip", ".litemod"], "heuristic": True,
    "indicators": module_indicators(COMBAT),
    "classification": {"highConfidenceSuspicion": [{"counts": [{"atLeast": 4, "of": [i for i, _ in COMBAT]}]}],
                       "needsReview": [{"counts": [{"atLeast": 2, "of": [i for i, _ in COMBAT]}]}]},
    "recommendedAction": "Quarantine", "reputationOnMatch": "Suspicious",
    "confidenceRationale": HEUR_RATIONALE + " Two distinct combat-module names are needed for review and four for a high-confidence suspicion (KillAura, aim assistance, trigger bots, auto-clickers, reach, velocity/anti-knockback, criticals, crystal aura, hitboxes).",
    "falsePositiveNotes": HEUR_FP, "limitations": "Obfuscated clients rename classes and are not found by this heuristic.", "sources": HEUR_SOURCES, "verifiedOn": D,
})
rules.append({
    "id": "CP-HEUR-0002", "version": 1, "family": "Generic movement and timer cheat modules", "category": "MovementOrTimer", "severity": "Medium",
    "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip", ".litemod"], "heuristic": True,
    "indicators": module_indicators(MOVEMENT),
    "classification": {"highConfidenceSuspicion": [{"counts": [{"atLeast": 5, "of": [i for i, _ in MOVEMENT]}]}],
                       "needsReview": [{"counts": [{"atLeast": 3, "of": [i for i, _ in MOVEMENT]}]}]},
    "recommendedAction": "Quarantine", "reputationOnMatch": "Suspicious",
    "confidenceRationale": HEUR_RATIONALE + " Three distinct movement-module names (fly, speed, timer, scaffold, no-fall, no-slow, step, spider, jesus, blink, long jump) are needed for review and five for a high-confidence suspicion.",
    "falsePositiveNotes": HEUR_FP, "limitations": "Obfuscated clients rename classes and are not found by this heuristic.", "sources": HEUR_SOURCES, "verifiedOn": D,
})
rules.append({
    "id": "CP-HEUR-0003", "version": 1, "family": "Generic X-ray and ESP cheat modules", "category": "XRayOrEsp", "severity": "Medium",
    "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip", ".litemod"], "heuristic": True,
    "indicators": module_indicators(RENDER),
    "classification": {"highConfidenceSuspicion": [{"counts": [{"atLeast": 3, "of": [i for i, _ in RENDER]}]}],
                       "needsReview": [{"counts": [{"atLeast": 2, "of": [i for i, _ in RENDER]}]}]},
    "recommendedAction": "Quarantine", "reputationOnMatch": "Suspicious",
    "confidenceRationale": HEUR_RATIONALE + " Two distinct render-cheat module names (x-ray, ESP, tracers, wallhack, chams) are needed for review and three for a high-confidence suspicion.",
    "falsePositiveNotes": HEUR_FP, "limitations": "Obfuscated clients rename classes and are not found by this heuristic.", "sources": HEUR_SOURCES, "verifiedOn": D,
})
cross = module_indicators(COMBAT, "c-") + module_indicators(MOVEMENT, "m-") + module_indicators(RENDER, "r-") + module_indicators(INVENTORY, "i-")
rules.append({
    "id": "CP-HEUR-0004", "version": 1, "family": "Generic hacked-client module layout", "category": "HackedClient", "severity": "Medium",
    "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip", ".litemod"], "heuristic": True,
    "indicators": cross,
    "classification": {
        "highConfidenceSuspicion": [{"counts": [{"atLeast": 2, "of": ["c-" + i for i, _ in COMBAT]}, {"atLeast": 2, "of": ["m-" + i for i, _ in MOVEMENT]},
                                                {"atLeast": 1, "of": ["r-" + i for i, _ in RENDER] + ["i-" + i for i, _ in INVENTORY]}]}],
        "needsReview": [{"counts": [{"atLeast": 1, "of": ["c-" + i for i, _ in COMBAT]}, {"atLeast": 2, "of": ["m-" + i for i, _ in MOVEMENT]},
                                    {"atLeast": 1, "of": ["r-" + i for i, _ in RENDER] + ["i-" + i for i, _ in INVENTORY]}]}],
    },
    "recommendedAction": "Quarantine", "reputationOnMatch": "Suspicious",
    "confidenceRationale": HEUR_RATIONALE + " This rule looks for the typical spread of a hacked client: combat, movement and render/inventory cheat modules in the same file.",
    "falsePositiveNotes": HEUR_FP, "limitations": "Obfuscated clients rename classes and are not found by this heuristic.", "sources": HEUR_SOURCES, "verifiedOn": D,
})
# Names of hacked and ghost clients. Distinctive names match on their own; names that are ordinary words only match
# when followed by "client"/"hack" (for example "future-client.jar"), to avoid flagging unrelated files.
DISTINCTIVE_NAMES = [
    "wurst", "meteor-?client", "liquidbounce", "bleachhack", "thunderhack", "aristois", "rusherhack", "konas", "salhack",
    "kami-?blue", "forgehax", "3arthh4ck", "earthhack", "seppuku", "fdpclient", "minusbounce", "novoline", "jex-?client",
    "aoba-?client", "ares-?client", "huzuni", "wolfram-?client", "vape(-?v[0-9]|-?lite)?", "drip-?lite", "doomsday-?client",
    "nursultan", "akrien", "wexside", "catlean", "doxware", "meteor-?rejects", "trouser-?streak", "liquidbounce-?plus",
]
WORD_NAMES = [
    "future", "impact", "rise", "sigma", "jello", "moon", "argon", "krypton", "prestige", "inertia", "celestial", "expensive",
    "entropy", "breeze", "drip", "mio", "pyro", "boze", "augustus", "tenacity", "exhibition", "astolfo", "raven", "lambda",
    "orion", "whiteout", "slinky", "phobos", "gamesense", "nodus", "flux", "skid",
]
NAME_PATTERN = r"(?i)(^|[^a-z0-9])(" + "|".join(DISTINCTIVE_NAMES) + r")([^a-z]|$)"
WORD_NAME_PATTERN = r"(?i)(^|[^a-z0-9])(" + "|".join(WORD_NAMES) + r")[-_ .]?(client|hack|cheat|b\+|bplus|b4|bs|xd)([^a-z]|$)"
assert len(NAME_PATTERN) <= 512 and len(WORD_NAME_PATTERN) <= 512
rules.append({
    "id": "CP-HEUR-0005", "version": 2, "family": "Known hacked-client name in file name", "category": "HackedClient", "severity": "Medium",
    "appliesTo": ["File"], "fileExtensions": [".jar", ".zip", ".exe", ".dll", ".rar", ".7z"], "heuristic": True,
    "indicators": [{"id": "name", "type": "FileNamePattern", "value": NAME_PATTERN,
                    "strength": "Weak", "description": "File name contains the name of a known hacked or ghost client"},
                   {"id": "name-word", "type": "FileNamePattern", "value": WORD_NAME_PATTERN,
                    "strength": "Weak", "description": "File name contains a client name followed by 'client' or 'hack'"}],
    "classification": {"needsReview": [{"any": ["name", "name-word"]}]},
    "recommendedAction": "ManualReview", "reputationOnMatch": "Unknown",
    "confidenceRationale": "A file name is weak evidence: anyone can name a file anything, so this alone only ever leads to 'Needs review' with a low severity. The list includes closed-source clients (for example Vape, Future, RusherHack, Konas, Aristois, Impact, Rise, Novoline) for which no file indicators have been published; for them, the name is the only available signal.",
    "falsePositiveNotes": "Unrelated files can contain these words. Ordinary words (for example 'future' or 'rise') only match when followed by 'client' or 'hack'. The file content decides; check the other evidence.",
    "limitations": "Renamed files are not found by this rule. Closed-source clients that are injected into the running game (for example Vape) may leave no file in the Minecraft folders at all.",
    "sources": [], "verifiedOn": D,
})
rules.append({
    "id": "CP-HEUR-0006", "version": 1, "family": "X-ray resource pack (name based)", "category": "XRayOrEsp", "severity": "Low",
    "appliesTo": ["Archive"], "fileExtensions": [".zip"], "heuristic": True,
    "indicators": [{"id": "name", "type": "FileNamePattern", "value": r"(?i)x[-_ ]?ray", "strength": "Weak", "description": "Archive name mentions x-ray"},
                   {"id": "pack", "type": "ArchiveEntry", "value": "pack.mcmeta", "strength": "Weak", "description": "Archive is a Minecraft resource pack"}],
    "classification": {"needsReview": [{"all": ["name", "pack"]}]},
    "recommendedAction": "ManualReview", "reputationOnMatch": "Unknown",
    "confidenceRationale": "Resource packs that make ordinary blocks transparent are commonly called x-ray packs. Only the name is checked, so this is a prompt for review, not proof.",
    "falsePositiveNotes": "Packs with x-ray in the name may be legitimate (for example x-ray themed decorations).", "limitations": "Texture contents are not analysed.",
    "sources": [], "verifiedOn": D,
})

rules.append({
    "id": "CP-AUTO-0001", "version": 1, "family": "Baritone (pathfinding/automation bot)", "category": "GameplayAutomation", "severity": "Low",
    "appliesTo": ["Archive"], "fileExtensions": [".jar"],
    "indicators": [{"id": "mod-id", "type": "ModId", "value": "baritone", "strength": "Strong", "description": "Mod metadata uses the Baritone mod id"},
                   {"id": "mixins", "type": "ArchiveEntry", "value": "mixins.baritone.json", "strength": "Moderate", "description": "Baritone mixin configuration"}],
    "classification": {"needsReview": [{"any": ["mod-id", "mixins"]}]},
    "recommendedAction": "ManualReview", "reputationOnMatch": "Unknown",
    "confidenceRationale": "Baritone is open-source automation software (LGPL). It is not malware and is allowed on some servers but forbidden on many, so it is only ever reported for review.",
    "falsePositiveNotes": "Some legitimate clients bundle Baritone for single-player use.", "limitations": "Whether Baritone is allowed depends on the server's rules.",
    "sources": [src("Baritone fabric.mod.json", GH+"cabaletta/baritone/blob/1.21.1/fabric/src/main/resources/fabric.mod.json")], "verifiedOn": D,
})

rules.append({
    "id": "CP-CFG-0001", "version": 1, "family": "Wurst Client configuration leftovers", "category": "CheatConfiguration", "severity": "Low",
    "appliesTo": ["File", "Directory"],
    "indicators": [{"id": "enabled-hacks", "type": "RelativePath", "value": "wurst/enabled-hacks.json", "strength": "Strong", "description": "Wurst list of enabled hacks"},
                   {"id": "keybinds", "type": "RelativePath", "value": "wurst/keybinds.json", "strength": "Moderate", "description": "Wurst keybind configuration"},
                   {"id": "folder", "type": "DirectoryName", "value": "wurst", "atInstallationRoot": True, "strength": "Moderate", "description": "Wurst configuration folder"}],
    "classification": {"knownMatch": [{"all": ["enabled-hacks"]}], "needsReview": [{"any": ["keybinds", "folder"]}]},
    "recommendedAction": "Quarantine", "reputationOnMatch": "Suspicious",
    "confidenceRationale": "WurstClient.java creates a 'wurst' folder in the game directory containing enabled-hacks.json, keybinds.json and other settings. These files show Wurst was installed at some point.",
    "falsePositiveNotes": "A folder named 'wurst' could be created by something else; only enabled-hacks.json is treated as a known match.",
    "limitations": "Configuration leftovers do not show when, or whether, the client was used.",
    "sources": [src("Wurst7 WurstClient.java (config folder and files)", GH+"Wurst-Imperium/Wurst7/blob/master/src/main/java/net/wurstclient/WurstClient.java")], "verifiedOn": D,
})
rules.append({
    "id": "CP-CFG-0002", "version": 1, "family": "Meteor Client data folder", "category": "CheatConfiguration", "severity": "Low",
    "appliesTo": ["Directory"],
    "indicators": [{"id": "folder", "type": "DirectoryName", "value": "meteor-client", "atInstallationRoot": True, "strength": "Moderate", "description": "Meteor Client data folder"}],
    "classification": {"needsReview": [{"all": ["folder"]}]},
    "recommendedAction": "ManualReview", "reputationOnMatch": "Suspicious",
    "confidenceRationale": "MeteorClient.java stores its data in a folder named after its mod id ('meteor-client') in the game directory.",
    "falsePositiveNotes": "Any program could create a folder with this name.", "limitations": "Leftover folders do not show when, or whether, the client was used.",
    "sources": [src("Meteor Client MeteorClient.java (FOLDER)", GH+"MeteorDevelopment/meteor-client/blob/master/src/main/java/meteordevelopment/meteorclient/MeteorClient.java")], "verifiedOn": D,
})
rules.append({
    "id": "CP-CFG-0003", "version": 1, "family": "LiquidBounce data folder", "category": "CheatConfiguration", "severity": "Low",
    "appliesTo": ["Directory"],
    "indicators": [{"id": "folder", "type": "DirectoryName", "value": "LiquidBounce", "atInstallationRoot": True, "strength": "Moderate", "description": "LiquidBounce configuration folder"}],
    "classification": {"needsReview": [{"all": ["folder"]}]},
    "recommendedAction": "ManualReview", "reputationOnMatch": "Suspicious",
    "confidenceRationale": "LiquidBounce's ConfigSystem creates a folder named CLIENT_NAME ('LiquidBounce') in the game directory.",
    "falsePositiveNotes": "Any program could create a folder with this name.", "limitations": "Leftover folders do not show when, or whether, the client was used.",
    "sources": [src("LiquidBounce ConfigSystem.kt (rootFolder)", GH+"CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/config/ConfigSystem.kt"),
                src("LiquidBounce.kt (CLIENT_NAME)", GH+"CCBlueX/LiquidBounce/blob/nextgen/src/main/kotlin/net/ccbluex/liquidbounce/LiquidBounce.kt")], "verifiedOn": D,
})

def ins(op, **kw):
    d = {"op": op}; d.update(kw); return d
S = "java/lang/String"
SIG1 = [ins("NEW", type=S), ins("INVOKESPECIAL", owner=S, name="<init>", desc="([B)V"), ins("NEW", type=S), ins("INVOKESPECIAL", owner=S, name="<init>", desc="([B)V"),
        ins("INVOKESTATIC", owner="java/lang/Class", name="forName", desc="(Ljava/lang/String;)Ljava/lang/Class;"),
        ins("INVOKEVIRTUAL", owner="java/lang/Class", name="getConstructor", desc="([Ljava/lang/Class;)Ljava/lang/reflect/Constructor;"),
        ins("INVOKESPECIAL", owner=S, name="<init>", desc="([B)V"), ins("INVOKESPECIAL", owner=S, name="<init>", desc="([B)V"), ins("INVOKESPECIAL", owner=S, name="<init>", desc="([B)V"),
        ins("INVOKESPECIAL", owner="java/net/URL", name="<init>", desc="(Ljava/lang/String;Ljava/lang/String;ILjava/lang/String;)V"),
        ins("INVOKEVIRTUAL", owner="java/lang/reflect/Constructor", name="newInstance", desc="([Ljava/lang/Object;)Ljava/lang/Object;"),
        ins("INVOKESTATIC", owner="java/lang/Class", name="forName", desc="(Ljava/lang/String;ZLjava/lang/ClassLoader;)Ljava/lang/Class;"),
        ins("INVOKESPECIAL", owner=S, name="<init>", desc="([B)V"),
        ins("INVOKEVIRTUAL", owner="java/lang/Class", name="getMethod", desc="(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;"),
        ins("INVOKEVIRTUAL", owner="java/lang/reflect/Method", name="invoke", desc="(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;")]
SIG2 = [ins("INVOKESTATIC", owner="java/lang/Runtime", name="getRuntime", desc="()Ljava/lang/Runtime;"),
        ins("INVOKESTATIC", owner="java/util/Base64", name="getDecoder", desc="()Ljava/util/Base64$Decoder;"),
        ins("INVOKEVIRTUAL", owner=S, name="concat", desc="(Ljava/lang/String;)Ljava/lang/String;"),
        ins("INVOKEVIRTUAL", owner="java/util/Base64$Decoder", name="decode", desc="(Ljava/lang/String;)[B"),
        ins("INVOKESPECIAL", owner=S, name="<init>", desc="([B)V"),
        ins("INVOKEVIRTUAL", owner="java/io/File", name="getPath", desc="()Ljava/lang/String;"),
        ins("INVOKEVIRTUAL", owner="java/lang/Runtime", name="exec", desc="([Ljava/lang/String;)Ljava/lang/Process;")]
ip = "85.217.144.130"
SIG3 = []
for idx, ch in enumerate(ip):
    if idx > 0:
        SIG3.append(ins("DUP"))
        SIG3.append(ins("ICONST_%d" % idx) if idx <= 5 else ins("BIPUSH", operand=idx))
    SIG3.append(ins("BIPUSH", operand=ord(ch)))
    if idx < len(ip) - 1:
        SIG3.append(ins("BASTORE"))
rules.append({
    "id": "CP-MAL-0001", "version": 1, "family": "fractureiser stage 0 (infected mod or plugin)", "category": "Malware", "severity": "Critical",
    "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip", ".litemod"],
    "indicators": [
        {"id": "sig1", "type": "BytecodeSignature", "strength": "Definitive", "description": "Stage 0 loader: reflective URLClassLoader download-and-run sequence",
         "bytecode": {"mode": "OrderedOpcodeFilter", "instructions": SIG1}},
        {"id": "sig2", "type": "BytecodeSignature", "strength": "Strong", "description": "Stage 0 variant: Runtime.exec of a Base64-decoded command",
         "bytecode": {"mode": "OrderedOpcodeFilterAnyStart", "instructions": SIG2}},
        {"id": "sig3", "type": "BytecodeSignature", "strength": "Strong", "description": "Byte array spelling the original stage 0 command-and-control address",
         "bytecode": {"mode": "Contiguous", "instructions": SIG3}},
    ],
    "classification": {"knownMatch": [{"all": ["sig1"]}], "highConfidenceSuspicion": [{"any": ["sig2", "sig3"]}]},
    "recommendedAction": "QuarantineAndCheckSystem", "reputationOnMatch": "KnownMalicious",
    "confidenceRationale": "Instruction sequences published by the fractureiser investigators in nekodetector. Its author describes the first signature as a definite detection and the other two as near-certain and likely detections; they are matched statically without running any code.",
    "falsePositiveNotes": "The investigation notes that some early stage 0 scanners produced false positives on popular mods; these signatures are the later, specific ones. The third signature uses strict contiguous matching, which is at least as specific as nekodetector's.",
    "limitations": "Only the documented stage 0 variants are recognised. If stage 0 was found, later stages may have run: check the system-artifact findings and run a full antivirus scan.",
    "sources": [NEKO, FR_TECH, FR_USERS], "verifiedOn": D,
})
rules.append({
    "id": "CP-MAL-0002", "version": 1, "family": "fractureiser stage 2 (lib.jar / libWebGL64.jar)", "category": "Malware", "severity": "Critical",
    "appliesTo": ["File"],
    "indicators": [{"id": "sha1-a", "type": "Sha1", "value": "52d08736543a240b0cbbbf2da03691ae525bb119", "strength": "Definitive", "description": "Published stage 2 SHA-1"},
                   {"id": "sha1-b", "type": "Sha1", "value": "6ec85c8112c25abe4a71998eb32480d266408863", "strength": "Definitive", "description": "Published stage 2 SHA-1 (earlier sample)"}],
    "classification": {"knownMatch": [{"any": ["sha1-a", "sha1-b"]}]},
    "recommendedAction": "QuarantineAndCheckSystem", "reputationOnMatch": "KnownMalicious",
    "confidenceRationale": "Exact file hashes published in the fractureiser technical analysis.",
    "falsePositiveNotes": "A hash match is exact; false positives are not expected.", "limitations": "Other builds of stage 2 have different hashes.",
    "sources": [FR_TECH], "verifiedOn": D,
})
rules.append({
    "id": "CP-MAL-0003", "version": 1, "family": "fractureiser stage 2 persistence folder", "category": "Malware", "severity": "Critical",
    "appliesTo": ["Directory"], "platforms": ["windows"],
    "indicators": [{"id": "local", "type": "KnownLocation", "value": "%LOCALAPPDATA%\\Microsoft Edge", "expect": "Directory", "strength": "Strong",
                    "description": "Folder named 'Microsoft Edge' (with a space) in Local AppData; the real Edge uses 'Microsoft\\Edge'"},
                   {"id": "roaming", "type": "KnownLocation", "value": "%APPDATA%\\Microsoft Edge", "expect": "Directory", "strength": "Strong",
                    "description": "Folder named 'Microsoft Edge' (with a space) in Roaming AppData, as checked by nekodetector"}],
    "classification": {"highConfidenceSuspicion": [{"any": ["local", "roaming"]}]},
    "recommendedAction": "QuarantineAndCheckSystem", "reputationOnMatch": "KnownMalicious",
    "confidenceRationale": "The fractureiser user guide states that a 'Microsoft Edge' folder (with a space) in %LOCALAPPDATA% means stage 2 ran. The folder name alone is reported as a high-confidence suspicion; its contents are checked by separate rules.",
    "falsePositiveNotes": "Legitimate Edge data lives in 'Microsoft\\Edge' or 'MicrosoftEdge' (no space). Another program could, in theory, create this name.",
    "limitations": "If stage 2 ran, stage 3 may have stolen credentials. Change passwords from a clean device and run a full antivirus scan.",
    "sources": [FR_USERS, NEKO], "verifiedOn": D,
})
rules.append({
    "id": "CP-MAL-0004", "version": 1, "family": "fractureiser stage 2/3 files", "category": "Malware", "severity": "Critical",
    "appliesTo": ["File"], "platforms": ["windows"],
    "indicators": [{"id": "webgl", "type": "KnownLocation", "value": "%LOCALAPPDATA%\\Microsoft Edge\\libWebGL64.jar", "expect": "File", "strength": "Strong", "description": "Stage 2 file name on Windows"},
                   {"id": "webgl-roaming", "type": "KnownLocation", "value": "%APPDATA%\\Microsoft Edge\\libWebGL64.jar", "expect": "File", "strength": "Strong", "description": "Stage 2 file name on Windows"},
                   {"id": "libdll", "type": "KnownLocation", "value": "%LOCALAPPDATA%\\Microsoft Edge\\lib.dll", "expect": "File", "strength": "Moderate", "description": "File listed by nekodetector"},
                   {"id": "ref", "type": "KnownLocation", "value": "%LOCALAPPDATA%\\Microsoft Edge\\.ref", "expect": "File", "strength": "Moderate", "description": "Stage 1/2 infection-source identifier file"},
                   {"id": "client", "type": "KnownLocation", "value": "%LOCALAPPDATA%\\Microsoft Edge\\client.jar", "expect": "File", "strength": "Strong", "description": "Stage 3 file downloaded by stage 2"}],
    "classification": {"knownMatch": [{"any": ["webgl", "webgl-roaming"]}], "highConfidenceSuspicion": [{"any": ["libdll", "ref", "client"]}]},
    "recommendedAction": "QuarantineAndCheckSystem", "reputationOnMatch": "KnownMalicious",
    "confidenceRationale": "File names and locations documented in the fractureiser technical analysis (stage 1 downloads libWebGL64.jar, stage 2 reads .ref and writes client.jar) and in nekodetector's stage 2 check.",
    "falsePositiveNotes": "These names are only meaningful inside the disguised 'Microsoft Edge' folder.",
    "limitations": "Stage 3 can steal browser, Discord and Minecraft credentials. Change passwords from a clean device and run a full antivirus scan.",
    "sources": [FR_TECH, FR_USERS, NEKO], "verifiedOn": D,
})
rules.append({
    "id": "CP-MAL-0005", "version": 1, "family": "fractureiser stage 3 client (NekoClient)", "category": "Malware", "severity": "Critical",
    "appliesTo": ["Archive"], "fileExtensions": [".jar"],
    "indicators": [{"id": "nekoclient", "type": "ClassPackagePrefix", "value": "dev/neko/nekoclient/", "strength": "Definitive", "description": "Stage 3 package dev.neko.nekoclient"},
                   {"id": "neko", "type": "ClassPackagePrefix", "value": "dev/neko/", "strength": "Strong", "description": "Package root used by all fractureiser stage 3 classes"}],
    "classification": {"knownMatch": [{"all": ["nekoclient"]}], "highConfidenceSuspicion": [{"all": ["neko"]}]},
    "recommendedAction": "QuarantineAndCheckSystem", "reputationOnMatch": "KnownMalicious",
    "confidenceRationale": "The technical analysis documents stage 3 classes under dev/neko/nekoclient (for example dev.neko.nekoclient.Client).",
    "falsePositiveNotes": "No legitimate Minecraft software is known to use the dev.neko package.", "limitations": "Obfuscated variants may use other package names.",
    "sources": [FR_TECH], "verifiedOn": D,
})
rules.append({
    "id": "CP-MAL-0006", "version": 1, "family": "fractureiser stage 3b persistence", "category": "Malware", "severity": "Critical",
    "appliesTo": ["File", "Directory"], "platforms": ["windows"],
    "indicators": [{"id": "vm-core", "type": "KnownLocation", "value": "%USERPROFILE%\\AppData\\LocalLow\\Microsoft\\Internet Explorer\\DOMStore\\microsoft-vm-core", "expect": "Any", "strength": "Strong", "description": "Stage 3b persistence file"},
                   {"id": "task", "type": "KnownLocation", "value": "%WINDIR%\\System32\\Tasks\\MicrosoftEdgeUpdateTaskMachineVM", "expect": "File", "strength": "Strong", "description": "Stage 3b scheduled task"}],
    "classification": {"highConfidenceSuspicion": [{"any": ["vm-core", "task"]}]},
    "recommendedAction": "QuarantineAndCheckSystem", "reputationOnMatch": "KnownMalicious",
    "confidenceRationale": "Persistence locations documented for the stage 3b replacement payload in the fractureiser technical analysis.",
    "falsePositiveNotes": "The task name imitates Microsoft Edge update tasks; legitimate Edge tasks are named MicrosoftEdgeUpdateTaskMachineCore/UA, without 'VM'.",
    "limitations": "Scheduled tasks live in a protected Windows folder and are never modified by this application. Remove the task with Task Scheduler (taskschd.msc) or your antivirus.",
    "sources": [FR_TECH], "verifiedOn": D,
})
rules.append({
    "id": "CP-MAL-0007", "version": 1, "family": "fractureiser startup persistence", "category": "Malware", "severity": "Critical",
    "appliesTo": ["StartupEntry", "File"], "platforms": ["windows"],
    "indicators": [{"id": "run-webgl", "type": "StartupCommandPattern", "value": r"(?i)libWebGL64\.jar", "strength": "Strong", "description": "Startup entry launches the stage 2 file"},
                   {"id": "run-folder", "type": "StartupCommandPattern", "value": r"(?i)\\AppData\\(Local|Roaming)\\Microsoft Edge\\", "strength": "Strong", "description": "Startup entry runs a program from the disguised 'Microsoft Edge' folder"},
                   {"id": "startup-webgl", "type": "FileName", "value": "libWebGL64.jar", "locationTemplate": "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup", "strength": "Strong", "description": "Stage 2 file in the Startup folder"},
                   {"id": "startup-ref", "type": "FileName", "value": ".ref", "locationTemplate": "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup", "strength": "Weak", "description": "File name listed by nekodetector"},
                   {"id": "startup-client", "type": "FileName", "value": "client.jar", "locationTemplate": "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup", "strength": "Weak", "description": "File name listed by nekodetector"},
                   {"id": "startup-libdll", "type": "FileName", "value": "lib.dll", "locationTemplate": "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup", "strength": "Weak", "description": "File name listed by nekodetector"},
                   {"id": "startup-runbat", "type": "FileName", "value": "run.bat", "locationTemplate": "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup", "strength": "Weak", "description": "File name listed by nekodetector"}],
    "classification": {"highConfidenceSuspicion": [{"any": ["run-webgl", "run-folder", "startup-webgl"]}],
                       "needsReview": [{"any": ["startup-ref", "startup-client", "startup-libdll", "startup-runbat"]}]},
    "recommendedAction": "QuarantineAndCheckSystem", "reputationOnMatch": "KnownMalicious",
    "confidenceRationale": "Stage 1 adds stage 2 to HKCU\\...\\Run or, failing that, the Startup folder (fractureiser technical analysis). nekodetector lists the file names it checks in the Startup folder; generic names such as run.bat are only reported for review.",
    "falsePositiveNotes": "Generic names like run.bat or client.jar can belong to legitimate programs.",
    "limitations": "Registry startup entries are reported but never edited by this application. Remove them with Task Manager (Startup apps) or your antivirus after confirming.",
    "sources": [FR_TECH, NEKO], "verifiedOn": D,
})

def legit(rid, family, modid, packages, sources, version=1):
    inds = [{"id": "mod-id", "type": "ModId", "value": modid, "strength": "Strong", "description": f"{family} mod id"}]
    cond = [{"all": ["mod-id"]}]
    if packages:
        for index, pkg in enumerate(packages):
            inds.append({"id": "package" if index == 0 else f"package-{index + 1}", "type": "ClassPackagePrefix", "value": pkg, "strength": "Strong",
                         "description": f"{family} package" + ("" if index == 0 else " (earlier versions)")})
        cond = [{"all": ["mod-id"], "any": [i["id"] for i in inds[1:]]}]
    return {"id": rid, "version": version, "family": family, "category": "LegitimateSoftware", "severity": "None",
            "appliesTo": ["Archive"], "fileExtensions": [".jar"], "indicators": inds,
            "classification": {"likelyLegitimate": cond}, "recommendedAction": "NoAction", "reputationOnMatch": "KnownLegitimate",
            "confidenceRationale": f"Identifiers taken from the official {family} source repository. Identity metadata can be copied, so this is supporting evidence and never overrides a specific detection rule.",
            "falsePositiveNotes": "A malicious file could imitate these identifiers; specific detection rules still apply.",
            "limitations": "Legitimacy evidence is not a guarantee.", "sources": sources, "verifiedOn": D}

# Popular mods with every package name their official builds have used. A jar that claims one of these mod ids
# without any of the packages is impersonating the mod (CP-IMP rules below); Argon, for example, poses as ImmediatelyFast.
PROTECTED_MODS = [
    ("CP-LEGIT-0001", "CP-IMP-0001", "Sodium", "sodium", ["net/caffeinemc/mods/sodium/", "me/jellysquid/mods/sodium/"],
     [src("Sodium fabric.mod.json", GH+"CaffeineMC/sodium/blob/dev/fabric/src/main/resources/fabric.mod.json"),
      gh("CaffeineMC/sodium", "1.20.1/stable", "src/main/resources/fabric.mod.json", "Sodium 1.20.1 fabric.mod.json (entrypoint me.jellysquid.mods.sodium.client.SodiumClientMod)")]),
    ("CP-LEGIT-0002", "CP-IMP-0002", "Iris Shaders", "iris", ["net/irisshaders/iris/", "net/coderbot/iris/"],
     [src("Iris fabric.mod.json", GH+"IrisShaders/Iris/blob/1.21.4/fabric/src/main/resources/fabric.mod.json"),
      gh("IrisShaders/Iris", "1.18.2", "src/main/resources/fabric.mod.json", "Iris 1.18.2 fabric.mod.json (net.coderbot.iris)")]),
    ("CP-LEGIT-0003", "CP-IMP-0003", "Lithium", "lithium", ["net/caffeinemc/mods/lithium/", "me/jellysquid/mods/lithium/"],
     [src("Lithium fabric.mod.json", GH+"CaffeineMC/lithium/blob/develop/fabric/src/main/resources/fabric.mod.json"),
      gh("CaffeineMC/lithium", "1.20.1", "src/main/resources/fabric.mod.json", "Lithium 1.20.1 fabric.mod.json (entrypoint me.jellysquid.mods.lithium.common.LithiumMod)")]),
    ("CP-LEGIT-0004", "CP-IMP-0004", "Mod Menu", "modmenu", ["com/terraformersmc/modmenu/", "io/github/prospector/modmenu/"],
     [src("Mod Menu fabric.mod.json", GH+"TerraformersMC/ModMenu/blob/1.21/src/main/resources/fabric.mod.json"),
      gh("TerraformersMC/ModMenu", "1.15", "src/main/resources/fabric.mod.json", "Mod Menu 1.15 fabric.mod.json (io.github.prospector.modmenu)")]),
    ("CP-LEGIT-0007", "CP-IMP-0005", "ImmediatelyFast", "immediatelyfast", ["net/raphimc/immediatelyfast/"],
     [gh("RaphiMC/ImmediatelyFast", "master", "fabric/src/main/resources/fabric.mod.json", "ImmediatelyFast fabric.mod.json"),
      gh("RaphiMC/ImmediatelyFast", "master", "common/src/main/resources/immediatelyfast-common.mixins.json", "ImmediatelyFast mixins (package net.raphimc.immediatelyfast.injection.mixins)")]),
]

rules += [legit(legit_id, family, modid, packages, sources, version=2 if legit_id != "CP-LEGIT-0007" else 1)
          for legit_id, _, family, modid, packages, sources in PROTECTED_MODS]
rules += [
    legit("CP-LEGIT-0005", "Fabric Loader", "fabricloader", None, [src("Fabric Loader fabric.mod.json", GH+"FabricMC/fabric-loader/blob/master/src/main/resources/fabric.mod.json")]),
    legit("CP-LEGIT-0006", "Fabric API", "fabric-api", None, [src("Fabric API fabric.mod.json", GH+"FabricMC/fabric/blob/1.21.1/src/main/resources/fabric.mod.json")]),
]

for _, imp_id, family, modid, packages, sources in PROTECTED_MODS:
    package_ids = ["package" if i == 0 else f"package-{i + 1}" for i in range(len(packages))]
    rules.append({
        "id": imp_id, "version": 1, "family": f"Impersonation of {family}", "category": "GhostClient", "severity": "Medium",
        "appliesTo": ["Archive"], "fileExtensions": [".jar", ".zip"], "heuristic": True,
        "indicators": [{"id": "mod-id", "type": "ModId", "value": modid, "strength": "Moderate", "description": f"Claims to be {family} (mod id '{modid}')"}] +
                      [{"id": pid, "type": "ClassPackagePrefix", "value": pkg, "strength": "Strong", "description": f"Real {family} package"}
                       for pid, pkg in zip(package_ids, packages)],
        "classification": {"highConfidenceSuspicion": [{"all": ["mod-id"], "none": package_ids}]},
        "recommendedAction": "Quarantine", "reputationOnMatch": "Suspicious",
        "confidenceRationale": f"The jar declares {family}'s mod id but contains none of the packages that every official {family} build uses ({', '.join(p.rstrip('/').replace('/', '.') for p in packages)}). Cheat clients hide this way so they look like a harmless performance mod in mod lists; Argon, for example, poses as ImmediatelyFast.",
        "falsePositiveNotes": f"An unofficial port or fork that reuses the '{modid}' mod id with its own packages would also match. Missing packages are only counted when the jar could be read completely.",
        "limitations": "Only impersonation of the mods listed in the rule database is checked.",
        "sources": sources, "verifiedOn": D,
    })

OPENJDK_LAUNCHER = gh("openjdk/jdk", "master", "src/java.base/share/classes/sun/launcher/resources/launcher.properties",
                      "OpenJDK launcher help (-javaagent, -agentpath, -agentlib, -Xbootclasspath/a)")
rules.append({
    "id": "CP-LOAD-0001", "version": 1, "family": "Code loaded through JVM options (Java agent)", "category": "InjectedModule", "severity": "Medium",
    "appliesTo": ["StartupEntry"],
    "indicators": [{"id": "agent", "type": "StartupCommandPattern", "value": r"(?i)(^|[\s\"'])-(javaagent|agentpath|agentlib)[:=]", "strength": "Moderate",
                    "description": "JVM option that loads an agent into the game"},
                   {"id": "bootclasspath", "type": "StartupCommandPattern", "value": r"(?i)(^|[\s\"'])-Xbootclasspath/[ap]:", "strength": "Moderate",
                    "description": "JVM option that adds classes to the boot class path"}],
    "classification": {"needsReview": [{"any": ["agent", "bootclasspath"]}]},
    "recommendedAction": "ManualReview", "reputationOnMatch": "Unknown",
    "confidenceRationale": "A Java agent (-javaagent, -agentpath, -agentlib) or a boot class path addition runs extra code inside Minecraft without being in the mods folder. Injected cheats use this, so every such option in launcher settings or in JAVA_TOOL_OPTIONS, _JAVA_OPTIONS or JDK_JAVA_OPTIONS (which every Java program reads) is shown for review, and the file it loads is scanned separately.",
    "falsePositiveNotes": "Some legitimate tools use agents too, for example authentication helpers for alternative account systems (authlib-injector), profilers and debuggers.",
    "limitations": "Agents attached to an already running game, and DLLs injected by other programs, leave no launch option to find.",
    "sources": [OPENJDK_LAUNCHER,
                gh("openjdk/jdk8u", "master", "jdk/src/share/classes/sun/launcher/resources/launcher.properties", "OpenJDK 8 launcher help (-Xbootclasspath/p)"),
                gh("openjdk/jdk", "master", "src/hotspot/share/runtime/arguments.cpp", "OpenJDK HotSpot arguments.cpp (reads JAVA_TOOL_OPTIONS and _JAVA_OPTIONS)"),
                gh("openjdk/jdk", "master", "src/java.base/share/native/libjli/args.c", "OpenJDK launcher args.c (reads JDK_JAVA_OPTIONS)")],
    "verifiedOn": D,
})

rules.append({
    "id": "CP-TEST-0001", "version": 1, "family": "Minecraft Cleaner Pro harmless test file", "category": "TestSignature", "severity": "Informational",
    "appliesTo": ["File"],
    "indicators": [{"id": "sha256", "type": "Sha256", "value": "6fab04ffb2267b6330c4551365755c5dbb072ba7bc0b98d14fde7dc6d27cacae", "strength": "Definitive", "description": "Hash of the harmless test file"},
                   {"id": "name", "type": "FileName", "value": "cleanerpro-harmless-test.txt", "strength": "Weak", "description": "Name of the harmless test file"}],
    "classification": {"knownMatch": [{"all": ["sha256"]}], "needsReview": [{"all": ["name"]}]},
    "recommendedAction": "Quarantine", "reputationOnMatch": "Unknown",
    "confidenceRationale": "Exact SHA-256 of the harmless test file created by 'Run detection self-test' (see docs/DETECTION.md). It contains only text and lets you verify detection, quarantine and restore safely.",
    "falsePositiveNotes": "None: the file is harmless by design.", "limitations": "Test signature only.", "sources": [], "verifiedOn": D,
})

rules.sort(key=lambda r: r["id"])
doc = {"formatVersion": 1, "databaseVersion": 2026101102, "displayVersion": "2026.10.11.2", "publishedAt": "2026-10-11T00:00:00Z", "expiresAt": None,
       "description": "Bundled detection rules for Minecraft Cleaner Pro Ultimate. Every non-heuristic rule cites the public source its indicators were verified against on the date shown. No hashes or indicators were invented. Generated by rules/build_rules.py.",
       "rules": rules}
import sys
open(sys.argv[1], "w").write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
print(len(rules), "rules")

# Optional: rewrite the rule table in docs/DETECTION.md from the same data, so the documentation cannot drift.
if len(sys.argv) > 3 and sys.argv[2] == "--doc":
    def strongest(rule):
        levels = rule["classification"]
        for key, label in (("knownMatch", "Known match"), ("highConfidenceSuspicion", "High-confidence"), ("needsReview", "Needs review"), ("likelyLegitimate", "Likely legitimate")):
            if levels.get(key):
                return label
        return "—"

    lines = [f"## Bundled database {doc['displayVersion']}", "",
             f"{len(rules)} rules. Generated from `rules/build_rules.py`; the JSON is the authoritative copy.", "",
             "| Rule | Family | Category | Severity | Strongest result | Indicator types | Platforms | Sources (retrieved 2026-10-11) |",
             "|---|---|---|---|---|---|---|---|"]
    for rule in rules:
        types = ", ".join(sorted({i["type"] for i in rule["indicators"]}))
        sources = "; ".join(f"[{s['title']}]({s['url']})" for s in rule["sources"]) or (
            "n/a (test signature)" if rule["category"] == "TestSignature" else "heuristic — rationale in rule")
        lines.append(f"| `{rule['id']}` | {rule['family']} | {rule['category']} | {rule['severity']} | {strongest(rule)} | {types} | "
                     f"{', '.join(rule.get('platforms') or ['all'])} | {sources} |")
    path = sys.argv[3]
    text = open(path, encoding="utf-8").read()
    start = text.index("## Bundled database")
    end = text.index("### Indicator verification notes")
    text = text[:start] + "\n".join(lines) + "\n\n" + text[end:]
    open(path, "w", encoding="utf-8").write(text)
    print("updated", path)
