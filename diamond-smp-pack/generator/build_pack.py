"""Builds the Diamond SMP "Black Hole" resource pack.

    pip install numpy numba pillow
    python build_pack.py            # full quality (about 10 minutes on 4 cores)
    python build_pack.py --quick    # low-res draft

Everything in the pack is generated from scratch by this script: the skies are
ray traced through a physical black hole (blackhole.py) and lit by a physical
atmosphere (atmosphere.py); the logo and icon are drawn in code. Block, item
and mob textures are left vanilla on purpose.

The OptiFine sky is a set of layers that cross-fade over the Minecraft day:
night (space), sunrise, day, sunset, plus overcast versions for rain.
"""

import argparse
import hashlib
import json
import math
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np
from numba import njit, prange
from PIL import Image, ImageFilter

import atmosphere as atm
import blackhole as bh

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pack"
ZIP_NAME = "Diamond-SMP-Black-Hole-Pack.zip"
LITE_ZIP_NAME = "Diamond-SMP-Black-Hole-Pack-Lite.zip"
MC = OUT / "assets" / "minecraft"

# Scenes: where each black hole sits and how its disk is tilted.
OVERWORLD = dict(distance=22, inclination=10, roll=-14, t_max=26000, opacity=2.2, seed=7)
OVERWORLD_DIR = bh.mc_direction(0, -24)        # due south, 24 degrees up
PANORAMA = dict(distance=24, inclination=9, roll=-10, t_max=26000, opacity=2.2, seed=11)
PANORAMA_DIR = bh.mc_direction(-28, -9)
END = dict(distance=18, inclination=17, roll=22, r_out=14, t_max=20000, opacity=2.4, seed=19)
END_DIR = bh.mc_direction(-90, -32)             # east, high in the End sky
GALAXY = dict(galactic_north=(0.35, 0.85, 0.4), galactic_centre=(0.2, -0.3, 1.0))
# The End is lit by "ender light": push the physical colours towards violet.
END_GRADE = np.array([[0.95, 0.05, 0.30], [0.04, 0.42, 0.10], [0.30, 0.05, 1.05]])

BG_GAIN = 150.0       # stars and Milky Way are lifted like an HDR astrophoto
DISK_KEY = 1.35       # exposure: the brightest 0.3% of the disk lands here (pre-tonemap)
SKY_KEY = 0.28        # exposure for the clear day sky at the zenith
TWILIGHT_KEY = 1.3    # exposure for the brightest horizon glow at sunrise/sunset
AUREOLE = ((3.0, 0.025), (9.0, 0.04), (22.0, 0.05))      # (sigma deg, fraction) haze glow
CLOUD_GLOW = ((10.0, 0.30), (28.0, 0.40))                 # light diffusing through rain clouds


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.1f}s] {msg}", flush=True)


def save(img, rel):
    path = MC / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img)
    img.save(path, optimize=True)
    return path


def aces(x):
    """ACES filmic curve (Narkowicz fit), per channel."""
    x = np.maximum(x, 0)
    return np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)


def to8(rgb, dither_seed=None):
    return bh.quantize(bh.srgb_encode(aces(rgb)), dither_seed)


# ---------------------------------------------------------------------------
# Direction grids for the different texture layouts (with optional padding,
# so glare can be computed across face edges without seams)
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


def _grid(n, pad):
    return ((np.arange(n + 2 * pad) - pad) + 0.5) / n * 2 - 1


def optifine_tile_dirs(tile, n, pad=0):
    t = _grid(n, pad)
    lx, lz = np.meshgrid(t, t)
    local = np.stack([lx, -np.ones_like(lx), lz], -1)
    return bh.normalize(local @ OPTIFINE_TILES[tile].T)


