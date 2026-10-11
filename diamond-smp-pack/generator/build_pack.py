"""Builds the Diamond SMP "Black Hole" resource pack.

    pip install numpy numba pillow
    python build_pack.py            # full quality (a few minutes)
    python build_pack.py --quick    # low-res draft

Everything in the pack is generated from scratch by this script: the black hole
skies are ray traced (see blackhole.py), the logo and icon are drawn in code.
Block, item and mob textures are left vanilla on purpose.
"""

import argparse
import hashlib
import json
import math
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import blackhole as bh

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pack"
ZIP_NAME = "Diamond-SMP-Black-Hole-Pack.zip"
MC = OUT / "assets" / "minecraft"

# Colour ramps (linear RGB), cold to hot.
DIAMOND = np.array([
    [0.00, 0.00, 0.00],
    [0.05, 0.01, 0.16],   # deep violet
    [0.16, 0.05, 0.55],   # indigo
    [0.05, 0.25, 0.95],   # royal blue
    [0.05, 0.62, 1.00],   # diamond blue
    [0.25, 0.90, 1.00],   # diamond cyan
    [0.70, 1.00, 1.00],   # ice
    [1.00, 1.00, 1.00],
])
VOID = np.array([          # the End: ender purple
    [0.00, 0.00, 0.00],
    [0.07, 0.00, 0.12],
    [0.28, 0.02, 0.45],
    [0.55, 0.08, 0.85],
    [0.85, 0.25, 1.00],
    [1.00, 0.55, 0.95],
    [1.00, 0.85, 1.00],
    [1.00, 1.00, 1.00],
])

DISK = dict(haze=0.012, disk_intensity=3.0, ring=0.8, disk_opacity=4.0,
            temperature=0.82, temp_max=0.92, doppler_power=2.5)


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.1f}s] {msg}", flush=True)


def save(img, rel):
    path = MC / rel if not str(rel).startswith("/") else Path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img)
    img.save(path, optimize=True)
    return path


# ---------------------------------------------------------------------------
# Direction grids for the different texture layouts
# ---------------------------------------------------------------------------


def optifine_tile_matrices():
    """MCPatcher/OptiFine 3x2 sky geometry (tile -> model matrix).

    Layout of the 3x2 image:   [Bottom][ Top  ][Back=S ]
                               [Left=W][Front=N][Right=E]
    """
    m = bh.rot(-90, (0, 1, 0))  # vanilla rotates the sky by -90 deg yaw first
    m = m @ bh.rot(90, (1, 0, 0)) @ bh.rot(-90, (0, 0, 1))
    out = [None] * 6
    out[4] = m
    out[1] = m @ bh.rot(90, (1, 0, 0))
    out[0] = m @ bh.rot(-90, (1, 0, 0))
    m = m @ bh.rot(90, (0, 0, 1)); out[5] = m
    m = m @ bh.rot(90, (0, 0, 1)); out[2] = m
    m = m @ bh.rot(90, (0, 0, 1)); out[3] = m
    return out


OPTIFINE_TILES = optifine_tile_matrices()


def optifine_tile_dirs(tile, size):
    t = (np.arange(size) + 0.5) / size * 2 - 1
    lx, lz = np.meshgrid(t, t)
    local = np.stack([lx, -np.ones_like(lx), lz], -1)
    return bh.normalize(local @ OPTIFINE_TILES[tile].T)


def panorama_dirs(face, size):
    """Vanilla title panorama: 0 front, 1 right, 2 back, 3 left, 4 up, 5 down."""
    yaw = [0, 90, 180, -90, 0, 0][face]
    pitch = [0, 0, 0, 0, -90, 90][face]
    f = bh.mc_direction(yaw, pitch)
    u = bh.mc_direction(yaw, pitch - 90)
    r = np.cross(f, u)
    t = (np.arange(size) + 0.5) / size * 2 - 1
    a, b = np.meshgrid(t, t)
    d = f[None, None] + a[..., None] * r[None, None] - b[..., None] * u[None, None]
    return bh.normalize(d)


def camera_dirs(w, h, half_tan_x, rotation=None):
    """Pinhole camera looking along scene +z (scene right is -x)."""
    xs = ((np.arange(w) + 0.5) / w * 2 - 1) * half_tan_x
    ys = ((np.arange(h) + 0.5) / h * 2 - 1) * half_tan_x * h / w
    a, b = np.meshgrid(xs, ys)
    d = bh.normalize(np.stack([-a, -b, np.ones_like(a)], -1))
    return d if rotation is None else d @ rotation.T


