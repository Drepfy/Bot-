"""Combine Diamond SMP with another resource pack into one zip, for PERSONAL use.

    python merge_packs.py path/to/OtherPack.zip            # uses the full Diamond SMP zip
    python merge_packs.py path/to/OtherPack.zip --lite     # uses the Lite zip
    python merge_packs.py OtherPack.zip --vanilla armor potions --light-boost --sky-shader

--vanilla drops the other pack's armor and/or potion files so those show the
plain vanilla look; --light-boost adds the Diamond SMP Light Boost shader;
--sky-shader adds the live Shader Sky (black hole + real stars without mods;
--sky-shader lite for the lighter version).

Where both packs contain the same file (sun, End sky, title logo, pack icon)
Diamond SMP wins; everything else (blocks, items, GUI, particles, shaders...)
comes from the other pack. The other pack's README/LICENSE files are kept.

The result goes to diamond-smp-pack/personal/, which is git-ignored on purpose:
most packs only allow private modifications, so don't upload or share the
merged zip without the other pack author's permission.

Tip: you get the same result in game without merging at all by enabling both
packs in Options > Resource Packs, with Diamond SMP above the other pack.
"""

import argparse
import json
import re
import zipfile
from pathlib import Path

import light_boost
import shader_sky

ROOT = Path(__file__).resolve().parent.parent
SKIP = ("__MACOSX/", ".DS_Store", "Thumbs.db")
LEGACY_LIMIT = 65  # resource pack formats below this need pack_format/supported_formats

# Files that make armor / potions look different from vanilla (any version layout).
_ARMOR_PIECE = r"(leather|chainmail|iron|golden|diamond|netherite|copper)_(helmet|chestplate|leggings|boots)"
VANILLA_GROUPS = {
    "armor": [
        rf"^assets/minecraft/textures/item/({_ARMOR_PIECE}|turtle_helmet)(_overlay)?\.png$",
        rf"^assets/minecraft/(items|models/item)/({_ARMOR_PIECE}|turtle_helmet)\.json$",
        r"^assets/minecraft/textures/entity/equipment/humanoid(_leggings)?/",
        r"^assets/minecraft/textures/models/armor/",                    # worn armor before 1.21.2
        r"^assets/minecraft/equipment/",
        r"^assets/minecraft/textures/misc/enchanted_glint_armor\.png(\.mcmeta)?$",
        r"^assets/minecraft/textures/(trims|palettes/trim)",             # armor trim colours
    ],
    "potions": [
        r"^assets/minecraft/textures/item/(potion|splash_potion|lingering_potion|potion_overlay"
        r"|tipped_arrow_base|tipped_arrow_head)\.png$",
        r"^assets/minecraft/(items|models/item)/(potion|splash_potion|lingering_potion|tipped_arrow)\.json$",
        r"^assets/minecraft/textures/(gui/sprites/)?mob_effect/",
        r"^assets/minecraft/textures/gui/sprites/(container/inventory|hud)/effect_background",
        r"^assets/minecraft/textures/particle/(effect|spell|glitter)_\d+\.png$",
        r"^assets/minecraft/particles/(effect|entity_effect|instant_effect)\.json$",
    ],
}


def as_version(v):
    """pack.mcmeta version (int, [major, minor] or a sloppy float like 97.1) -> (major, minor)."""
    if isinstance(v, list):
        return (int(v[0]), int(v[1]) if len(v) > 1 else 0)
    if isinstance(v, float):
        major, _, minor = repr(v).partition(".")
        return (int(major), int(minor or 0))
    return (int(v), 0)


def pack_range(meta):
    pack = meta.get("pack", {})
    if "min_format" in pack and "max_format" in pack:
        return as_version(pack["min_format"]), as_version(pack["max_format"])
    sf = pack.get("supported_formats")
    if isinstance(sf, dict):
        return (int(sf["min_inclusive"]), 0), (int(sf["max_inclusive"]), 0)
    if isinstance(sf, list) and len(sf) == 2:
        return (int(sf[0]), 0), (int(sf[1]), 0)
    fmt = (int(pack.get("pack_format", 15)), 0)
    return fmt, fmt


def to_json_version(v):
    return v[0] if v[1] == 0 else [v[0], v[1]]


def plain_description(meta, fallback):
    desc = meta.get("pack", {}).get("description", "")
    if isinstance(desc, str) and desc.strip():
        return re.sub("§.", "", desc).strip().splitlines()[0]
    return fallback