def panorama_dirs(face, n, pad=0):
    """Vanilla title panorama: 0 front, 1 right, 2 back, 3 left, 4 up, 5 down."""
    yaw = [0, 90, 180, -90, 0, 0][face]
    pitch = [0, 0, 0, 0, -90, 90][face]
    f = bh.mc_direction(yaw, pitch)
    u = bh.mc_direction(yaw, pitch - 90)
    r = np.cross(f, u)
    t = _grid(n, pad)
    a, b = np.meshgrid(t, t)
    d = f[None, None] + a[..., None] * r[None, None] - b[..., None] * u[None, None]
    return bh.normalize(d)


def camera_dirs(w, h, half_tan_x):
    """Pinhole camera looking along scene +z (scene right is -x)."""
    xs = ((np.arange(w) + 0.5) / w * 2 - 1) * half_tan_x
    ys = ((np.arange(h) + 0.5) / h * 2 - 1) * half_tan_x * h / w
    a, b = np.meshgrid(xs, ys)
    return bh.normalize(np.stack([-a, -b, np.ones_like(a)], -1))


def render_padded(scene, w2s, dir_fn, face, ss, pad):
    """Trace one face (plus `pad` px on each side) with ss x ss supersampling."""
    n = face + 2 * pad
    out = scene.render(dir_fn(face * ss, pad * ss) @ w2s.T)
    return out.reshape(n, ss, n, ss, 7).mean(axis=(1, 3)), dir_fn(face, pad)


def crop(img, pad):
    return img[pad:img.shape[0] - pad, pad:img.shape[1] - pad] if pad else img


def upsample(img, size):
    chans = [np.array(Image.fromarray(img[..., c].astype(np.float32), "F").resize((size, size), Image.BILINEAR))
             for c in range(img.shape[-1])]
    return np.stack(chans, -1).astype(np.float64)


# ---------------------------------------------------------------------------
# Atmospheric glow around the black hole (computed on the sphere, so seamless)
# ---------------------------------------------------------------------------


@njit(parallel=True, fastmath=True)
def _glow_kernel(dirs, sdirs, sflux, sig, wts, out):
    for i in prange(dirs.shape[0]):
        dx, dy, dz = dirs[i, 0], dirs[i, 1], dirs[i, 2]
        r, g, b = 0.0, 0.0, 0.0
        for j in range(sdirs.shape[0]):
            th2 = 2.0 * (1.0 - (dx * sdirs[j, 0] + dy * sdirs[j, 1] + dz * sdirs[j, 2]))
            k = 0.0
            for s in range(sig.shape[0]):
                k += wts[s] / (2 * math.pi * sig[s] * sig[s]) * math.exp(-th2 / (2 * sig[s] * sig[s]))
            r += sflux[j, 0] * k
            g += sflux[j, 1] * k
            b += sflux[j, 2] * k
        out[i, 0] = r
        out[i, 1] = g
        out[i, 2] = b


class Emitter:
    """The black hole's disk light as a cloud of point sources (world frame)."""

    def __init__(self, scene, w2s, half_fov=40.0, res=256, bins=64):
        ht = math.tan(math.radians(half_fov))
        d = camera_dirs(res, res, ht)
        light = scene.render(d)[..., :3]
        px = 2 * ht / res
        a = -d[..., 0] / d[..., 2]
        b = -d[..., 1] / d[..., 2]
        domega = px * px / (1 + a * a + b * b) ** 1.5
        k = res // bins
        flux = (light * domega[..., None]).reshape(bins, k, bins, k, 3).sum(axis=(1, 3)).reshape(-1, 3)
        sd = bh.normalize(d.reshape(bins, k, bins, k, 3).mean(axis=(1, 3)).reshape(-1, 3))
        keep = flux @ bh.LUMA > 1e-9
        self.dirs = np.ascontiguousarray(sd[keep] @ w2s)
        self.flux = np.ascontiguousarray(flux[keep])
        self.p997 = float(np.percentile(light @ bh.LUMA, 99.7))
        self.centre = bh.normalize(w2s[2])

    def glow(self, dirs, comps):
        sig = np.array([math.radians(s) for s, _ in comps])
        wts = np.array([w for _, w in comps])
        flat = np.ascontiguousarray(dirs.reshape(-1, 3))
        out = np.zeros((flat.shape[0], 3))
        _glow_kernel(flat, self.dirs, self.flux, sig, wts, out)
        return out.reshape(*dirs.shape[:-1], 3)