def supersample(dir_fn, size, ss):
    """Call dir_fn(size*ss) and return a function that averages ss x ss blocks."""
    d = dir_fn(size * ss)
    return d, (lambda img: img.reshape(size, ss, size, ss, -1).mean(axis=(1, 3)))


def render_world(scene, world_to_scene, dir_fn, size, ss):
    dirs, shrink = supersample(dir_fn, size, ss)
    return shrink(scene.render(dirs @ world_to_scene.T))


# ---------------------------------------------------------------------------
# Sky textures
# ---------------------------------------------------------------------------


def render_optifine_sky(scene, target_dir, face, ss, exposure, seed):
    w2s = bh.world_to_scene(target_dir)
    img = np.zeros((2 * face, 3 * face, 3), dtype=np.uint8)
    for tile in range(6):
        rgb = render_world(scene, w2s, lambda n: optifine_tile_dirs(tile, n), face, ss)[..., :3]
        r, c = divmod(tile, 3)
        img[r * face:(r + 1) * face, c * face:(c + 1) * face] = bh.tonemap(rgb, exposure, seed + tile)
        log(f"  sky tile {tile + 1}/6")
    return img


def render_panorama(scene, target_dir, face, ss, exposure, seed):
    w2s = bh.world_to_scene(target_dir)
    for k in range(6):
        rgb = render_world(scene, w2s, lambda n: panorama_dirs(k, n), face, ss)[..., :3]
        save(bh.tonemap(rgb, exposure, seed + k), f"textures/gui/title/background/panorama_{k}.png")
        log(f"  panorama {k + 1}/6")


def render_sun(size, ss):
    """The vanilla sun becomes a small black hole (drawn additively by the game)."""
    scene = bh.BlackHoleScene(DIAMOND, distance=40, inclination=14, roll=24, r_out=9.5, seed=21,
                              **{**DISK, "disk_intensity": 3.4, "haze": 0.02})
    # The sun quad is 30 units wide at distance 100: half-angle tangent 0.3.
    dirs = camera_dirs(size * ss, size * ss, 0.3)
    out = scene.render(dirs).reshape(size, ss, size, ss, 4).mean(axis=(1, 3))
    t = (np.arange(size) + 0.5) / size * 2 - 1
    a, b = np.meshgrid(t, t)
    rad = np.sqrt(a * a + b * b)
    fade = np.clip((1.0 - rad) / 0.25, 0, 1) ** 2
    lin = 1.0 - np.exp(-out[..., :3] * 1.1)
    srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055) * fade[..., None]
    alpha = np.maximum(srgb.max(-1), out[..., 3] * fade)
    rgb = np.where(alpha[..., None] > 1e-4, srgb / np.maximum(alpha[..., None], 1e-4), 0)
    rgba = np.concatenate([rgb, alpha[..., None]], -1)
    return np.clip(np.round(rgba * 255), 0, 255).astype(np.uint8)


def render_star_sun(size):
    """OptiFine replaces the sun with a diamond-white star so the sky has one black hole."""
    t = (np.arange(size) + 0.5) / size * 2 - 1
    a, b = np.meshgrid(t, t)
    r = np.sqrt(a * a + b * b)
    core = np.exp(-(r / 0.035) ** 2) * 3.0 + np.exp(-(r / 0.09) ** 2) * 0.6 + np.exp(-r / 0.22) * 0.12
    spikes = np.zeros_like(r)
    for ang, length in ((0, 0.75), (90, 0.75), (45, 0.32), (135, 0.32)):
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        along = a * ca + b * sa
        across = -a * sa + b * ca
        spikes += np.exp(-(across / 0.012) ** 2) * np.exp(-np.abs(along) / (length * 0.35))
    lum = core + spikes * 0.9
    col = np.array([0.75, 0.95, 1.0])
    rgb = 1.0 - np.exp(-lum[..., None] * col * 1.4)
    rgb *= np.clip((1.0 - r) / 0.2, 0, 1)[..., None]
    return np.clip(np.round(rgb ** (1 / 2.2) * 255), 0, 255).astype(np.uint8)


