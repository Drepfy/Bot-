"""Diamond SMP Light Boost: a slight brightness lift that gets stronger in the dark.

    python light_boost.py      # writes ../Diamond-SMP-Light-Boost.zip

The boost lives in Minecraft's lightmap shader, which changes between versions,
so the pack carries one patched copy per shader version in pack "overlays" and
the game picks the right one. Versions without a matching overlay simply get no
boost (nothing breaks). The vanilla shaders are fetched from the misode/mcmeta
mirror of the game assets and cached in generator/.cache/.

The boost:
* about +2% in full light, rising smoothly to about +15% in pitch black
  (caves, night), applied after the game's own Brightness setting;
* fades out under the Warden's Darkness effect, so it doesn't cheat PvP/PvE.
"""

import json
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CACHE = HERE / ".cache"
ADDON_ZIP = "Diamond-SMP-Light-Boost.zip"
MIRROR = "https://raw.githubusercontent.com/misode/mcmeta/{tag}-assets/assets/minecraft/shaders/core/lightmap.fsh"
SHADER = "assets/minecraft/shaders/core/lightmap.fsh"

# (overlay directory, version whose vanilla shader is patched, min_format, max_format)
VARIANTS = [
    ("light_boost_1_21_9", "1.21.11", [69, 0], [75, 99]),   # 1.21.9 - 1.21.11
    ("light_boost_26_1", "26.2", [84, 0], [88, 99]),        # 26.1 - 26.2
    ("light_boost_26_3", "26.3", [97, 0], [97, 99]),        # 26.3
]
MIN_FORMAT = [69, 0]
MAX_FORMAT = [97, 99]

BOOST = """\
    // Diamond SMP light boost: slight in bright light, stronger the darker it
    // gets. Fades out under the Darkness effect.
    {
        float boostLum = max(color.r, max(color.g, color.b));
        float boostDark = 1.0 - clamp(boostLum, 0.0, 1.0);
        float boostLift = 0.02 + 0.13 * boostDark * boostDark;
        boostLift *= 1.0 - clamp(lightmapInfo.DarknessScale * 4.0, 0.0, 1.0);
        color = color + (vec3(1.0) - color) * boostLift;
    }

"""
ANCHOR = "    fragColor = vec4(color, 1.0);"


def vanilla_shader(tag):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"lightmap_{tag}.fsh"
    if not path.exists():
        with urllib.request.urlopen(MIRROR.format(tag=tag), timeout=30) as r:
            path.write_bytes(r.read())
    return path.read_text(encoding="utf-8")


def boosted(src):
    if src.count(ANCHOR) != 1 or "uniform LightmapInfo" not in src or "DarknessScale" not in src:
        raise ValueError("unexpected vanilla lightmap.fsh layout; the boost needs updating")
    return src.replace(ANCHOR, BOOST + ANCHOR)


def overlay_files():
    """{path inside the pack: shader text} for every overlay."""
    return {f"{d}/{SHADER}": boosted(vanilla_shader(tag)) for d, tag, _, _ in VARIANTS}


def overlay_entries():
    return [{"directory": d, "min_format": lo, "max_format": hi} for d, _, lo, hi in VARIANTS]


def build_addon(icon=None):
    meta = {
        "pack": {
            "description": [
                "",
                {"text": "Diamond SMP ", "color": "aqua", "bold": True},
                {"text": "Light Boost", "color": "yellow"},
                {"text": "\nSlight, stronger in the dark • 1.21.9+", "color": "gray"},
            ],
            "min_format": MIN_FORMAT,
            "max_format": MAX_FORMAT,
        },
        "overlays": {"entries": overlay_entries()},
    }
    out = ROOT / ADDON_ZIP
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("pack.mcmeta", json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        if icon is not None and Path(icon).exists():
            z.write(icon, "pack.png")
        for name, text in sorted(overlay_files().items()):
            z.writestr(name, text)
    print(f"wrote {out.name} ({out.stat().st_size / 1e3:.1f} kB)")
    return out


if __name__ == "__main__":
    build_addon(ROOT / "pack" / "pack.png")