# ---------------------------------------------------------------------------
# Sky textures
# ---------------------------------------------------------------------------


def airglow(dirs):
    """Faint natural glow of the night air, strongest towards the horizon."""
    s = np.clip(dirs[..., 1], 0, 1)
    return (0.0025 / (s + 0.12))[..., None] * np.array([0.45, 0.75, 0.40])


def overworld_layers(face, ss, pad, galaxy, log_prefix="  "):
    """Night / sunrise / day / sunset / overcast skies for the Overworld (OptiFine 3x2)."""
    scene = bh.BlackHoleScene(background=galaxy, **OVERWORLD)
    w2s = bh.world_to_scene(OVERWORLD_DIR)
    em = Emitter(scene, w2s)
    e_disk = DISK_KEY / em.p997

    day_suns = [atm.sun_direction(el, side) for el in (25, 45, 65, 85) for side in (1, -1)]
    skies = {
        "day": atm.SkyModel(day_suns, mie_g=0.7),
        "sunrise": atm.SkyModel([atm.sun_direction(2.0, 1)]),
        "sunset": atm.SkyModel([atm.sun_direction(2.0, -1)]),
    }
    zen = np.array([[0.0, 1.0, 0.0]])
    e_sky = {"day": SKY_KEY / float(skies["day"].radiance(zen)[0] @ bh.LUMA)}
    for name, side in (("sunrise", 1), ("sunset", -1)):
        hor = bh.normalize(np.array([[side, 0.08, 0.0]]))
        e_sky[name] = TWILIGHT_KEY / float(skies[name].radiance(hor)[0] @ bh.LUMA)
    # The black hole's brightness through the haze, relative to each sky.
    e_bh = {"night": e_disk, "day": 0.55 * e_disk, "sunrise": 0.65 * e_disk, "sunset": 0.65 * e_disk}

    names = ["night", "sunrise", "day", "sunset"]
    imgs = {n: np.zeros((2 * face, 3 * face, 3), dtype=np.uint8) for n in names}
    lo_face, lo_pad = max(face // 8, 8), max(pad // 8, 1)
    full = face + 2 * pad
    for tile in range(6):
        fn = lambda n, p: optifine_tile_dirs(tile, n, p)  # noqa: E731
        raw, world = render_padded(scene, w2s, fn, face, ss, pad)
        halo = upsample(em.glow(fn(lo_face, lo_pad), AUREOLE), full)
        trn = skies["day"].transmittance(world)
        disk, stars = raw[..., :3], raw[..., 3:6]
        r, c = divmod(tile, 3)
        for name in names:
            e = e_bh[name]
            if name == "night":  # clear night air carries less haze than daytime air
                # eyes adapt at night: the sky background is lifted twice as much
                hdr = (disk + stars * BG_GAIN * 2) * trn * e + halo * e * 0.35 + airglow(world)
            else:
                hdr = disk * trn * e + halo * e + skies[name].radiance(world) * e_sky[name]
            hdr = crop(bh.glare(hdr, scale=face / 1024), pad)
            imgs[name][r * face:(r + 1) * face, c * face:(c + 1) * face] = to8(
                hdr, 100 + tile if name == "night" else None)
        log(f"{log_prefix}overworld tile {tile + 1}/6")

    # Rain: the hole is only a diffuse glow through the clouds.
    oc = max(face // 4, 64)
    over = {n: np.zeros((2 * oc, 3 * oc, 3), dtype=np.uint8) for n in ("overcast_day", "overcast_night")}
    for tile in range(6):
        d = optifine_tile_dirs(tile, oc)
        s = np.clip(d[..., 1], 0, 1)[..., None]
        cloud = (1 + 2 * s) / 3 * np.array([0.80, 0.82, 0.86])
        glow = em.glow(d, CLOUD_GLOW) * 0.4
        r, c = divmod(tile, 3)
        over["overcast_day"][r * oc:(r + 1) * oc, c * oc:(c + 1) * oc] = to8(cloud * 0.42 + glow * e_bh["day"])
        over["overcast_night"][r * oc:(r + 1) * oc, c * oc:(c + 1) * oc] = to8(
            cloud * 0.012 + glow * e_disk * 0.35, 200 + tile)
    imgs.update(over)
    return imgs


def space_faces(scene, w2s, dir_fn, face, ss, pad, grade=None, dither=0):
    """Six faces of pure space (no atmosphere): panorama or the End."""
    em_key = DISK_KEY / Emitter(scene, w2s, res=192, bins=48).p997
    faces = []
    for k in range(6):
        fn = lambda n, p: dir_fn(k, n, p)  # noqa: E731
        raw, _ = render_padded(scene, w2s, fn, face, ss, pad)
        hdr = (raw[..., :3] + raw[..., 3:6] * BG_GAIN) * em_key
        if grade is not None:
            hdr = hdr @ grade.T
        faces.append(to8(crop(bh.glare(hdr, scale=face / 1024), pad), dither + k))
        log(f"  face {k + 1}/6")
    return faces


def render_sun(size, ss):
    """The vanilla sun becomes a small black hole (the game draws it additively)."""
    scene = bh.BlackHoleScene(distance=40, inclination=14, roll=24, r_out=9.5, seed=21, t_max=26000, opacity=2.2)
    # The sun quad is 30 units wide at distance 100: half-angle tangent 0.3.
    out = scene.render(camera_dirs(size * ss, size * ss, 0.3)).reshape(size, ss, size, ss, 7).mean(axis=(1, 3))
    disk = out[..., :3] * (DISK_KEY * 1.2 / np.percentile(out[..., :3] @ bh.LUMA, 99.7))
    t = (np.arange(size) + 0.5) / size * 2 - 1
    a, b = np.meshgrid(t, t)
    fade = np.clip((1.0 - np.sqrt(a * a + b * b)) / 0.25, 0, 1) ** 2
    srgb = bh.srgb_encode(aces(bh.glare(disk, scale=size / 1024))) * fade[..., None]
    alpha = np.maximum(srgb.max(-1), out[..., 6] * fade)
    rgb = np.where(alpha[..., None] > 1e-4, srgb / np.maximum(alpha[..., None], 1e-4), 0)
    return np.clip(np.round(np.concatenate([rgb, alpha[..., None]], -1) * 255), 0, 255).astype(np.uint8)


def render_real_sun(size):
    """OptiFine sun: a limb-darkened 5800 K disc with atmospheric glare."""
    t = (np.arange(size) + 0.5) / size * 2 - 1
    a, b = np.meshgrid(t, t)
    theta = np.degrees(np.arctan(0.3 * np.sqrt(a * a + b * b)))
    radius = 1.4  # degrees (the real sun is 0.27; enlarged so it reads in game)
    mu = np.sqrt(np.clip(1 - (theta / radius) ** 2, 0, 1))
    disc = np.where(theta < radius, 1 - 0.6 * (1 - mu), 0) * 40.0
    halo = 1.2 * np.exp(-theta / 0.9) + 0.25 * np.exp(-theta / 3.5) + 0.05 * np.exp(-theta / 10)
    rgb = (disc + halo)[..., None] * bh.blackbody_colour(5800.0)
    rgb *= np.clip((16.0 - theta) / 3.0, 0, 1)[..., None]
    return to8(rgb)


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
    tint = bh.blackbody_colour(rng.choice([4000, 6500, 9000, 16000, 25000], n).astype(float))
    for x, y, v, c in zip(xs, ys, br, tint):
        x0, y0 = int(x), int(y)
        for dy in (-1, 0, 1, 2):
            for dx in (-1, 0, 1, 2):
                px, py = (x0 + dx) % size, (y0 + dy) % size
                d2 = (x0 + dx + 0.5 - x) ** 2 + (y0 + dy + 0.5 - y) ** 2
                img[py, px] += c * v * math.exp(-d2 / 0.5)
    return to8(img * 2.2, seed)


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
    galaxy = bh.make_galaxy(256, 41, (0.3, 0.8, 0.5), (0.4, -0.5, 1.0), n_stars=8000)
    scene = bh.BlackHoleScene(distance=17, inclination=12, roll=-18, r_out=11, seed=33, t_max=26000,
                              opacity=2.2, background=galaxy)
    ss = 3
    out = scene.render(camera_dirs(size * ss, size * ss, math.tan(math.radians(36))))
    out = out.reshape(size, ss, size, ss, 7).mean(axis=(1, 3))
    e = DISK_KEY / np.percentile(out[..., :3] @ bh.LUMA, 99.7)
    hdr = (out[..., :3] + out[..., 3:6] * BG_GAIN) * e
    icon = Image.fromarray(to8(bh.glare(hdr, scale=size / 1024), 3)).convert("RGBA")
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
            {"text": "\nRealistic day & night • ray traced", "color": "gray"},
        ],
        # 1.20 (format 15) and everything newer, including 1.21.9+ min/max fields.
        "pack_format": 34,
        "supported_formats": {"min_inclusive": 15, "max_inclusive": 999},
        "min_format": 15,
        "max_format": 999,
    }
}