def read_zip(path):
    files = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/").lstrip("/")
            if info.is_dir() or any(s in name for s in SKIP) or ".." in name.split("/"):
                continue
            files[name] = z.read(info)
    # Some zips wrap everything in one top-level folder; unwrap it.
    if "pack.mcmeta" not in files:
        roots = {n.split("/", 1)[0] for n in files}
        if len(roots) == 1:
            root = roots.pop() + "/"
            files = {n[len(root):]: d for n, d in files.items() if n.startswith(root)}
    if "pack.mcmeta" not in files:
        raise SystemExit(f"{path} doesn't look like a resource pack (no pack.mcmeta)")
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("other", type=Path, help="the other resource pack (.zip)")
    ap.add_argument("--lite", action="store_true", help="merge the Lite version of Diamond SMP")
    ap.add_argument("--name", help="display name of the other pack (default: from its pack.mcmeta)")
    ap.add_argument("--out", type=Path, help="output zip (default: diamond-smp-pack/personal/...)")
    ap.add_argument("--vanilla", nargs="+", choices=sorted(VANILLA_GROUPS), default=[],
                    help="drop the other pack's files for these groups so they look vanilla")
    ap.add_argument("--light-boost", action="store_true", help="add the Diamond SMP Light Boost (1.21.9+)")
    ap.add_argument("--sky-shader", nargs="?", const="high", choices=sorted(shader_sky.QUALITY),
                    help="add the Diamond SMP Shader Sky (1.21.9+): live black hole and real stars, no mods")
    args = ap.parse_args()

    ours = read_zip(ROOT / ("Diamond-SMP-Black-Hole-Pack-Lite.zip" if args.lite else "Diamond-SMP-Black-Hole-Pack.zip"))
    theirs = read_zip(args.other)
    dropped = []
    for group in args.vanilla:
        rx = re.compile("|".join(VANILLA_GROUPS[group]))
        hits = sorted(n for n in theirs if rx.search(n))
        dropped += [(group, n) for n in hits]
        for n in hits:
            del theirs[n]
    their_meta = json.loads(theirs["pack.mcmeta"].decode("utf-8-sig"))
    our_meta = json.loads(ours["pack.mcmeta"].decode("utf-8"))
    name = args.name or plain_description(their_meta, args.other.stem)

    (o_lo, o_hi), (t_lo, t_hi) = pack_range(our_meta), pack_range(their_meta)
    lo, hi = max(o_lo, t_lo), min(o_hi, t_hi)
    if lo > hi:  # no overlap: trust the other pack, it is the version-specific one
        lo, hi = t_lo, t_hi
    if args.light_boost:  # the boost only exists for 1.21.9+, where overlays use min/max_format
        lo = max(lo, tuple(light_boost.MIN_FORMAT))
    if args.sky_shader:   # so does the shader sky
        lo = max(lo, tuple(shader_sky.MIN_FORMAT))
    pack = {
        "description": [
            "",
            {"text": "Diamond SMP ", "color": "aqua", "bold": True},
            {"text": f"+ {name}", "color": "white"},
            {"text": "\nBlack hole sky • personal merge", "color": "gray"},
        ],
        "min_format": to_json_version(lo),
        "max_format": to_json_version(hi),
    }
    if lo[0] < LEGACY_LIMIT:
        pack["pack_format"] = lo[0]
        pack["supported_formats"] = {"min_inclusive": lo[0], "max_inclusive": hi[0]}

    overridden = sorted(n for n in theirs if n in ours and n != "pack.mcmeta")
    merged = dict(theirs)
    merged.update(ours)
    meta = {"pack": pack}
    overlays = list(their_meta.get("overlays", {}).get("entries", []))
    extras = []
    if args.light_boost:
        merged.update({n: t.encode() for n, t in light_boost.overlay_files().items()})
        overlays += light_boost.overlay_entries()
        extras.append("light boost")
    if args.sky_shader:
        merged.update({n: t.encode() for n, t in shader_sky.overlay_files(args.sky_shader).items()})
        overlays += shader_sky.overlay_entries()
        extras.append("live sky")
    pack["description"][3]["text"] = "\n" + " \u2022 ".join(["Black hole sky", *extras, "personal merge"])
    if overlays:
        meta["overlays"] = {"entries": overlays}
    merged["pack.mcmeta"] = (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode()
    merged["DIAMOND_SMP_MERGE.txt"] = (
        f"Personal merge: Diamond SMP Black Hole Sky + {name}\n\n"
        f"Made for your own use only. Check {name}'s README/LICENSE before sharing:\n"
        "many packs do not allow redistributing modified versions.\n\n"
        "Files where Diamond SMP replaced the other pack's version:\n"
        + "".join(f"  {n}\n" for n in overridden)
        + ("\nLeft out so they look vanilla:\n" + "".join(f"  [{g}] {n}\n" for g, n in dropped) if dropped else "")
        + ("\nIncludes the Diamond SMP Light Boost (1.21.9 - 1.21.11, 26.1 - 26.3).\n" if args.light_boost else "")
        + (f"\nIncludes the Diamond SMP Shader Sky ({args.sky_shader}): the black hole and the real night sky\n"
           "drawn live by Minecraft's own sky shaders (1.21.9 - 1.21.11, 26.1 - 26.3). With OptiFine or\n"
           "Nuit, switch their custom sky off to see it.\n" if args.sky_shader else "")
    ).encode()

    safe = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "Other"
    out = args.out or ROOT / "personal" / f"Diamond-SMP-x-{safe}{'-Lite' if args.lite else ''}-PERSONAL.zip"
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n in sorted(merged):
            z.writestr(n, merged[n])
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB): {len(theirs)} files from {name}, "
          f"{len(ours)} from Diamond SMP, {len(overridden)} replaced, formats {lo}..{hi}")
    for n in overridden:
        print("  Diamond SMP wins:", n)
    for g, n in dropped:
        print(f"  vanilla {g}:", n)
    if args.light_boost:
        print("  + light boost overlays:", ", ".join(e["directory"] for e in light_boost.overlay_entries()))
    if args.sky_shader:
        print(f"  + shader sky ({args.sky_shader}) overlays:",
              ", ".join(e["directory"] for e in shader_sky.overlay_entries()))


if __name__ == "__main__":
    main()
