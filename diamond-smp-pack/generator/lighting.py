"""Diamond SMP Lighting: coloured light for vanilla (core shader) and OptiFine (custom lightmaps).

    python lighting.py            # writes ../Diamond-SMP-Colored-Lighting.zip and previews/lighting.png

Minecraft lights every block from two numbers, its sky light and its block (torch) light,
through a 16x16 colour table, the "lightmap", that the game rebuilds every frame. This module
changes that table, the same way twice:

* Vanilla / Fabric / Sodium (1.21.9 and newer): the game draws the lightmap with a core
  shader (shaders/core/lightmap.fsh). The add-on carries a patched copy per shader version
  in pack overlays, exactly like the Light Boost (and it includes the Light Boost, since
  both live in the same file).
* OptiFine: custom lightmap palettes (optifine/lightmap/world*.png), which go in the main
  pack. OptiFine picks a column by the time of day and the torch flicker and adds the sky
  and torch rows together (see the OptiFine docs, "Custom Lightmaps").

The look, in both:
* Torches, lanterns, fire and lava light: a warm amber glow when dim, warm white up close.
* Moonlight: a cooler, clearer blue than vanilla's purple night (eyes see blue in the dark).
* Dawn and dusk: golden sky light while the daylight fades.
* The Nether: a smouldering red-orange haze in the dark. The End: a violet one.
* Rain and storms: greyer, cooler daylight; lightning flashes blue-white.
Overall brightness stays close to vanilla, so mobs and caves are no easier or harder to see.
"""

import io
import json
import re
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

import light_boost

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ADDON_ZIP = "Diamond-SMP-Colored-Lighting.zip"
SHADER = light_boost.SHADER

# (overlay directory, vanilla version patched, min_format, max_format, shader layout)
VARIANTS = [
    ("colored_light_1_21_9", "1.21.11", [69, 0], [75, 99], "ambient_factor"),   # 1.21.9 - 1.21.11
    ("colored_light_26_1", "26.2", [84, 0], [88, 99], "block_tint"),            # 26.1 - 26.2
    ("colored_light_26_3", "26.3", [97, 0], [97, 99], "block_tint"),            # 26.3
]
MIN_FORMAT = light_boost.MIN_FORMAT
MAX_FORMAT = light_boost.MAX_FORMAT

LUMA = np.array([0.2126, 0.7152, 0.0722])

# --- the look (the GLSL below and the numpy model use the same numbers) ----------------
TORCH_GAIN = 1.06             # keeps torch-lit places as bright as vanilla
TORCH_G = (0.58, 0.32)        # torch green  = b * (0.58 + 0.32 * min(b, 1)): amber when dim
TORCH_B = (0.22, 0.50)        # torch blue   = b * (0.22 + 0.50 * min(b, 1)): warm white up close
VANILLA_NIGHT_SKY = np.array([0x7a, 0x7a, 0xff]) / 255.0   # vanilla's night sky light colour
MOON_TINT = np.array([0.80, 1.06, 1.00])                    # vanilla night purple -> moonlight blue
GOLDEN_TINT = np.array([1.25, 0.95, 0.62])                  # sky light at dusk and dawn
GOLDEN_WEIGHT = 0.8
NETHER_HAZE = np.array([1.45, 0.85, 0.62]) / float(np.array([1.45, 0.85, 0.62]) @ LUMA)
END_HAZE = np.array([0.92, 0.74, 1.32]) / float(np.array([0.92, 0.74, 1.32]) @ LUMA)


def _vec3(v):
    return "vec3(%s)" % ", ".join("%.4f" % x for x in v)