# (texture, description, (startFadeIn, endFadeIn, endFadeOut), weather). Order matters:
# later layers are drawn over earlier ones while they fade.
OVERWORLD_LAYERS = [
    ("night", "Night: deep space, the Milky Way and the black hole", ("18:15", "19:15", "05:45"), "clear"),
    ("sunrise", "Sunrise: physical sky, sun rising in the east", ("04:30", "05:30", "07:45"), "clear"),
    ("day", "Day: blue sky, the black hole shining through the haze", ("06:15", "07:30", "18:00"), "clear"),
    ("sunset", "Sunset: physical sky, sun setting in the west", ("16:15", "17:15", "19:30"), "clear"),
    ("overcast_day", "Rain by day: the black hole glows behind the clouds", ("05:00", "06:30", "19:00"),
     "rain thunder"),
    ("overcast_night", "Rain by night: a faint glow behind the clouds", ("17:15", "18:45", "06:45"),
     "rain thunder"),
]


def layer_props(name, comment, fades, weather):
    return (f"# Diamond SMP - {comment}\n"
            f"source=./{name}.png\nblend=alpha\nrotate=false\n"
            f"startFadeIn={fades[0]}\nendFadeIn={fades[1]}\nendFadeOut={fades[2]}\n"
            f"weather={weather}\ntransition=3\n")


