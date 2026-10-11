"""Combine Diamond SMP with another resource pack into one zip, for PERSONAL use.

    python merge_packs.py path/to/OtherPack.zip            # uses the full Diamond SMP zip
    python merge_packs.py path/to/OtherPack.zip --lite     # uses the Lite zip

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

ROOT = Path(__file__).resolve().parent.parent
SKIP = ("__MACOSX/", ".DS_Store", "Thumbs.db")
LEGACY_LIMIT = 65  # resource pack formats below this need pack_format/supported_formats


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
    args = ap.parse_args()

    ours = read_zip(ROOT / ("Diamond-SMP-Black-Hole-Pack-Lite.zip" if args.lite else "Diamond-SMP-Black-Hole-Pack.zip"))
    theirs = read_zip(args.other)
    their_meta = json.loads(theirs["pack.mcmeta"].decode("utf-8-sig"))
    our_meta = json.loads(ours["pack.mcmeta"].decode("utf-8"))
    name = args.name or plain_description(their_meta, args.other.stem)

    (o_lo, o_hi), (t_lo, t_hi) = pack_range(our_meta), pack_range(their_meta)
    lo, hi = max(o_lo, t_lo), min(o_hi, t_hi)
    if lo > hi:  # no overlap: trust the other pack, it is the version-specific one
        lo, hi = t_lo, t_hi
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
    merged["pack.mcmeta"] = (json.dumps({"pack": pack}, indent=2, ensure_ascii=False) + "\n").encode()
    merged["DIAMOND_SMP_MERGE.txt"] = (
        f"Personal merge: Diamond SMP Black Hole Sky + {name}\n\n"
        f"Made for your own use only. Check {name}'s README/LICENSE before sharing:\n"
        "many packs do not allow redistributing modified versions.\n\n"
        "Files where Diamond SMP replaced the other pack's version:\n"
        + "".join(f"  {n}\n" for n in overridden)
    ).encode()

    safe = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "Other"
    out = args.out or ROOT / "personal" / f"Diamond-SMP-x-{safe}{'-Lite' if args.lite else ''}-PERSONAL.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n in sorted(merged):
            z.writestr(n, merged[n])
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB): {len(theirs)} files from {name}, "
          f"{len(ours)} from Diamond SMP, {len(overridden)} replaced, formats {lo}..{hi}")
    for n in overridden:
        print("  Diamond SMP wins:", n)


if __name__ == "__main__":
    main()