FUNCS = f"""\
// ---- Diamond SMP coloured lighting ------------------------------------------
// Torch, lantern, fire and lava light: amber when dim, warm white up close.
vec3 dsl_torch(float b) {{
    float t = clamp(b, 0.0, 1.0);
    return {TORCH_GAIN:.2f} * b * vec3(1.0, {TORCH_G[0]:.2f} + {TORCH_G[1]:.2f} * t, {TORCH_B[0]:.2f} + {TORCH_B[1]:.2f} * t);
}}

// Sky light. Vanilla fades it from white (day) to #7a7aff (night); x is how far through
// that fade we are (1 = day, 0 = night), read from the colour itself so rain and
// thunder (which only grey it) do not count as dusk.
vec3 dsl_sky_light(vec3 sky) {{
    float ratio = sky.r / max(sky.b, 1e-4);
    float x = clamp((ratio - {VANILLA_NIGHT_SKY[0]:.4f}) / {1 - VANILLA_NIGHT_SKY[0]:.4f}, 0.0, 1.0);
    float twilight = 4.0 * x * (1.0 - x);
    vec3 tint = mix({_vec3(MOON_TINT)}, vec3(1.0), x);
    tint *= mix(vec3(1.0), {_vec3(GOLDEN_TINT)}, {GOLDEN_WEIGHT:.2f} * twilight);
    return sky * tint;
}}

// The dimension's ambient light, recoloured at the same brightness: red-orange in the
// Nether, violet in the End. `nether` and `end` say which dimension this is.
vec3 dsl_haze(vec3 ambient, bool nether, bool end) {{
    float lum = dot(ambient, vec3(0.2126, 0.7152, 0.0722));
    if (nether) return lum * {_vec3(NETHER_HAZE)};
    if (end) return lum * {_vec3(END_HAZE)};
    return ambient;
}}
// -----------------------------------------------------------------------------

"""

# 1.21.9 - 1.21.11: the ambient light factor is the dimension's ambient_light: 0 in the
# Overworld, 0.1 in the Nether, 0.25 in the End.
PATCHES = {
    "ambient_factor": [
        (r"vec3 color = vec3\(\s*block_brightness,.*?\);", "vec3 color = dsl_torch(block_brightness);"),
        (re.escape("color = mix(color, lightmapInfo.AmbientColor, lightmapInfo.AmbientLightFactor);"),
         "color = mix(color, dsl_haze(lightmapInfo.AmbientColor,\n"
         "        lightmapInfo.AmbientLightFactor > 0.05 && lightmapInfo.AmbientLightFactor < 0.175,\n"
         "        lightmapInfo.AmbientLightFactor >= 0.175), lightmapInfo.AmbientLightFactor);"),
        (re.escape("color += lightmapInfo.SkyLightColor * sky_brightness;"),
         "color += dsl_sky_light(lightmapInfo.SkyLightColor) * sky_brightness;"),
    ],
    # 26.1+: the ambient colour is the dimension's ambient_light_color: #0a0a0a in the
    # Overworld, a warm #302821 in the Nether and a grey-green #3f473f in the End.
    "block_tint": [
        (re.escape("vec3 color = max(lightmapInfo.AmbientColor, nightVisionColor);"),
         "vec3 dslAmbient = lightmapInfo.AmbientColor;\n"
         "    bool dslLit = max(dslAmbient.r, max(dslAmbient.g, dslAmbient.b)) > 0.08;\n"
         "    vec3 color = max(dsl_haze(dslAmbient, dslLit && dslAmbient.r > 1.15 * dslAmbient.b,\n"
         "        dslLit && dslAmbient.r <= 1.15 * dslAmbient.b), nightVisionColor);"),
        (re.escape("color += lightmapInfo.SkyLightColor * sky_brightness;"),
         "color += dsl_sky_light(lightmapInfo.SkyLightColor) * sky_brightness;"),
        (r"vec3 BlockLightColor = mix\(lightmapInfo\.BlockLightTint.*?;\s*color \+= BlockLightColor \* block_brightness;",
         "color += dsl_torch(block_brightness);"),
    ],
}