END_SKY = """# Diamond SMP - black hole skybox (the End)
source=./void_sky.png
blend=replace
rotate=false
weather=clear rain thunder
"""

SUN_PROPS = """# The black hole is its own object in the sky, so the sun is a real sun again.
source=./sun.png
blend=add
"""


def write_text(rel, text, root=OUT):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def zip_dir(src, zpath):
    if zpath.exists():
        zpath.unlink()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(src).as_posix())
    sha1 = hashlib.sha1(zpath.read_bytes()).hexdigest()
    log(f"wrote {zpath.name} ({zpath.stat().st_size / 1e6:.1f} MB, sha1 {sha1})")


def is_big_sky_texture(rel):
    rel = rel.as_posix()
    return ((rel.startswith("optifine/sky/") and not rel.endswith("/sun.png"))
            or rel.startswith("textures/gui/title/background/panorama_")
            or rel in ("textures/environment/sun.png", "textures/environment/celestial/sun.png"))


def make_lite():
    """Same pack with every sky texture at half resolution (a quarter of the VRAM)."""
    with tempfile.TemporaryDirectory() as tmp:
        lite = Path(tmp) / "pack"
        shutil.copytree(OUT, lite)
        mc = lite / "assets" / "minecraft"
        for p in sorted(mc.rglob("*.png")):
            if is_big_sky_texture(p.relative_to(mc)):
                im = Image.open(p)
                im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save(p, optimize=True)
        meta = json.loads(json.dumps(PACK_MCMETA))
        meta["pack"]["description"][2]["text"] = "Black Hole Sky Lite"
        write_text("pack.mcmeta", json.dumps(meta, indent=2, ensure_ascii=False) + "\n", root=lite)
        zip_dir(lite, ROOT / LITE_ZIP_NAME)