def render_end_tile(size, seed):
    """Tileable deep-space texture for the vanilla End sky (the game dims it a lot)."""
    rng = np.random.default_rng(seed)
    # Fine-grained, low-contrast nebula: the game tiles this 16x per face, so
    # big blobs would repeat visibly.
    neb = bh.periodic_noise(size, size, seed, aniso=1.0, alpha=1.15)
    neb2 = bh.periodic_noise(size, size, seed + 1, aniso=1.0, alpha=1.0)
    img = np.zeros((size, size, 3))
    img += (np.clip(neb - 0.3, 0, 1) ** 1.5 * 0.55)[..., None] * np.array([0.55, 0.12, 0.85])
    img += (np.clip(neb2 - 0.5, 0, 1) * 0.45)[..., None] * np.array([0.15, 0.25, 0.9])
    n = size * size // 90
    xs, ys = rng.uniform(0, size, n), rng.uniform(0, size, n)
    br = np.clip(0.25 * (rng.pareto(1.6, n) + 1) ** 1.3, 0, 4)
    tint = bh.star_colour(rng.choice([4000, 6500, 9000, 16000, 25000], n))
    for x, y, v, c in zip(xs, ys, br, tint):
        x0, y0 = int(x), int(y)
        for dy in (-1, 0, 1, 2):
            for dx in (-1, 0, 1, 2):
                px, py = (x0 + dx) % size, (y0 + dy) % size
                d2 = (x0 + dx + 0.5 - x) ** 2 + (y0 + dy + 0.5 - y) ** 2
                img[py, px] += c * v * math.exp(-d2 / 0.5)
    return bh.tonemap(img, 2.2, seed)


# ---------------------------------------------------------------------------
# Logo, edition banner and pack icon (pixel art drawn in code)
# ---------------------------------------------------------------------------

GLYPHS = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".####", "#....", "#....", "#....", "#....", "#....", ".####"],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": ["###", ".#.", ".#.", ".#.", ".#.", ".#.", "###"],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    " ": ["..", "..", "..", "..", "..", "..", ".."],
}


def text_grid(text):
    cols = []
    for i, ch in enumerate(text):
        g = GLYPHS[ch]
        if i:
            cols.append([False] * 7)
        for x in range(len(g[0])):
            cols.append([g[y][x] == "#" for y in range(7)])
    return np.array(cols, dtype=bool).T  # (7, width)


def dilate(mask, r):
    img = Image.fromarray((mask * 255).astype(np.uint8))
    return np.array(img.filter(ImageFilter.MaxFilter(2 * r + 1))) > 127


def hexrgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64)