def colored(src, layout):
    """The vanilla lightmap shader `src` with the coloured lighting and the Light Boost."""
    if src.count("void main()") != 1:
        raise ValueError("unexpected vanilla lightmap.fsh layout")
    for pattern, repl in PATCHES[layout]:
        src, n = re.subn(pattern, lambda _m: repl, src, flags=re.S)
        if n != 1:
            raise ValueError(f"unexpected vanilla lightmap.fsh layout ({layout}): {pattern[:40]}")
    src = src.replace("void main()", FUNCS + "void main()")
    return light_boost.boosted(src)


def overlay_files():
    """{path inside the pack: shader text} for every overlay."""
    return {f"{d}/{SHADER}": colored(light_boost.vanilla_shader(tag), layout) for d, tag, _, _, layout in VARIANTS}


def overlay_entries():
    return [{"directory": d, "min_format": lo, "max_format": hi} for d, _, lo, hi, _ in VARIANTS]


def validate(verbose=True):
    """Compile each overlay's shader with glslangValidator (26.3 in Vulkan mode)."""
    import shutil
    import subprocess
    exe = shutil.which("glslangValidator")
    if exe is None:
        print("glslangValidator not installed: skipping shader compile check")
        return True
    tmp = HERE / ".cache" / "shader_check"
    tmp.mkdir(parents=True, exist_ok=True)
    ok = True
    for d, tag, _, _, _ in VARIANTS:
        path = tmp / f"{d}.frag"
        path.write_text(overlay_files()[f"{d}/{SHADER}"])
        flags = ["-V", "--amb", "--aml", "-o", str(tmp / "out.spv")] if tag == "26.3" else []
        res = subprocess.run([exe, *flags, str(path)], capture_output=True, text=True)
        ok &= res.returncode == 0
        if verbose or res.returncode:
            print(f"  {d} (vanilla {tag}): {'compiles OK' if res.returncode == 0 else 'FAILED'}")
            if res.returncode:
                print(res.stdout[-3000:])
    return ok


# ---------------------------------------------------------------------------
# numpy model of the 1.21.11 shader (vanilla and coloured), for previews, tests and the
# OptiFine palettes
# ---------------------------------------------------------------------------


def get_brightness(level):
    return level / (4.0 - 3.0 * level)


def torch(b):
    b = np.asarray(b, float)[..., None]
    t = np.clip(b, 0, 1)
    return TORCH_GAIN * b * np.concatenate([np.ones_like(t), TORCH_G[0] + TORCH_G[1] * t, TORCH_B[0] + TORCH_B[1] * t], -1)


def vanilla_torch(b):
    b = np.asarray(b, float)[..., None]
    return np.concatenate([b, b * ((b * 0.6 + 0.4) * 0.6 + 0.4), b * (b * b * 0.6 + 0.4)], -1)


def sky_light(sky):
    sky = np.asarray(sky, float)
    x = np.clip((sky[..., 0] / np.maximum(sky[..., 2], 1e-4) - VANILLA_NIGHT_SKY[0]) / (1 - VANILLA_NIGHT_SKY[0]), 0, 1)
    tw = (4 * x * (1 - x))[..., None]
    tint = MOON_TINT + (1 - MOON_TINT) * x[..., None]
    tint = tint * (1 + (GOLDEN_TINT - 1) * GOLDEN_WEIGHT * tw)
    return sky * tint


def haze(ambient, factor):
    lum = float(np.asarray(ambient) @ LUMA)
    if 0.05 < factor < 0.175:
        return lum * NETHER_HAZE
    if factor >= 0.175:
        return lum * END_HAZE
    return np.asarray(ambient, float)


def not_gamma(c):
    m = np.maximum(c.max(-1, keepdims=True), 1e-6)
    inv = 1 - m
    return c * ((1 - inv ** 4) / m)


