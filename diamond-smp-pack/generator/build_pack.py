"""Builds the Diamond SMP "Black Hole" resource pack.

    pip install numpy numba pillow
    python build_pack.py            # full quality (about 10 minutes on 4 cores)
    python build_pack.py --quick    # low-res draft

Everything in the pack is generated from scratch by this script: the skies are
ray traced through a physical black hole (kerr.py) and lit by a physical
atmosphere (atmosphere.py); the logo and icon are drawn in code. Block, item
and mob textures are left vanilla on purpose.

The OptiFine sky is a set of layers that cross-fade over the Minecraft day:
night (space: the black hole, the real stars, the Milky Way and the northern
lights), sunrise, day and sunset (the clean physical sky, no black hole), plus
overcast versions for rain. The hole fades in at dusk with the night layer.
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
import celestial
import earth
import kerr
import real_sky

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pack"
ZIP_NAME = "Diamond-SMP-Black-Hole-Pack.zip"
LITE_ZIP_NAME = "Diamond-SMP-Black-Hole-Pack-Lite.zip"
MC = OUT / "assets" / "minecraft"

# Scenes: where the black hole sits and how its disk is tilted. Lengths are in units of
# the hole's mass M; spin a/M = 0.9 makes it a rotating (Kerr) black hole, like Gargantua.
SPIN = 0.9
OVERWORLD = dict(spin=SPIN, distance=44, inclination=10, roll=-14, r_out=26, t_max=26000, opacity=2.2, seed=7)
OVERWORLD_DIR = real_sky.SGR_A_WORLD            # the hole IS Sagittarius A*: due south, 24 degrees up
PANORAMA = dict(spin=SPIN, distance=48, inclination=9, roll=-10, r_out=26, t_max=26000, opacity=2.2, seed=11)
PANORAMA_DIR = bh.mc_direction(-28, -9)
END = dict(spin=SPIN, distance=36, inclination=17, roll=22, r_out=28, t_max=20000, opacity=2.4, seed=19)
END_DIR = bh.mc_direction(-90, -32)             # east, high in the End sky
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


# ---------------------------------------------------------------------------
# Northern lights (aurora borealis) in the night sky
# ---------------------------------------------------------------------------
#
# The aurora is light given off 100-300 km up by oxygen atoms and nitrogen molecules
# hit by electrons that rain down along the magnetic field lines. It is modelled as a
# few thin emitting sheets ("curtains") hanging over the ground far to the north:
#
# * Geometry: each curtain runs east-west at a distance d north of the player, bends
#   away along the auroral oval, meanders, and folds back over itself where its
#   fold steepness kappa * amplitude > 1 (Kelvin-Helmholtz-like S-folds). Across the
#   sheet the emission is a Gaussian a few km thick. Field lines are nearly vertical
#   at auroral latitudes, so the sheets are vertical. A view ray sees the line integral
#   of the emission through every sheet it crosses, so a fold seen edge-on glows
#   brightest, as in photographs. Points are placed on a curved Earth, which makes the
#   far ends of every arc sink smoothly into the horizon. The display spans ~140 degrees
#   of the northern sky, its lower borders 5-30 degrees up and its tops up to ~60.
# * Fine rays: across the sheet the brightness is broken into strands 1-5 km wide (a
#   few tenths of a degree seen from the ground) that run along the field lines; each
#   strand reaches its own height.
# * Colour comes from the altitude: the O 557.7 nm green starts at a sharp lower border
#   about 100 km up and fades upwards; the O 630.0 nm red takes over at 200-300 km
#   (its 110 s lifetime smears it, so it does not show the fine rays); a trace of N2+
#   427.8 nm violet on the sunlit tops; on some stretches a thin pink/magenta N2 fringe
#   just under the lower border, where the electrons are most energetic.
#
# Rendering: for every azimuth column the horizontal line of sight is marched once and
# the stretches where it crosses a sheet are stored as short chunks (distance, weights,
# local border height). A pixel at elevation e then sums its column's chunks, each one
# seen at height h(r, e) on the curved Earth, with path length 1 / cos(e) through the
# vertical sheet. The result is linear radiance, added in front of the stars before
# atmospheric extinction and tone mapping.

AURORA_GREEN = np.array([0.20, 1.00, 0.45])    # O(1S) 557.7 nm
AURORA_RED = np.array([1.00, 0.12, 0.18])      # O(1D) 630.0 nm
AURORA_VIOLET = np.array([0.45, 0.22, 1.00])   # N2+ 427.8 nm, resonance-scattered sunlight on the tops
AURORA_PINK = np.array([1.00, 0.32, 0.72])     # N2 first positive (red) + N2+ (blue) lower-border fringe
AURORA_GAIN = 0.24       # radiance scale (pre-tonemap): a brightness-1 curtain seen face-on at its border
AURORA_SAT = 0.20        # soft ceiling of the green (pre-tonemap): edge-on folds stay below ~0.5 on screen
AURORA_SIGMA = 1.4       # sheet half-thickness (Gaussian sigma, km)
AURORA_DR = 0.35         # march step along the line of sight (km)
AURORA_CHUNK = 1.2       # longest stretch of a crossing stored as one chunk (km)
AURORA_R = (40.0, 2150.0)   # range of horizontal distances marched (km); beyond, 300 km is below the horizon
AURORA_AZ = 100.0        # columns cover azimuths -100..100 degrees (north = 0, east > 0)
AURORA_SPAN = (50.0, 76.0)  # the display fades out between these azimuths (east and west of north)
AURORA_MAX_CHUNKS = 512    # per column; the busiest columns (edge-on folds) need ~300
R_EARTH_KM = 6371.0
OBSERVER_KM = 0.2

# One row per curtain: distance north d (km), arc centre x0 (km east), half length (km),
# brightness, oval radius (km), meander amplitude / wavelength (km), fold amplitude /
# wavelength (km), fold steepness kappa (1/km), curl amplitude / wavelength (km),
# lower border height (km), fringe (0..1, how much pink fringe), seed.
AURORA_CURTAINS = np.array([
    #  d     x0    half   bright oval    mea  mwl    fold  fwl   kappa  curl cwl  h0     fringe seed
    [235., -150., 900., 0.50, 4500., 55., 900., 65., 380., 0.021, 2.0, 26., 104.0, 0.0, 11.],
    [330., 60., 1400., 1.00, 6000., 70., 1100., 85., 430., 0.017, 2.6, 34., 99.0, 1.0, 12.],
    [480., -60., 1500., 0.65, 8000., 60., 1000., 60., 400., 0.020, 2.6, 40., 100.0, 0.5, 13.],
    [650., 160., 1600., 0.42, 10000., 45., 1000., 40., 420., 0.022, 2.4, 44., 102.0, 0.0, 14.],
])


@njit(inline="always")
def _hash1(i, seed):
    h = (i * 374761393 + seed * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return (h & 0xFFFFFF) / 16777215.0


@njit(inline="always")
def _noise1(x, seed):
    """Smooth 1D value noise in [0, 1] (quintic fade, so the curtains have no kinks)."""
    i = math.floor(x)
    t = x - i
    t = t * t * t * (t * (t * 6 - 15) + 10)
    i = int(i)
    a = _hash1(i, seed)
    return a + (_hash1(i + 1, seed) - a) * t


@njit(inline="always")
def _curtain_field(c, x, n):
    """Implicit curtain: F(x, n) = 0 on the sheet (x km east, n km north). Also returns
    the along-sheet coordinate u (km), which follows the sheet through its folds."""
    seed = int(c[14])
    m = c[0] + x * x / (2.0 * c[4]) + c[5] * (2.0 * _noise1(x / c[6], seed) - 1.0)
    y = n - m
    # the fold amplitude waxes and wanes along the arc: some stretches fold, some are smooth
    amp = c[7] * (0.25 + 1.1 * _noise1(x / (1.7 * c[8]) + 3.1, seed + 1))
    k = 2.0 * math.pi / c[8]
    theta = k * x + 6.2831853 * _noise1(x / 900.0, seed + 2) + c[9] * y
    f = y - amp * math.sin(theta) - c[10] * math.sin(2.0 * math.pi * x / c[11] + 1.3 * seed)
    return f, theta / k


@njit(inline="always")
def _aurora_flush(out, ci, nch, wsum, wr, wf, wd, wh0, whg, wfr):
    if wsum > 0.0 and nch < out.shape[1]:
        out[ci, nch, 0] = wr / wsum
        out[ci, nch, 1] = wf
        out[ci, nch, 2] = wd
        out[ci, nch, 3] = wh0 / wsum
        out[ci, nch, 4] = whg / wsum
        out[ci, nch, 5] = wfr / wsum
        return nch + 1
    return nch


@njit(parallel=True)
def _aurora_columns(az, curt, r0, r1, dr, chunk, sigma, span0, span1, out, count):
    """March the horizontal line of sight of every azimuth column through the curtains."""
    norm = 1.0 / (math.sqrt(2.0 * math.pi) * sigma)
    cut = 3.2 * sigma
    eps = 0.02
    for ci in prange(az.shape[0]):
        sa, ca = math.sin(az[ci]), math.cos(az[ci])
        # this display spans ~140 degrees of the northern sky and fades out softly at its sides
        aw = min(max((span1 - abs(math.degrees(az[ci]))) / (span1 - span0), 0.0), 1.0)
        aw = aw * aw * (3.0 - 2.0 * aw)
        if aw <= 0.0:
            count[ci] = 0
            continue
        nch = 0
        for k in range(curt.shape[0]):
            c = curt[k]
            seed = int(c[14])
            wsum = wr = wf = wd = wh0 = whg = wfr = 0.0
            start = -1.0
            r = r0
            while r < r1:
                x, n = r * sa, r * ca
                f, u = _curtain_field(c, x, n)
                inside = False
                if abs(f) < 6.0 * cut:
                    fx = (_curtain_field(c, x + eps, n)[0] - f) / eps
                    fn = (_curtain_field(c, x, n + eps)[0] - f) / eps
                    s = f / max(math.sqrt(fx * fx + fn * fn), 1e-3)  # distance to the sheet (km)
                    if abs(s) < cut:
                        inside = True
                        # brightness along the arc: soft ends, slow surges and patches
                        q = (x - c[1]) / c[2]
                        win = min(max((1.0 - abs(q)) / 0.6, 0.0), 1.0)
                        win = win * win * (3.0 - 2.0 * win)
                        slow = 0.2 + 0.8 * _noise1(x / 240.0, seed + 3) ** 1.5
                        patch = 0.55 + 0.9 * _noise1(x / 70.0, seed + 4) ** 2
                        b = c[3] * win * slow * patch * aw
                        # fine rays (strands along the field lines) across the sheet
                        s1 = _noise1(u / 1.3, seed + 5)
                        s2 = _noise1(u / 4.0, seed + 6)
                        s3 = _noise1(u / 11.0, seed + 7)
                        ray = 0.3 + s2 * s2 * (0.5 + 1.8 * s1 ** 3) + 0.35 * s3
                        g = math.exp(-0.5 * (s / sigma) ** 2) * norm * dr
                        w = g * b
                        if w > 0.0:
                            if start < 0.0:
                                start = r
                            h0 = c[12] + 7.0 * (_noise1(x / 160.0, seed + 8) - 0.5) + 2.5 * (s2 - 0.5)
                            hg = 10.0 + 32.0 * (0.6 * s2 + 0.4 * s1) ** 1.5 * (0.6 + 0.8 * s3)
                            fr = c[13] * min(max((_noise1(x / 130.0, seed + 9) - 0.45) * 4.0, 0.0), 1.0)
                            wsum += w
                            wr += w * r
                            wf += w * ray
                            wd += w * (0.55 + 0.45 * s3)
                            wh0 += w * h0
                            whg += w * hg
                            wfr += w * fr
                            if r - start >= chunk:
                                nch = _aurora_flush(out, ci, nch, wsum, wr, wf, wd, wh0, whg, wfr)
                                wsum = wr = wf = wd = wh0 = whg = wfr = 0.0
                                start = -1.0
                if not inside and wsum > 0.0:
                    nch = _aurora_flush(out, ci, nch, wsum, wr, wf, wd, wh0, whg, wfr)
                    wsum = wr = wf = wd = wh0 = whg = wfr = 0.0
                    start = -1.0
                # far from this sheet, stride faster: |grad F| stays below ~4 (8 allowed for),
                # so a stride never jumps over the band |F| < 6 cut examined above
                r += dr if abs(f) < 8.0 * cut else max(dr, 0.12 * (abs(f) - 6.0 * cut))
            nch = _aurora_flush(out, ci, nch, wsum, wr, wf, wd, wh0, whg, wfr)
        count[ci] = nch


@njit(parallel=True, fastmath=True)
def _aurora_pixels(dirs, az0, daz, cols, count, green, red, violet, pink, out):
    rr = R_EARTH_KM + OBSERVER_KM
    for i in prange(dirs.shape[0]):
        dx, dy, dz = dirs[i, 0], dirs[i, 1], dirs[i, 2]
        out[i, 0] = out[i, 1] = out[i, 2] = 0.0
        ch = math.sqrt(dx * dx + dz * dz)  # cos(elevation)
        if dy <= 0.0 or ch < 1e-4:
            continue
        fa = (math.atan2(dx, -dz) - az0) / daz
        if fa < 0.0 or fa > count.shape[0] - 1.001:
            continue
        j = int(fa)
        ta = fa - j
        tan_e = dy / ch
        acc_r = acc_g = acc_b = 0.0
        for side in range(2):
            col = j + side
            wcol = (1.0 - ta) if side == 0 else ta
            if wcol <= 0.0:
                continue
            for k in range(count[col]):
                r = cols[col, k, 0]
                y = r * tan_e
                h = math.sqrt(r * r + (rr + y) * (rr + y)) - R_EARTH_KM
                if h > 460.0:
                    continue
                z = h - cols[col, k, 3]
                if z < -9.0:
                    continue
                wf = cols[col, k, 1] * wcol
                wd = cols[col, k, 2] * wcol
                # green: sharp lower border, fading upwards over the strand's own height
                edge = 1.0 / (1.0 + math.exp(-z / 0.8))
                zp = max(z, 0.0)
                gr = edge * (0.35 * math.exp(-zp / 5.0) + 0.55 * math.exp(-zp / cols[col, k, 4])
                             + 0.10 * math.exp(-zp / (2.0 * cols[col, k, 4])))
                # pink fringe just under the border
                pk = cols[col, k, 5] * 0.8 * math.exp(-((z + 2.4) / 2.0) ** 2)
                # diffuse red tops and a trace of sunlit violet
                hr = (h - 140.0) / 70.0
                rd = 0.0
                if hr > 0.0:
                    hr = min(hr, 1.0)
                    rd = 0.055 * hr * hr * (3.0 - 2.0 * hr) * math.exp(-max(h - 240.0, 0.0) / 70.0)
                hv = min(max((h - 210.0) / 70.0, 0.0), 1.0)
                vi = 0.035 * hv * hv * (3.0 - 2.0 * hv) * math.exp(-max(h - 300.0, 0.0) / 60.0)
                a_g = wf * gr
                a_p = wf * pk
                a_r = wd * rd * edge
                a_v = wd * vi
                acc_r += a_g * green[0] + a_p * pink[0] + a_r * red[0] + a_v * violet[0]
                acc_g += a_g * green[1] + a_p * pink[1] + a_r * red[1] + a_v * violet[1]
                acc_b += a_g * green[2] + a_p * pink[2] + a_r * red[2] + a_v * violet[2]
        inv = 1.0 / ch  # path length through a vertical sheet grows as 1 / cos(elevation)
        out[i, 0] = acc_r * inv
        out[i, 1] = acc_g * inv
        out[i, 2] = acc_b * inv


class Aurora:
    """The northern lights as linear sky radiance (world frame, before extinction)."""

    def __init__(self, curtains=AURORA_CURTAINS, az_step_deg=0.04, gain=AURORA_GAIN, sat=AURORA_SAT):
        n = int(round(2 * AURORA_AZ / az_step_deg)) + 1
        self.az = np.radians(np.linspace(-AURORA_AZ, AURORA_AZ, n))
        self.cols = np.zeros((n, AURORA_MAX_CHUNKS, 6), dtype=np.float32)
        self.count = np.zeros(n, dtype=np.int64)
        _aurora_columns(self.az, np.ascontiguousarray(curtains, dtype=np.float64), AURORA_R[0], AURORA_R[1],
                        AURORA_DR, AURORA_CHUNK, AURORA_SIGMA, AURORA_SPAN[0], AURORA_SPAN[1], self.cols, self.count)
        if self.count.max() >= AURORA_MAX_CHUNKS:
            log(f"  warning: aurora column overflow ({self.count.max()} chunks), raise AURORA_MAX_CHUNKS")
        self.gain, self.sat = gain, sat

    def radiance(self, dirs):
        flat = np.ascontiguousarray(dirs.reshape(-1, 3), dtype=np.float64)
        out = np.zeros((flat.shape[0], 3))
        _aurora_pixels(flat, self.az[0], self.az[1] - self.az[0], self.cols, self.count,
                       AURORA_GREEN, AURORA_RED, AURORA_VIOLET, AURORA_PINK, out)
        out *= self.gain
        # Exposure roll-off: a fold seen edge-on is tens of times brighter than the sheet
        # seen face-on; compress it (hue kept) like a photo of a bright display.
        g = np.maximum(out.max(axis=1), 1e-12)
        out *= (self.sat * -np.expm1(-g / self.sat) / g)[:, None]
        return out.reshape(*dirs.shape[:-1], 3)


def daytime_skies():
    """Sky models and exposures of the daytime layers: {name: (SkyModel, exposure)}."""
    day_suns = [atm.sun_direction(el, side) for el in (25, 45, 65, 85) for side in (1, -1)]
    skies = {
        "day": atm.SkyModel(day_suns, mie_g=0.7),
        "sunrise": atm.SkyModel([atm.sun_direction(2.0, 1)]),
        "sunset": atm.SkyModel([atm.sun_direction(2.0, -1)]),
    }
    zen = np.array([[0.0, 1.0, 0.0]])
    out = {"day": (skies["day"], SKY_KEY / float(skies["day"].radiance(zen)[0] @ bh.LUMA))}
    for name, side in (("sunrise", 1), ("sunset", -1)):
        hor = bh.normalize(np.array([[side, 0.08, 0.0]]))
        out[name] = (skies[name], TWILIGHT_KEY / float(skies[name].radiance(hor)[0] @ bh.LUMA))
    return out


def overworld_layers(face, ss, pad, galaxy, log_prefix="  "):
    """Night / sunrise / day / sunset / overcast skies for the Overworld (OptiFine 3x2).

    By day the sky is just the physical atmosphere (the sun is the game's own sprite).
    The black hole belongs to the night: the night layer shows it with the real stars,
    the Milky Way and the northern lights in the north, and it fades in at dusk as the
    night layer cross-fades in under the sunset (see OVERWORLD_LAYERS)."""
    scene = kerr.KerrScene(background=galaxy, **OVERWORLD)
    w2s = bh.world_to_scene(OVERWORLD_DIR)
    em = Emitter(scene, w2s)
    e_disk = DISK_KEY / em.p997
    aurora = Aurora()
    log(f"{log_prefix}northern lights: {int(aurora.count.sum())} curtain crossings")
    daytime = daytime_skies()
    clear_air = daytime["day"][0]  # transmittance of the whole atmosphere (independent of the sun)

    names = ["night", "sunrise", "day", "sunset"]
    imgs = {n: np.zeros((2 * face, 3 * face, 3), dtype=np.uint8) for n in names}
    lo_face, lo_pad = max(face // 8, 8), max(pad // 8, 1)
    full = face + 2 * pad
    for tile in range(6):
        fn = lambda n, p: optifine_tile_dirs(tile, n, p)  # noqa: E731
        raw, world = render_padded(scene, w2s, fn, face, ss, pad)
        halo = upsample(em.glow(fn(lo_face, lo_pad), AUREOLE), full)
        trn = clear_air.transmittance(world)
        disk, stars = raw[..., :3], raw[..., 3:6]
        r, c = divmod(tile, 3)
        for name in names:
            if name == "night":
                # Clear night air carries less haze than daytime air, and eyes adapt at night:
                # the sky background is lifted twice as much. The aurora glows 100-300 km up,
                # in front of the stars, and is dimmed by the same air near the horizon.
                hdr = ((disk + stars * BG_GAIN * 2) * trn * e_disk + halo * e_disk * 0.35 + airglow(world)
                       + aurora.radiance(world) * trn)
            else:
                sky, e_sky = daytime[name]
                hdr = sky.radiance(world) * e_sky
            hdr = crop(bh.glare(hdr, scale=face / 1024), pad)
            imgs[name][r * face:(r + 1) * face, c * face:(c + 1) * face] = to8(
                hdr, 100 + tile if name == "night" else None)
        log(f"{log_prefix}overworld tile {tile + 1}/6")

    # Rain: an overcast sky (CIE overcast luminance: brighter towards the zenith). At
    # night the hole is only a diffuse glow through the clouds; they hide the aurora.
    oc = max(face // 4, 64)
    over = {n: np.zeros((2 * oc, 3 * oc, 3), dtype=np.uint8) for n in ("overcast_day", "overcast_night")}
    for tile in range(6):
        d = optifine_tile_dirs(tile, oc)
        s = np.clip(d[..., 1], 0, 1)[..., None]
        cloud = (1 + 2 * s) / 3 * np.array([0.80, 0.82, 0.86])
        glow = em.glow(d, CLOUD_GLOW) * 0.4
        r, c = divmod(tile, 3)
        over["overcast_day"][r * oc:(r + 1) * oc, c * oc:(c + 1) * oc] = to8(cloud * 0.42)
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
    scene = kerr.KerrScene(spin=SPIN, distance=34, inclination=12, roll=-18, r_out=22, seed=33, t_max=26000,
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
Northern lights tonight!
557.7 nanometres of green!
Look north after dark!
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
            {"text": "\nBlack hole by night • northern lights • real stars", "color": "gray"},
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
# The black hole is only in the night layers. The clear night layer sits under the sunset
# layer, which stays fully opaque until 18:30 (the sun sets at 18:47), so the hole and
# the northern lights appear only as the sunset fades out (~15% at sunset, full at
# 19:30), long after the day layer has gone (18:00); at dawn they fade out under the
# sunrise (sun up at 05:13) before the day layer starts. The rain-night layer is drawn
# over the rain-day layer, so it starts fading in only when that one starts fading out
# (17:30).
OVERWORLD_LAYERS = [
    ("night", "Night: deep space, the Milky Way, the black hole and the northern lights",
     ("18:15", "19:15", "05:45"), "clear"),
    ("sunrise", "Sunrise: physical sky, sun rising in the east", ("04:30", "05:30", "07:45"), "clear"),
    ("day", "Day: clear blue physical sky (the black hole only comes out at night)", ("06:15", "07:30", "18:00"),
     "clear"),
    ("sunset", "Sunset: physical sky, sun setting in the west", ("16:15", "17:15", "19:30"), "clear"),
    ("overcast_day", "Rain by day: a plain overcast sky", ("05:00", "06:30", "19:00"), "rain thunder"),
    ("overcast_night", "Rain by night: the black hole a faint glow behind the clouds", ("17:30", "18:45", "06:30"),
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
    return (rel.startswith("optifine/sky/")
            or rel.startswith("textures/gui/title/background/panorama_")
            or rel.startswith("textures/environment/celestial/")
            or rel in ("textures/environment/sun.png", "textures/environment/moon_phases.png"))


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
    # The real sky: 8,800 catalogue stars at their true positions for latitude 37 N with
    # Sagittarius A* on the meridian, procedural stars below magnitude 6.6, and the Milky Way
    # along the true galactic plane with its centre right behind the black hole.
    galaxy = bh.make_galaxy(512 if quick else 2048, 3, n_stars=40000 if quick else 220000, star_flux=4.5,
                            diffuse=0.0065,
                            **real_sky.make_galaxy_kwargs(bh.world_to_scene(OVERWORLD_DIR)))

    log("overworld sky layers (OptiFine)")
    imgs = overworld_layers(face, ss, pad, galaxy)
    for i, (name, comment, fades, weather) in enumerate(OVERWORLD_LAYERS, 1):
        save(imgs[name], f"optifine/sky/world0/{name}.png")
        write_text(f"assets/minecraft/optifine/sky/world0/sky{i}.properties", layer_props(name, comment, fades, weather))

    log("title screen panorama")
    pano = kerr.KerrScene(background=galaxy, **PANORAMA)
    for k, img in enumerate(space_faces(pano, bh.world_to_scene(PANORAMA_DIR), panorama_dirs, face, ss, pad,
                                        dither=300)):
        save(img, f"textures/gui/title/background/panorama_{k}.png")

    log("End black hole skybox (OptiFine)")
    end = kerr.KerrScene(background=galaxy, **END)
    tiles = space_faces(end, bh.world_to_scene(END_DIR), optifine_tile_dirs, face, ss, pad,
                        grade=END_GRADE, dither=400)
    sky = np.zeros((2 * face, 3 * face, 3), dtype=np.uint8)
    for t, img in enumerate(tiles):
        r, c = divmod(t, 3)
        sky[r * face:(r + 1) * face, c * face:(c + 1) * face] = img
    save(sky, "optifine/sky/world1/void_sky.png")
    write_text("assets/minecraft/optifine/sky/world1/sky1.properties", END_SKY)
    del galaxy

    log("photorealistic sun, and the Earth in place of the moon")
    res = 256 if quick else 512
    sun = celestial.make_sun(res)
    save(sun, "textures/environment/sun.png")             # up to 1.21.10
    save(sun, "textures/environment/celestial/sun.png")   # 1.21.11 and newer
    # The moon's eight phases become the Earth seen from space: same phase angles and lit
    # sides, a different face of the turning planet each night, city lights on the dark side.
    phases = earth.make_earth_phases(res, map_width=1024 if quick else 2048)
    for name, img in phases.items():
        save(img, f"textures/environment/celestial/moon/{name}.png")
    save(celestial.moon_phase_sheet(phases), "textures/environment/moon_phases.png")

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