def build(quick):
    face = 256 if quick else 1024
    ss = 1 if quick else 2
    pad = face // 8
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    log("galaxy (stars, Milky Way, dust, nebulae)")
    galaxy = bh.make_galaxy(512 if quick else 2048, 3, n_stars=40000 if quick else 220000, star_flux=1.1, **GALAXY)

    log("overworld sky layers (OptiFine)")
    imgs = overworld_layers(face, ss, pad, galaxy)
    for i, (name, comment, fades, weather) in enumerate(OVERWORLD_LAYERS, 1):
        save(imgs[name], f"optifine/sky/world0/{name}.png")
        write_text(f"assets/minecraft/optifine/sky/world0/sky{i}.properties", layer_props(name, comment, fades, weather))
    save(render_real_sun(256), "optifine/sky/world0/sun.png")
    write_text("assets/minecraft/optifine/sky/world0/sun.properties", SUN_PROPS)

    log("title screen panorama")
    pano = bh.BlackHoleScene(background=galaxy, **PANORAMA)
    for k, img in enumerate(space_faces(pano, bh.world_to_scene(PANORAMA_DIR), panorama_dirs, face, ss, pad,
                                        dither=300)):
        save(img, f"textures/gui/title/background/panorama_{k}.png")

    log("End black hole skybox (OptiFine)")
    end = bh.BlackHoleScene(background=galaxy, **END)
    tiles = space_faces(end, bh.world_to_scene(END_DIR), optifine_tile_dirs, face, ss, pad,
                        grade=END_GRADE, dither=400)
    sky = np.zeros((2 * face, 3 * face, 3), dtype=np.uint8)
    for t, img in enumerate(tiles):
        r, c = divmod(t, 3)
        sky[r * face:(r + 1) * face, c * face:(c + 1) * face] = img
    save(sky, "optifine/sky/world1/void_sky.png")
    write_text("assets/minecraft/optifine/sky/world1/sky1.properties", END_SKY)
    del galaxy

    log("vanilla sun -> black hole")
    sun = render_sun(256 if quick else 512, 1 if quick else 3)
    save(sun, "textures/environment/sun.png")             # up to 1.21.10
    save(sun, "textures/environment/celestial/sun.png")   # 1.21.11 and newer

    log("vanilla End sky tile, logo, edition, icon, splashes")
    save(render_end_tile(256, 4), "textures/environment/end_sky.png")
    logo = make_logo()
    save(logo, "textures/gui/title/minecraft.png")
    save(logo, "textures/gui/title/minceraft.png")
    save(make_edition(), "textures/gui/title/edition.png")
    make_icon().save(OUT / "pack.png", optimize=True)
    write_text("assets/minecraft/texts/splashes.txt", SPLASHES)
    write_text("pack.mcmeta", json.dumps(PACK_MCMETA, indent=2, ensure_ascii=False) + "\n")

    zip_dir(OUT, ROOT / ZIP_NAME)
    make_lite()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="fast low-resolution draft")
    build(ap.parse_args().quick)