# The states the game feeds the lightmap shader in each situation (1.21.11 values from the
# vanilla timelines and dimension types; the ambient colour is assumed white).
SCENES = {
    "day": dict(sky_factor=1.0, sky_color=(1.0, 1.0, 1.0), ambient=0.0),
    "dusk": dict(sky_factor=0.62, sky_color=tuple(0.5 * (1 + VANILLA_NIGHT_SKY)), ambient=0.0),
    "night": dict(sky_factor=0.24, sky_color=tuple(VANILLA_NIGHT_SKY), ambient=0.0),
    "nether": dict(sky_factor=0.0, sky_color=tuple(VANILLA_NIGHT_SKY), ambient=0.1),
    "end": dict(sky_factor=0.0, sky_color=(0xe5 / 255, 0x80 / 255, 1.0), ambient=0.25),
}


def lightmap(scene, coloured=True, block_factor=1.5, brightness=0.5, boost=None):
    """16x16x3 lightmap (rows: sky level 0..15, columns: block level 0..15) in `scene`."""
    p = SCENES[scene] if isinstance(scene, str) else scene
    level = np.arange(16) / 15.0
    b = get_brightness(level) * block_factor
    s = get_brightness(level) * p["sky_factor"]
    sky_col = np.asarray(p["sky_color"], float)
    amb = np.ones(3)
    f = p["ambient"]
    color = (torch(b) if coloured else vanilla_torch(b))[None, :, :]
    color = color * (1 - f) + (haze(amb, f) if coloured else amb) * f
    color = color + (sky_light(sky_col) if coloured else sky_col) * s[:, None, None]
    color = color + (0.75 - color) * 0.04
    color = np.clip(color, 0, 1)
    color = color + (not_gamma(color) - color) * brightness
    color = color + (0.75 - color) * 0.04
    if boost if boost is not None else coloured:
        lum = color.max(-1, keepdims=True)
        lift = 0.02 + 0.13 * (1 - np.clip(lum, 0, 1)) ** 2
        color = color + (1 - color) * lift
    return color


# ---------------------------------------------------------------------------
# OptiFine custom lightmap palettes
# ---------------------------------------------------------------------------

PALETTE_WIDTH = 64       # columns 0..62: night -> day (sky) / flicker (torch); 63: lightning
FLOOR = 0.035            # the darkest a block gets with no light at all


def _palette(sky_rows, torch_rows):
    """Stack sky and torch rows (each (16, W, 3) linear) plus night-vision rows into 64 x W."""
    norm = sky_rows / np.maximum(sky_rows.max(-1, keepdims=True), 1e-4)
    nv_sky = np.maximum(0.80 * (norm + (0.85 - norm) * 0.45), sky_rows)   # bright, hue kept but softened
    nv_torch = torch_rows * 0.55
    img = np.concatenate([sky_rows, torch_rows, nv_sky, nv_torch], 0)
    return Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def _torch_rows(scale=1.0):
    flicker = np.linspace(0.90, 1.08, PALETTE_WIDTH)
    level = get_brightness(np.arange(16) / 15.0)
    return torch(level[:, None] * 1.5 * flicker[None, :]) * scale


def overworld_palette(weather="clear"):
    w = PALETTE_WIDTH
    s = np.linspace(0, 1, w - 1)                                   # 0 = midnight, 1 = noon
    sky_col = VANILLA_NIGHT_SKY + (1 - VANILLA_NIGHT_SKY) * np.clip(s * 1.6 - 0.3, 0, 1)[:, None]
    tint = sky_light(sky_col)
    factor = 0.24 + 0.76 * s
    if weather != "clear":
        grey = np.array([0.90, 0.94, 1.0])
        k = 0.65 if weather == "rain" else 0.85
        lum = (tint @ LUMA)[:, None]
        tint = (tint + (lum * grey - tint) * k) * (0.92 if weather == "rain" else 0.82)
    level = get_brightness(np.arange(16) / 15.0)
    sky = level[:, None, None] * factor[None, :, None] * tint[None, :, :]
    floor = FLOOR * np.array([0.85, 0.92, 1.10])
    sky = sky + floor
    # the last column: a lightning flash, blue-white
    flash = level[:, None] * np.array([0.82, 0.86, 1.0]) * (1.0 if weather == "thunder" else 0.9) + floor
    sky = np.concatenate([sky, flash[:, None, :]], 1)
    return _palette(sky, _torch_rows())