def block_text(text, block, depth, outline, top, bottom, side, edge_dark, rng, sparkle=0.08):
    grid = text_grid(text)
    gh, gw = grid.shape
    h, w = gh * block, gw * block
    pad = outline + 2
    H, W = h + depth + 2 * pad, w + 2 * pad
    face = np.zeros((H, W, 3))
    face_m = np.zeros((H, W), dtype=bool)
    px = max(block // 8, 1)  # size of one "texel" on a block
    bev = 2 * px if block >= 8 else 1
    for gy in range(gh):
        for gx in range(gw):
            if not grid[gy, gx]:
                continue
            y0, x0 = pad + gy * block, pad + gx * block
            for ty in range(0, block, px):
                for tx in range(0, block, px):
                    k = (gy * block + ty) / max(h - 1, 1)  # vertical gradient over the word
                    c = top * (1 - k) + bottom * k
                    if ty < bev or tx < bev:
                        c = c * 0.55 + 255 * 0.45  # bevel highlight
                    if ty >= block - bev or tx >= block - bev:
                        c = c * 0.72  # bevel shade
                    if rng.random() < sparkle:
                        c = c * 0.3 + 255 * 0.7
                    face[y0 + ty:y0 + ty + px, x0 + tx:x0 + tx + px] = c
            face_m[y0:y0 + block, x0:x0 + block] = True
    # Extrusion: stacked copies of the silhouette pushed downwards, darkening.
    ext = np.zeros((H, W, 3))
    ext_m = np.zeros((H, W), dtype=bool)
    for d in range(depth, 0, -1):
        sh = np.zeros_like(face_m)
        sh[d:] = face_m[:-d]
        k = d / depth
        ext[sh] = side * (1 - 0.45 * k)
        ext_m |= sh
    rgb = np.where(ext_m[..., None], ext, 0)
    rgb = np.where(face_m[..., None], face, rgb)
    solid = face_m | ext_m
    # Dark seam where the face meets the extrusion makes the 3D read clearly.
    seam = ext_m & ~face_m & dilate(face_m, 1)
    rgb[seam] = edge_dark
    ring = dilate(solid, outline) & ~solid
    alpha = (solid | ring).astype(np.float64)
    rgb[ring] = edge_dark * 0.5
    return np.concatenate([rgb, alpha[..., None] * 255], -1).astype(np.uint8)


def make_logo():
    rng = np.random.default_rng(5)
    word = block_text("DIAMOND SMP", 16, 14, 4, hexrgb("#c9fbff"), hexrgb("#1497c4"),
                      hexrgb("#0e5f86"), hexrgb("#04162b"), rng)
    canvas = Image.new("RGBA", (1024, 256), (0, 0, 0, 0))
    wimg = Image.fromarray(word)
    canvas.alpha_composite(wimg, ((1024 - wimg.width) // 2, 6))
    return canvas


def make_edition():
    rng = np.random.default_rng(9)
    word = block_text("BLACK HOLE EDITION", 4, 3, 2, hexrgb("#f6e6ff"), hexrgb("#a24cff"),
                      hexrgb("#4a1785"), hexrgb("#12021f"), rng, sparkle=0.0)
    canvas = Image.new("RGBA", (512, 64), (0, 0, 0, 0))
    wimg = Image.fromarray(word)
    canvas.alpha_composite(wimg, ((512 - wimg.width) // 2, (56 - wimg.height) // 2))
    return canvas


GEM = [
    "...##########...",
    "..#WLLWLLWLLD#..",
    ".#WLLLWLLWLLLD#.",
    "#MMMMMMMMMMMMMD#",
    ".#MLMMMLLMMMLD#.",
    "..#MLMMLLMMLD#..",
    "...#MLMLLMLD#...",
    "....#MLLLLD#....",
    ".....#MLLD#.....",
    "......#LD#......",
    ".......##.......",
]
GEM_COL = {"#": "#06203d", "W": "#ffffff", "L": "#9ff6ff", "M": "#33d0ea", "D": "#137e9e"}


def make_icon(size=256):
    """Pack icon: the black hole with a pixel-art diamond burning in front of it."""
    scene = bh.BlackHoleScene(DIAMOND, distance=17, inclination=12, roll=-18, r_out=11, seed=33,
                              background=bh.make_starfield(256, 41, (0.12, 0.04, 0.35), (0.02, 0.18, 0.40),
                                                           (0.3, 0.8, 0.5), n_stars=6000), **DISK)
    dirs = camera_dirs(size * 3, size * 3, math.tan(math.radians(36)))
    img = scene.render(dirs).reshape(size, 3, size, 3, 4).mean(axis=(1, 3))
    icon = Image.fromarray(bh.tonemap(img[..., :3], 1.0, 3)).convert("RGBA")
    cell = max(size // 64, 1)  # gem pixel size
    gw, gh = 16 * cell, len(GEM) * cell
    gem = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
    gp = gem.load()
    for y, row in enumerate(GEM):
        for x, ch in enumerate(row):
            if ch in GEM_COL:
                c = tuple(int(v) for v in hexrgb(GEM_COL[ch])) + (255,)
                for yy in range(cell):
                    for xx in range(cell):
                        gp[x * cell + xx, y * cell + yy] = c
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ox, oy = (size - gw) // 2, (size - gh) // 2 + cell
    glow.alpha_composite(gem, (ox, oy))
    halo = np.array(glow)[..., 3].astype(np.float64)
    halo = np.array(Image.fromarray(halo.astype(np.uint8)).filter(ImageFilter.GaussianBlur(cell * 2.5)))
    halo_rgba = np.zeros((size, size, 4), dtype=np.uint8)
    halo_rgba[..., :3] = (120, 240, 255)
    halo_rgba[..., 3] = np.clip(halo * 0.9, 0, 255).astype(np.uint8)
    icon.alpha_composite(Image.fromarray(halo_rgba))
    icon.alpha_composite(gem, (ox, oy))
    return icon


SPLASHES = """Diamond SMP!
Don't look into the black hole!
Spaghettification imminent!
Now with 100% more event horizon!
Diamonds are forever!
Mine diamonds at Y -58!
Branch mining is the way!
Never dig straight down!
Hawking radiation not included!
Gravity is just a suggestion!
Light can't escape. Can you?
Shiny!
The void is staring back!
Interstellar!
Ray traced sky!
Fortune III or bust!
Who stole my diamonds?
Accretion disk certified!
Beyond the event horizon!
Check your coords!
Don't forget your elytra!
Time dilation is real!
Diamond pickaxe ready!
Stay hydrated, stay shiny!
Where are the netherite upgrades?
One more diamond...
Schwarzschild approved!
3 sqrt 3 over 2!
Galaxy brain!
SMP vibes!
Respect the spawn!
Gargantua says hi!
Also try the Nether!
Night vision recommended!
Bring a totem!
"""


# ---------------------------------------------------------------------------
# Pack assembly
# ---------------------------------------------------------------------------

PACK_MCMETA = {
    "pack": {
        "description": [
            "",  # empty root so the parts below don't inherit each other's style
            {"text": "Diamond SMP ", "color": "aqua", "bold": True},
            {"text": "Black Hole Sky", "color": "light_purple"},
            {"text": "\nVanilla+ • ray traced space", "color": "gray"},
        ],
        # 1.20 (format 15) and everything newer, including 1.21.9+ min/max fields.
        "pack_format": 34,
        "supported_formats": {"min_inclusive": 15, "max_inclusive": 999},
        "min_format": 15,
        "max_format": 999,
    }
}

OVERWORLD_SKY = """# Diamond SMP - black hole skybox (overworld)
# Layout: 3x2 cube map, always visible, in every weather.
source=./blackhole_sky.png
blend=replace
rotate=false
weather=clear rain thunder
transition=1
"""

END_SKY = """# Diamond SMP - black hole skybox (the End)
source=./void_sky.png
blend=replace
rotate=false
weather=clear rain thunder
"""

SUN_PROPS = """# With the black hole skybox active, the sun becomes a distant diamond-white star.
source=./diamond_star.png
blend=add
"""


def write_text(rel, text):
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build(quick):
    face = 256 if quick else 1024
    ss = 1 if quick else 2
    bg_size = 512 if quick else 2048
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    log("starfield (overworld)")
    diamond_bg = bh.make_starfield(bg_size, 3, (0.12, 0.04, 0.35), (0.02, 0.18, 0.40), (0.25, 0.9, 0.35),
                                   n_stars=30000 if quick else 70000)

    log("overworld black hole skybox (OptiFine)")
    sky = bh.BlackHoleScene(DIAMOND, distance=22, inclination=10, roll=-14, background=diamond_bg, **DISK)
    target = bh.mc_direction(0, -24)  # due south, 24 degrees above the horizon
    img = render_optifine_sky(sky, target, face, ss, 1.0, 100)
    save(img, "optifine/sky/world0/blackhole_sky.png")
    write_text("assets/minecraft/optifine/sky/world0/sky1.properties", OVERWORLD_SKY)

    log("title screen panorama")
    pano = bh.BlackHoleScene(DIAMOND, distance=24, inclination=9, roll=-10, background=diamond_bg, seed=11, **DISK)
    render_panorama(pano, bh.mc_direction(-28, -9), face, ss, 1.0, 200)
    del diamond_bg

    log("starfield (End)")
    void_bg = bh.make_starfield(bg_size, 8, (0.30, 0.03, 0.40), (0.08, 0.05, 0.45), (0.8, 0.5, -0.2),
                                n_stars=30000 if quick else 70000)
    log("End black hole skybox (OptiFine)")
    end = bh.BlackHoleScene(VOID, distance=18, inclination=17, roll=22, background=void_bg, seed=19,
                            r_out=14, **{**DISK, "temperature": 0.78, "temp_max": 0.88})
    img = render_optifine_sky(end, bh.mc_direction(-90, -32), face, ss, 1.0, 300)
    save(img, "optifine/sky/world1/void_sky.png")
    write_text("assets/minecraft/optifine/sky/world1/sky1.properties", END_SKY)
    del void_bg

    log("vanilla sun -> black hole")
    sun = render_sun(256 if quick else 512, 1 if quick else 3)
    save(sun, "textures/environment/sun.png")             # up to 1.21.10
    save(sun, "textures/environment/celestial/sun.png")   # 1.21.11 and newer
    save(render_star_sun(256), "optifine/sky/world0/diamond_star.png")
    write_text("assets/minecraft/optifine/sky/world0/sun.properties", SUN_PROPS)

    log("vanilla End sky tile")
    save(render_end_tile(256, 4), "textures/environment/end_sky.png")

    log("OptiFine fog colour (matches the space horizon)")
    save(Image.new("RGB", (256, 256), (22, 24, 52)), "optifine/colormap/fog0.png")

    log("logo, edition, icon, splashes")
    logo = make_logo()
    save(logo, "textures/gui/title/minecraft.png")
    save(logo, "textures/gui/title/minceraft.png")
    save(make_edition(), "textures/gui/title/edition.png")
    make_icon().save(OUT / "pack.png", optimize=True)
    write_text("assets/minecraft/texts/splashes.txt", SPLASHES)
    write_text("pack.mcmeta", json.dumps(PACK_MCMETA, indent=2, ensure_ascii=False) + "\n")

    zpath = ROOT / ZIP_NAME
    if zpath.exists():
        zpath.unlink()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(OUT.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(OUT).as_posix())
    sha1 = hashlib.sha1(zpath.read_bytes()).hexdigest()
    log(f"wrote {zpath.name} ({zpath.stat().st_size / 1e6:.1f} MB, sha1 {sha1})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="fast low-resolution draft")
    build(ap.parse_args().quick)