def dimension_palette(haze_colour, ambient):
    """The Nether and the End have no day: every sky column is the same coloured haze."""
    floor = ambient * haze_colour + FLOOR * 0.4
    sky = np.broadcast_to(floor, (16, PALETTE_WIDTH, 3)).copy()
    return _palette(sky, _torch_rows(1 - ambient))


def optifine_lightmaps():
    """{path in the pack: PNG bytes} of the OptiFine custom lightmaps."""
    imgs = {
        "world0": overworld_palette("clear"),
        "world0_rain": overworld_palette("rain"),
        "world0_thunder": overworld_palette("thunder"),
        "world-1": dimension_palette(NETHER_HAZE, 0.10),
        "world1": dimension_palette(END_HAZE, 0.25),
    }
    out = {}
    for name, img in imgs.items():
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        out[f"assets/minecraft/optifine/lightmap/{name}.png"] = buf.getvalue()
    return out


# ---------------------------------------------------------------------------
# Other OptiFine features: emissive overlays, natural textures, better grass
# ---------------------------------------------------------------------------

EMISSIVE = """\
# Diamond SMP - OptiFine emissive textures: any texture with a matching <name>_e.png
# overlay (glowing ore specks, eyes, lamps, ...) glows at full brightness in the dark.
suffix.emissive=_e
"""

NATURAL = """\
# Diamond SMP - OptiFine natural textures: blocks are randomly rotated and flipped
# so big fields of grass, sand and stone stop showing a repeating grid.
# 4 = rotate in 90 degree steps, 2 = rotate 180, F = flip, 4F / 2F = both
grass_block_top = 4F
grass_block_side = F
grass_block_side_overlay = F
grass_block_snow = F
dirt = 4F
coarse_dirt = 4F
rooted_dirt = 4F
podzol_top = 4F
podzol_side = F
mycelium_top = 4F
mycelium_side = F
dirt_path_top = 4
dirt_path_side = F
farmland = 2F
farmland_moist = 2F
mud = 4F
clay = 4F
snow = 4F
sand = 4F
red_sand = 4F
suspicious_sand_0 = 4F
gravel = 2
stone = 2F
granite = 2F
diorite = 2F
andesite = 2F
tuff = 2F
calcite = 2F
sandstone_top = 4
sandstone_bottom = 4F
red_sandstone_top = 4
red_sandstone_bottom = 4F
end_stone = 4
netherrack = 4F
soul_sand = 4F
soul_soil = 4F
crimson_nylium = 4F
warped_nylium = 4F
glowstone = 4
nether_quartz_ore = 2
oak_log_top = 4F
spruce_log_top = 4F
birch_log_top = 4F
jungle_log_top = 4F
acacia_log_top = 4F
dark_oak_log_top = 4F
mangrove_log_top = 4F
cherry_log_top = 4F
oak_leaves = 2F
spruce_leaves = 2F
birch_leaves = 2F
jungle_leaves = 2
acacia_leaves = 2F
dark_oak_leaves = 2F
mangrove_leaves = 2F
azalea_leaves = 2F
cherry_leaves = 2F
coal_ore = 2F
iron_ore = 2F
gold_ore = 2F
copper_ore = 2F
redstone_ore = 2F
lapis_ore = 2F
diamond_ore = 2F
emerald_ore = 2F
"""

BETTER_GRASS = """\
# Diamond SMP - OptiFine better grass: the sides of grass, paths, mycelium, podzol and
# nylium blocks take the top's texture where they meet the same block below, so hills
# look like continuous grassy slopes. (OptiFine: Video Settings > Quality > Better Grass.)
grass=true
dirt_path=true
mycelium=true
podzol=true
crimson_nylium=true
warped_nylium=true
grass.snow=true
mycelium.snow=true
podzol.snow=true
grass.multilayer=false
texture.grass=block/grass_block_top
texture.grass_side=block/grass_block_side
texture.dirt_path=block/dirt_path_top
texture.dirt_path_side=block/dirt_path_side
texture.mycelium=block/mycelium_top
texture.podzol=block/podzol_top
texture.crimson_nylium=block/crimson_nylium
texture.warped_nylium=block/warped_nylium
texture.snow=block/snow
"""


def optifine_files():
    """{path in the pack: bytes} of every OptiFine extra the main pack carries."""
    out = optifine_lightmaps()
    for name, text in (("emissive", EMISSIVE), ("natural", NATURAL), ("bettergrass", BETTER_GRASS)):
        out[f"assets/minecraft/optifine/{name}.properties"] = text.encode()
    return out


# ---------------------------------------------------------------------------
# The add-on and the preview
# ---------------------------------------------------------------------------


def build_addon(icon=None):
    meta = {
        "pack": {
            "description": [
                "",
                {"text": "Diamond SMP ", "color": "aqua", "bold": True},
                {"text": "Colored Lighting", "color": "gold"},
                {"text": "\nWarm torches • blue moonlight • 1.21.9+", "color": "gray"},
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


def _scene_strip(lm, w=256, h=96):
    """A little cave scene lit by the lightmap: a torch on the left, open sky at the top."""
    y, x = np.mgrid[0:h, 0:w]
    block = np.clip(15 - np.hypot(x - 24, (y - h * 0.62) * 1.4) / 13.0, 0, 15)
    sky = np.clip(15 - np.maximum(h * 0.45 - y, 0) * 0 - (y / h) * 26 + (x / w) * 9, 0, 15)
    rgb = lm[np.floor(sky).astype(int), np.floor(block).astype(int)]
    rng = np.random.default_rng(3)
    stone = 0.42 + 0.10 * rng.standard_normal((h // 8 + 1, w // 8 + 1)).clip(-2, 2)
    tex = np.kron(stone, np.ones((8, 8)))[:h, :w, None]
    return np.clip(rgb * tex * 1.7, 0, 1)


def preview(path=ROOT / "previews" / "lighting.png"):
    """Vanilla vs Diamond lightmaps and a lit scene, for day, dusk, night, Nether and End."""
    from PIL import ImageDraw
    cell, pad = 256, 16
    names = list(SCENES)
    W = pad + len(names) * (cell + pad)
    H = 2 * (cell // 2 + 96 + 3 * pad) + 40
    img = Image.new("RGB", (W, H), (14, 16, 22))
    draw = ImageDraw.Draw(img)
    for row, coloured in enumerate((False, True)):
        y0 = 30 + row * (cell // 2 + 96 + 3 * pad)
        draw.text((pad, y0 - 18), "Diamond SMP colored lighting" if coloured else "Vanilla", fill=(220, 225, 235))
        for k, name in enumerate(names):
            lm = lightmap(name, coloured)
            x0 = pad + k * (cell + pad)
            sw = Image.fromarray((lm[::-1] ** (1 / 1.0) * 255).astype(np.uint8)).resize((cell // 2, cell // 2), Image.NEAREST)
            img.paste(sw, (x0, y0))
            sc = Image.fromarray((_scene_strip(lm) * 255).astype(np.uint8))
            img.paste(sc, (x0, y0 + cell // 2 + pad // 2))
            draw.text((x0 + cell // 2 + 8, y0 + 4), name, fill=(200, 205, 215))
            draw.text((x0 + cell // 2 + 8, y0 + 20), "torch ->", fill=(150, 150, 160))
            draw.text((x0 + cell // 2 + 8, y0 + 36), "sky ^", fill=(150, 150, 160))
    path.parent.mkdir(exist_ok=True)
    img.save(path, optimize=True)
    print(f"wrote {path.relative_to(ROOT)}")
    return path


if __name__ == "__main__":
    ok = validate()
    build_addon(ROOT / "pack" / "pack.png")
    preview()
    if not ok:
        raise SystemExit("shader compile check failed")
