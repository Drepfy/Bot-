"""Diamond SMP Shader Sky: the black hole and the real night sky, drawn LIVE by vanilla shaders.

    python shader_sky.py            # writes ../Diamond-SMP-Shader-Sky.zip and the Lite zip, then checks them
    python shader_sky.py --preview  # also renders WebGL previews into ../previews/

No mods needed. The add-on replaces two of Minecraft's own core shaders:

* sky.vsh/fsh draws the flat sky disc above the camera. Pixels near Sagittarius A*
  (due south, 24 degrees up) trace a light ray through a Schwarzschild black hole
  on the GPU: the shadow, the photon ring, a thin Novikov-Thorne disk glowing as a
  blackbody with exact Doppler/gravitational redshift and limb darkening, and gas
  streaks that ORBIT in real time (inner gas faster, driven by the game clock).
  It shows day and night, like the Moon.
* stars.vsh/fsh normally draws ~1500 white squares. Diamond SMP turns that pass
  into one full-screen layer that paints the real night sky instead: the ~900
  brightest stars of the Yale Bright Star Catalogue at their true places and
  colours, faint stars that crowd into the Milky Way, the Milky Way itself with
  dust lanes and pink nebulae, twinkling and atmospheric extinction near the
  horizon. Every pixel is bent by the hole's gravity (an exact lens table), so the
  galactic bulge behind it wraps into an Einstein ring. It fades in at dusk and
  disappears in rain exactly when vanilla's stars would.

The shaders differ between Minecraft versions, so each zip carries one copy per
shader layout in pack overlays (1.21.9-1.21.11, 26.1-26.2, 26.3).
"""

import json
import math
import re
import shutil
import subprocess
import sys
import zipfile
from functools import lru_cache
from pathlib import Path
from string import Template

import numpy as np

import blackhole as bh
import real_sky

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VANILLA = HERE / ".cache" / "vanilla"

# Same black hole as the pack's skybox textures, in Schwarzschild radii (r_s = 2M).
BH_DIR = bh.normalize(real_sky.SGR_A_WORLD)   # Sagittarius A*: due south, 24 degrees up
DISTANCE = 22.0
INCLINATION = 10.0
ROLL = -14.0
R_IN, R_OUT = 3.0, 13.0
T_MAX = 26000.0
OPACITY = 2.2
DISK_KEY = 1.35                            # brightest 0.3% of the disk -> this, before the filmic curve
FLOW = 9.0                                 # how far the gas orbits per animation cycle
TIME_SCALE = 150.0                         # animation cycles per Minecraft day (~8 s per cycle)

# Night sky
LENS_N = 128                               # lens table entries
LENS_X0 = math.log(3e-4)                   # table starts this close to the shadow edge (log scale)
CELLS = 10                                 # bright-star lookup grid: 6 x 10 x 10 cube cells
CELL_MARGIN_DEG = 0.8                      # stars are listed in every cell within this distance
FAINT_CELLS = 128                          # faint-star grid: 6 x 128 x 128 cells, at most one star each
FAINT_MAG = 7.0                            # faintest procedural star
FAINT_DENSITY = 0.37                       # chance of a star per cell in the galactic plane
STAR_GAIN = 3.0                            # peak brightness of a magnitude 0 star (linear)
MW_GAIN = 0.13                             # Milky Way brightness (linear)
HALO = 0.12                                # glare around the brightest stars
HALO_R = math.radians(0.13)                # glare radius (at most 2 pixels)
EXTINCTION = (0.10, 0.15, 0.24)            # magnitudes per airmass in red, green, blue (sea level is ~0.1-0.3)

# Two builds: full quality, and a Lite one for integrated graphics.
QUALITY = {
    "high": dict(zip="Diamond-SMP-Shader-Sky.zip", label="Shader Sky", steps=160, step_k=0.06, layers=2,
                 disk_octaves=4, region=34.0, mag_limit=4.5, faint=True,
                 octaves=dict(warp=1, thick=1, clouds=4, dust=4, lane=1, neb=2)),
    "lite": dict(zip="Diamond-SMP-Shader-Sky-Lite.zip", label="Shader Sky Lite", steps=80, step_k=0.12,
                 layers=1, disk_octaves=3, region=30.0, mag_limit=4.0, faint=False,
                 octaves=dict(warp=0, thick=0, clouds=2, dust=2, lane=0, neb=0)),
}

# (overlay directory, vanilla versions to check against, min_format, max_format, style)
VARIANTS = [
    ("shader_sky_1_21_9", ("1.21.9", "1.21.10", "1.21.11"), [69, 0], [75, 99], "moj_import"),
    ("shader_sky_26_1", ("26.1", "26.2"), [84, 0], [88, 99], "moj_import"),
    ("shader_sky_26_3", ("26.3",), [97, 0], [97, 99], "include"),
]
MIN_FORMAT, MAX_FORMAT = [69, 0], [97, 99]
SHADERS = "assets/minecraft/shaders"


def _fl(x):
    """A GLSL float literal."""
    s = f"{float(x):.9g}"
    return s if ("e" in s or "." in s) else s + ".0"


def _vec(v):
    return "vec3(" + ", ".join(_fl(x) for x in v) + ")"


# ---------------------------------------------------------------------------
# Physics tables
# ---------------------------------------------------------------------------


def scene_frame():
    """Scene axes in world coordinates and the disk basis, exactly as blackhole.BlackHoleScene."""
    w2s = bh.world_to_scene(BH_DIR)
    i = math.radians(INCLINATION)
    n = bh.normalize(bh.rot(ROLL, (0, 0, 1)) @ np.array([0.0, math.cos(i), -math.sin(i)]))
    e1 = bh.normalize(np.cross(n, [0.0, 0.0, 1.0]))
    e2 = np.cross(n, e1)
    return w2s, n, e1, e2


def exposure():
    """Exposure that matches the pack's skybox textures (p99.7 of disk luminance -> DISK_KEY)."""
    scene = bh.BlackHoleScene(distance=DISTANCE, inclination=INCLINATION, roll=ROLL, r_in=R_IN, r_out=R_OUT,
                              t_max=T_MAX, opacity=OPACITY, seed=7)
    ht = math.tan(math.radians(40))
    t = (np.arange(192) + 0.5) / 192 * 2 - 1
    a, b = np.meshgrid(t * ht, t * ht)
    d = bh.normalize(np.stack([-a, -b, np.ones_like(a)], -1))
    lum = scene.render(d)[..., :3] @ bh.LUMA
    return DISK_KEY / float(np.percentile(lum, 99.7))


def blackbody_table(n=64, t_lo=1500.0, t_hi=80000.0, normalise=False):
    """Blackbody colours on a log-temperature grid: radiance (6500 K has luminance 1),
    or with normalise=True just the tint (every entry has luminance 1)."""
    temps = np.geomspace(t_lo, t_hi, n)
    if normalise:
        return bh.blackbody_colour(temps), t_lo, t_hi
    x = (np.log(temps) - bh.BB_LO) / (bh.BB_HI - bh.BB_LO) * (len(bh.BB_LUT) - 1)
    i = np.clip(x.astype(int), 0, len(bh.BB_LUT) - 2)
    f = (x - i)[:, None]
    return bh.BB_LUT[i] * (1 - f) + bh.BB_LUT[i + 1] * f, t_lo, t_hi


def shadow_angle():
    """Angular radius of the shadow seen from DISTANCE (same ray model as the tracer)."""
    b_c = 1.5 * math.sqrt(3.0)              # critical impact parameter, r_s = 1
    h_c = b_c / math.sqrt(1.0 + b_c * b_c / DISTANCE ** 3)
    return math.asin(h_c / DISTANCE)


def escape_angles(theta, k=0.002, r_far=3000.0):
    """Where rays end up: a ray leaving the camera at angle theta from the hole escapes to
    the far sky at angle psi from it, measured the same way round (psi < theta: bent
    towards the hole; psi < 0 or < -pi: wrapped around it). NaN if the hole swallows it.

    Integrates the exact Schwarzschild photon orbit in the same form the GPU tracer uses
    (d2x/dl2 = -1.5 h^2 x / r^5), vectorised over rays."""
    th = np.atleast_1d(np.asarray(theta, dtype=np.float64)).ravel()
    n = th.size
    px, pz = np.zeros(n), np.full(n, -DISTANCE)
    vx, vz = np.sin(th), np.cos(th)
    h2 = (DISTANCE * np.sin(th)) ** 2
    psi = th.copy()
    out = np.full(n, np.nan)
    live = np.arange(n)

    def acc(x, z, hh):
        r2 = x * x + z * z
        f = -1.5 * hh / (r2 * r2 * np.sqrt(r2))
        return f * x, f * z

    while live.size:
        x, z, ux, uz, hh = px[live], pz[live], vx[live], vz[live], h2[live]
        r = np.hypot(x, z)
        dt = np.minimum(k * r * (0.6 + 0.4 * np.minimum(r / 3.0, 1.0)) * np.where(r > 30.0, 4.0, 1.0), 40.0)
        a1 = acc(x, z, hh)
        a2 = acc(x + 0.5 * dt * ux, z + 0.5 * dt * uz, hh)
        b2 = (ux + 0.5 * dt * a1[0], uz + 0.5 * dt * a1[1])
        a3 = acc(x + 0.5 * dt * b2[0], z + 0.5 * dt * b2[1], hh)
        b3 = (ux + 0.5 * dt * a2[0], uz + 0.5 * dt * a2[1])
        b4 = (ux + dt * a3[0], uz + dt * a3[1])
        a4 = acc(x + dt * b3[0], z + dt * b3[1], hh)
        qx = x + dt / 6 * (ux + 2 * b2[0] + 2 * b3[0] + b4[0])
        qz = z + dt / 6 * (uz + 2 * b2[1] + 2 * b3[1] + b4[1])
        nx = ux + dt / 6 * (a1[0] + 2 * a2[0] + 2 * a3[0] + a4[0])
        nz = uz + dt / 6 * (a1[1] + 2 * a2[1] + 2 * a3[1] + a4[1])
        psi[live] += np.arctan2(uz * nx - ux * nz, ux * nx + uz * nz)
        px[live], pz[live], vx[live], vz[live] = qx, qz, nx, nz
        rq = np.hypot(qx, qz)
        caught = rq < 1.0
        gone = (rq > r_far) & (qx * nx + qz * nz > 0)
        out[live[gone]] = psi[live[gone]]
        live = live[~(caught | gone)]
    return out.reshape(np.shape(theta)) if np.ndim(theta) else float(out[0])


@lru_cache(maxsize=None)
def lens_table(n=LENS_N):
    """psi and d psi / dx on a grid of x = ln(theta / theta_shadow - 1)."""
    th_sh = shadow_angle()
    x1 = math.log(math.pi / th_sh - 1.0)
    x = np.linspace(LENS_X0, x1, n)
    dx = 1e-3
    th = lambda xx: th_sh * (1.0 + np.exp(xx))  # noqa: E731
    psi = escape_angles(np.minimum(th(x), math.pi))
    hi = escape_angles(np.minimum(th(x + dx), math.pi))
    lo = escape_angles(th(x - dx))
    dpsi = (hi - lo) / (np.minimum(th(x + dx), math.pi) - th(x - dx)) * (th(x) - th_sh)
    return th_sh, LENS_X0, x1, psi, dpsi


def _cube_face(d):
    """Cube face and equal-angle (u, v) in [-1, 1] for directions d (..., 3). Mirrors dsf_face()."""
    d = np.asarray(d, dtype=np.float64)
    ax, ay, az = np.abs(d[..., 0]), np.abs(d[..., 1]), np.abs(d[..., 2])
    xm = (ax >= ay) & (ax >= az)
    ym = ~xm & (ay >= az)
    face = np.where(xm, np.where(d[..., 0] > 0, 0, 1),
                    np.where(ym, np.where(d[..., 1] > 0, 2, 3), np.where(d[..., 2] > 0, 4, 5)))
    m = np.where(xm, ax, np.where(ym, ay, az))
    a = np.where(xm, d[..., 1], d[..., 0]) / m
    b = np.where(xm | ym, d[..., 2], d[..., 1]) / m
    return face, np.arctan(a) / (math.pi / 4), np.arctan(b) / (math.pi / 4)


def cube_cell(d, n):
    face, u, v = _cube_face(d)
    i = np.clip(((u + 1) * 0.5 * n).astype(int), 0, n - 1)
    j = np.clip(((v + 1) * 0.5 * n).astype(int), 0, n - 1)
    return (face * n + j) * n + i


def face_dir(face, u, v):
    """Inverse of _cube_face (mirrors dsf_face_dir())."""
    face = np.asarray(face)[..., None]
    a, b = np.tan(np.asarray(u) * math.pi / 4), np.tan(np.asarray(v) * math.pi / 4)
    s = np.where(face % 2 == 0, 1.0, -1.0)[..., 0]
    d = np.where(face < 2, np.stack([s, a, b], -1),
                 np.where(face < 4, np.stack([a, s, b], -1), np.stack([a, b, s], -1)))
    return bh.normalize(d)


def star_tables(mag_limit, n=CELLS, margin_deg=CELL_MARGIN_DEG):
    """Real catalogue stars sorted into cube cells for the GPU.

    Returns (cell_start (6n^2+1,), entries (M, 4)): entry = (direction * (1 + T/1e5), peak flux)."""
    dirs, mag, temp = real_sky.catalog_stars(mag_limit)
    order = np.argsort(mag)
    dirs, mag, temp = dirs[order], mag[order], np.clip(temp[order], 2000.0, 40000.0)
    # 24 points on a small circle round each star + the star itself: every cell it can touch
    t1 = bh.normalize(np.cross(dirs, np.where(np.abs(dirs[:, 1:2]) < 0.9, [[0.0, 1.0, 0.0]], [[1.0, 0.0, 0.0]])))
    t2 = np.cross(dirs, t1)
    m = math.radians(margin_deg)
    ang = np.linspace(0, 2 * math.pi, 24, endpoint=False)
    ring = (math.cos(m) * dirs[:, None, :] + math.sin(m) * (np.cos(ang)[None, :, None] * t1[:, None, :]
                                                            + np.sin(ang)[None, :, None] * t2[:, None, :]))
    pts = np.concatenate([dirs[:, None, :], ring], axis=1)
    cells = cube_cell(pts, n)
    members = [[] for _ in range(6 * n * n)]
    for k in range(len(mag)):
        for c in np.unique(cells[k]):
            members[c].append(k)
    start = np.zeros(6 * n * n + 1, dtype=int)
    start[1:] = np.cumsum([len(m_) for m_ in members])
    idx = np.array([k for m_ in members for k in m_], dtype=int)
    entries = np.concatenate([dirs[idx] * (1.0 + temp[idx] / 1e5)[:, None],
                              (STAR_GAIN * 10 ** (-0.4 * mag[idx]))[:, None]], axis=1)
    return start, entries


def galactic_frame():
    gn = bh.normalize(real_sky.GALACTIC_NORTH_WORLD)
    gc = real_sky.GALACTIC_CENTRE_WORLD
    gc = bh.normalize(gc - gn * np.dot(gc, gn))
    return gn, gc, np.cross(gn, gc)


# ---------------------------------------------------------------------------
# GLSL
# ---------------------------------------------------------------------------

BLACKHOLE_GLSL = Template("""\
// Diamond SMP: live black hole (Sagittarius A*) for the vanilla sky shader.
// Generated by diamond-smp-pack/generator/shader_sky.py ($QUALITY quality) - edit that file, not this one.
#ifndef DIAMOND_BLACKHOLE_GLSL
#define DIAMOND_BLACKHOLE_GLSL

const vec3 DBH_DIR = $DIR;      // world direction of the hole: south, 24 deg up
const vec3 DBH_SX = $SX;       // scene axes (camera looks along +z at the hole)
const vec3 DBH_SY = $SY;
const vec3 DBH_N = $N;             // disk normal (scene frame)
const vec3 DBH_E1 = $E1;
const vec3 DBH_E2 = $E2;
const float DBH_D = $D;                    // camera distance, Schwarzschild radii
const float DBH_RIN = $RIN;                 // innermost stable circular orbit
const float DBH_ROUT = $ROUT;
const float DBH_TMAX = $TMAX;              // peak disk temperature, kelvin
const float DBH_OPACITY = $OPACITY;
const float DBH_FPEAK = $FPEAK;           // peak of the Novikov-Thorne profile
const float DBH_EXPOSURE = $EXPOSURE;
const float DBH_COS_REGION = $COS_REGION;
const float DBH_STEPK = $STEPK;
const float DBH_RESC = $RESC;               // past this (outward bound) a ray can hit nothing more
const float DBH_FLOW = $FLOW;
const int DBH_STEPS = $STEPS;
const int DBH_LAYERS = $LAYERS;            // noise layers in the gas
const int DBH_OCT = $DISK_OCT;               // and octaves per layer
const vec3 DBH_EXT = $EXT;      // atmospheric extinction, magnitudes per airmass (R, G, B)
const float DBH_LUT_LO = $LUT_LO;
const float DBH_LUT_HI = $LUT_HI;
const vec3 DBH_LUT[$LUT_N] = vec3[$LUT_N](
    $LUT
);

// The animation clock. GameTime is the fraction of a 20-minute day; anything outside
// 0..1 means the uniform is missing, and then the disk simply stands still.
float dbh_time(float gameTime) {
    float g = (gameTime >= 0.0 && gameTime <= 1.0) ? gameTime : 0.0;
    return g * $TIME_SCALE;
}

vec3 dbh_blackbody(float temp) {
    float x = clamp((log(max(temp, 1.0)) - DBH_LUT_LO) / (DBH_LUT_HI - DBH_LUT_LO), 0.0, 1.0) * $LUT_LAST;
    int i = int(min(floor(x), $LUT_LAST - 1.0));
    return mix(DBH_LUT[i], DBH_LUT[i + 1], x - float(i));
}

float dbh_hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float dbh_noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(dbh_hash(i), dbh_hash(i + vec3(1.0, 0.0, 0.0)), f.x),
                   mix(dbh_hash(i + vec3(0.0, 1.0, 0.0)), dbh_hash(i + vec3(1.0, 1.0, 0.0)), f.x), f.y),
               mix(mix(dbh_hash(i + vec3(0.0, 0.0, 1.0)), dbh_hash(i + vec3(1.0, 0.0, 1.0)), f.x),
                   mix(dbh_hash(i + vec3(0.0, 1.0, 1.0)), dbh_hash(i + vec3(1.0, 1.0, 1.0)), f.x), f.y), f.z);
}

float dbh_fbm(vec3 p) {
    float s = 0.0;
    float a = 0.5;
    float norm = 0.0;
    for (int k = 0; k < DBH_OCT; k++) {
        s += a * dbh_noise(p);
        norm += a;
        p = p * 2.03 + vec3(1.7, 9.2, 3.1);
        a *= 0.5;
    }
    return clamp((s / norm - 0.5) * 3.2 + 0.5, 0.0, 1.0);   // stretch the contrast to 0..1
}

// Orbital streaks: noise wrapped around the orbit (periodic in phi), stretched along it,
// with a trailing spiral twist.
float dbh_streaks(float phi, float lr, float scale, float seed) {
    float a = phi + 3.4557519 * lr;
    return dbh_fbm(vec3(cos(a) * 1.6 * scale, sin(a) * 1.6 * scale, lr * 9.0 * scale + seed));
}

// Gas at radius r orbits with the Keplerian angular speed sqrt(M / r^3); two phases of the
// pattern are cross-faded so the differential rotation never shears it into thin threads,
// with a variance-preserving blend so the streaks stay equally crisp all through the cycle.
float dbh_disk_noise(float phi, float r, float t, float scale, float seed) {
    float omega = sqrt(0.5 / (r * r * r));
    float lr = log(r);
    float t1 = fract(t);
    float t2 = fract(t + 0.5);
    float w1 = 1.0 - abs(1.0 - 2.0 * t1);
    float w2 = 1.0 - w1;
    float n1 = dbh_streaks(phi - omega * DBH_FLOW * t1, lr, scale, seed);
    float n2 = dbh_streaks(phi - omega * DBH_FLOW * t2, lr, scale, seed + 5.3);
    return clamp(0.5 + (w1 * (n1 - 0.5) + w2 * (n2 - 0.5)) * inversesqrt(w1 * w1 + w2 * w2), 0.0, 1.0);
}

vec3 dbh_accel(vec3 x, float h2) {
    float r2 = dot(x, x);
    return -1.5 * h2 / (r2 * r2 * sqrt(r2)) * x;
}

// Trace one ray (scene frame) backwards from the camera. Returns disk light (linear RGB)
// and how much of the pixel is the black shadow.
vec4 dbh_trace(vec3 sd, float t) {
    vec3 x = vec3(0.0, 0.0, -DBH_D);
    vec3 v = sd;
    vec3 L = cross(x, v);
    float h2 = dot(L, L);
    float h = sqrt(h2);
    float lam = 0.0;     // photon angular momentum about the disk axis
    if (h > 1e-6) {
        float b = h / sqrt(max(1.0 - h2 / (DBH_D * DBH_D * DBH_D), 1e-6));
        lam = -dot(L, DBH_N) / h * b;
    }
    vec3 col = vec3(0.0);
    float trans = 1.0;
    float shadow = 0.0;
    for (int i = 0; i < DBH_STEPS; i++) {
        float r = length(x);
        // long steps out where there is nothing to hit, short ones near the hole
        float k = r > DBH_ROUT ? 2.5 * DBH_STEPK : DBH_STEPK;
        float dt = min(k * r * (0.6 + 0.4 * min(r / 3.0, 1.0)), 4.0);
        vec3 a1 = dbh_accel(x, h2);
        vec3 a2 = dbh_accel(x + 0.5 * dt * v, h2);
        vec3 b2 = v + 0.5 * dt * a1;
        vec3 a3 = dbh_accel(x + 0.5 * dt * b2, h2);
        vec3 b3 = v + 0.5 * dt * a2;
        vec3 b4 = v + dt * a3;
        vec3 a4 = dbh_accel(x + dt * b3, h2);
        vec3 q = x + dt / 6.0 * (v + 2.0 * b2 + 2.0 * b3 + b4);
        vec3 vn = v + dt / 6.0 * (a1 + 2.0 * a2 + 2.0 * a3 + a4);
        float s0 = dot(x, DBH_N);
        float s1 = dot(q, DBH_N);
        if (s0 * s1 < 0.0) {
            vec3 p = mix(x, q, s0 / (s0 - s1));
            float rp = length(p);
            if (rp > DBH_RIN * 0.95 && rp < DBH_ROUT) {
                float xr = rp / DBH_RIN;
                float ft = xr > 1.0 ? pow(xr, -0.75) * pow(1.0 - inversesqrt(xr), 0.25) / DBH_FPEAK : 0.0;
                ft = max(ft, 0.18 * clamp((rp - DBH_RIN * 0.95) / (DBH_RIN * 0.05), 0.0, 1.0));
                float phi = atan(dot(p, DBH_E2), dot(p, DBH_E1));
                float n1 = dbh_disk_noise(phi, rp, t, 1.0, 0.0);
                float n2 = DBH_LAYERS > 1 ? dbh_disk_noise(phi, rp, t, 2.1, 17.0) : n1;
                float temp = DBH_TMAX * ft * (1.0 + 0.14 * (n2 - 0.5));
                float edgeIn = clamp((rp - DBH_RIN * 0.95) / (DBH_RIN * 0.08), 0.0, 1.0);
                float tOut = clamp((DBH_ROUT - rp) / (DBH_ROUT * 0.4), 0.0, 1.0);
                float edgeOut = tOut * tOut * (3.0 - 2.0 * tOut);
                float tau = DBH_OPACITY * (0.25 + 1.5 * n1) * pow(edgeOut, 1.5) * edgeIn;
                float alpha = 1.0 - exp(-tau);
                // exact redshift for gas on circular orbits: Doppler + gravitational
                float om = sqrt(0.5 / (rp * rp * rp));
                float g = sqrt(max(1.0 - 1.5 / rp, 1e-4)) / max(1.0 - om * lam, 1e-3);
                float mu = abs(dot(normalize(vn), DBH_N));
                float limb = (1.0 + 2.06 * mu) / 2.03;    // Chandrasekhar limb darkening
                col += trans * alpha * (0.55 + 0.9 * pow(n1, 1.5)) * limb * dbh_blackbody(g * temp);
                trans *= 1.0 - alpha;
            }
        }
        x = q;
        v = vn;
        float rq = length(q);
        if (rq < 1.0) {
            shadow = trans;
            break;
        }
        if (trans < 0.01 || (rq > DBH_RESC && dot(x, v) > 0.0)) {
            break;
        }
    }
    return vec4(col, shadow);
}

vec3 dbh_aces(vec3 x) {
    x = max(x, vec3(0.0));
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

vec3 dbh_srgb(vec3 c) {
    return mix(12.92 * c, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c));
}

// How much air a ray crosses at a height y = sin(altitude), relative to straight up.
float dbh_airmass(float y) {
    y = max(y, 0.0);
    return 1.0 / (y + 0.025 * exp(-11.0 * y));
}

// Put the black hole into a vanilla sky colour `base` for world direction `dir`.
// t is the animation phase (any real number; only its fractional part matters).
vec3 dbh_sky(vec3 base, vec3 dir, float t) {
    float cd = dot(dir, DBH_DIR);
    if (cd < DBH_COS_REGION || dir.y <= 0.0) {
        return base;
    }
    vec3 sd = normalize(vec3(dot(dir, DBH_SX), dot(dir, DBH_SY), cd));
    vec4 hole = dbh_trace(sd, t);
    float lum = dot(base, vec3(0.2126, 0.7152, 0.0722));
    float night = 1.0 - smoothstep(0.06, 0.45, lum);
    // Rain turns vanilla's day sky grey: then the hole is only a faint glow behind the clouds.
    float hi = max(base.r, max(base.g, base.b));
    float chroma = (hi - min(base.r, min(base.g, base.b))) / max(hi, 1e-4);
    float overcast = (1.0 - smoothstep(0.22, 0.42, chroma)) * smoothstep(0.03, 0.08, lum);
    // Air dims and reddens the hole low in the sky; by day it is fainter against the
    // bright blue, like the Moon in daylight.
    vec3 air = exp2(-1.328771 * DBH_EXT * (dbh_airmass(dir.y) - 1.0));
    vec3 disk = dbh_srgb(dbh_aces(hole.rgb * air * DBH_EXPOSURE * mix(0.55, 1.0, night)));
    // A soft glow of disk light scattered by the air around the hole.
    float ang = acos(clamp(cd, -1.0, 1.0));
    disk += air * vec3(0.80, 0.88, 1.0) * (0.10 * exp(-ang / 0.10) + 0.04 * exp(-ang / 0.30)) * mix(0.35, 1.0, night);
    // At night the shadow is pitch black; by day the air in front of it fills it in.
    base *= 1.0 - 0.85 * hole.a * night;
    disk *= smoothstep(DBH_COS_REGION, DBH_COS_REGION + 0.03, cd) * smoothstep(0.0, 0.035, dir.y)
          * (1.0 - 0.8 * overcast);
    return 1.0 - (1.0 - base) * (1.0 - clamp(disk, 0.0, 1.0));
}

#endif
""")


STARFIELD_GLSL = Template("""\
// Diamond SMP: the real night sky, bent by the black hole, for the vanilla stars shader.
// Generated by diamond-smp-pack/generator/shader_sky.py ($QUALITY quality) - edit that file, not this one.
// Stars: Yale Bright Star Catalogue (public domain), V <= $MAG_LIMIT, at their true places for
// latitude 37 N with Sagittarius A* on the meridian.
#ifndef DIAMOND_STARFIELD_GLSL
#define DIAMOND_STARFIELD_GLSL

const vec3 DSF_H = $H;       // the hole (world frame)
const vec3 DSF_PERP0 = $PERP0;   // any direction at right angles to it
const vec3 DSF_GN = $GN;      // galactic north pole
const vec3 DSF_GC = $GC;      // galactic centre (behind the hole)
const vec3 DSF_GS = $GS;
const float DSF_TH_SH = $TH_SH;            // angular radius of the shadow, radians
const float DSF_LX0 = $LX0;
const float DSF_LX1 = $LX1;
const int DSF_LN = $LN;
// Lens table on x = ln(theta / DSF_TH_SH - 1): a ray seen at angle theta from the hole
// came from angle psi(x) on the far sky (negative: it wrapped round the hole).
const float DSF_PSI[$LN] = float[$LN](
    $PSI
);
const float DSF_DPSI[$LN] = float[$LN](    // d psi / dx
    $DPSI
);
const int DSF_CN = $CN;
const int DSF_CELL[$CELL_N] = int[$CELL_N](
    $CELL
);
// xyz: direction * (1 + temperature / 1e5); w: peak brightness
const vec4 DSF_STAR[$STAR_N] = vec4[$STAR_N](
    $STARS
);
const bool DSF_FAINT = $FAINT;
const int DSF_FN = $FN;
const float DSF_FAINT_P = $FAINT_P;
const float DSF_FAINT_M0 = $MAG_LIMIT;
const float DSF_FAINT_M1 = $FAINT_M1;
const float DSF_STAR_GAIN = $STAR_GAIN;
const float DSF_MW_GAIN = $MW_GAIN;
const float DSF_HALO = $HALO;
const float DSF_HALO_R = $HALO_R;
const vec3 DSF_EXT = $EXT;
const vec3 DSF_C_DISK = $C_DISK;
const vec3 DSF_C_BULGE = $C_BULGE;
const int DSF_OCT_WARP = $OCT_WARP;
const int DSF_OCT_THICK = $OCT_THICK;
const int DSF_OCT_CLOUDS = $OCT_CLOUDS;
const int DSF_OCT_DUST = $OCT_DUST;
const int DSF_OCT_LANE = $OCT_LANE;
const int DSF_OCT_NEB = $OCT_NEB;
const float DSF_BB_LO = $BB_LO;
const float DSF_BB_HI = $BB_HI;
const vec3 DSF_BB[$BB_N] = vec3[$BB_N](
    $BB
);

float dsf_time(float gameTime) {
    return (gameTime >= 0.0 && gameTime <= 1.0) ? gameTime : 0.0;
}

uint dsf_pcg(uint v) {
    uint s = v * 747796405u + 2891336453u;
    uint w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u;
    return (w >> 22u) ^ w;
}

float dsf_u01(uint h) {
    return float(h >> 8u) * (1.0 / 16777216.0);
}

float dsf_hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float dsf_noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(dsf_hash(i), dsf_hash(i + vec3(1.0, 0.0, 0.0)), f.x),
                   mix(dsf_hash(i + vec3(0.0, 1.0, 0.0)), dsf_hash(i + vec3(1.0, 1.0, 0.0)), f.x), f.y),
               mix(mix(dsf_hash(i + vec3(0.0, 0.0, 1.0)), dsf_hash(i + vec3(1.0, 0.0, 1.0)), f.x),
                   mix(dsf_hash(i + vec3(0.0, 1.0, 1.0)), dsf_hash(i + vec3(1.0, 1.0, 1.0)), f.x), f.y), f.z);
}

float dsf_fbm(vec3 p, int octaves) {
    float s = 0.0;
    float a = 1.0;
    float norm = 0.0;
    for (int k = 0; k < octaves; k++) {
        s += a * dsf_noise(p);
        norm += a;
        p = p * 2.03 + vec3(1.7, 9.2, 3.1);
        a *= 0.5;
    }
    return octaves > 0 ? s / norm : 0.5;
}

vec3 dsf_blackbody(float temp) {
    float x = clamp((log(temp) - DSF_BB_LO) / (DSF_BB_HI - DSF_BB_LO), 0.0, 1.0) * $BB_LAST;
    int i = int(min(floor(x), $BB_LAST - 1.0));
    return mix(DSF_BB[i], DSF_BB[i + 1], x - float(i));
}

vec3 dsf_srgb(vec3 c) {
    return mix(12.92 * c, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c));
}

// Cube-map face and equal-angle coordinates in -1..1.
void dsf_face(vec3 d, out int face, out vec2 uv) {
    vec3 a = abs(d);
    vec2 p;
    float m;
    if (a.x >= a.y && a.x >= a.z) {
        face = d.x > 0.0 ? 0 : 1;
        p = d.yz;
        m = a.x;
    } else if (a.y >= a.z) {
        face = d.y > 0.0 ? 2 : 3;
        p = d.xz;
        m = a.y;
    } else {
        face = d.z > 0.0 ? 4 : 5;
        p = d.xy;
        m = a.z;
    }
    uv = atan(p / m) * 1.2732395;
}

vec3 dsf_face_dir(int face, vec2 uv) {
    vec2 p = tan(uv * 0.78539816);
    float s = (face == 0 || face == 2 || face == 4) ? 1.0 : -1.0;
    vec3 d = face < 2 ? vec3(s, p.x, p.y) : (face < 4 ? vec3(p.x, s, p.y) : vec3(p.x, p.y, s));
    return normalize(d);
}

// World-frame direction through the screen point c (-1..1) in the stars pass. Vanilla's star
// matrix is camera * rotateY(-90) * rotateX(sky angle), so its first column is the world +Z
// axis as the camera sees it; the camera never rolls, which pins down its whole rotation.
// Except when facing exactly east or west: then the pitch cannot be told apart from the sky
// angle, and `trust` fades the stars out rather than drawing them in the wrong place.
vec3 dsf_world_ray(mat3 mv, mat4 proj, vec2 c, out float trust) {
    mat4 inv = inverse(proj);
    vec4 p1 = inv * vec4(c, 0.25, 1.0);
    vec4 p2 = inv * vec4(c, 0.5, 1.0);
    vec3 a1 = p1.xyz / p1.w;
    vec3 a2 = p2.xyz / p2.w;
    vec3 ray = dot(a2, a2) > dot(a1, a1) ? a2 - a1 : a1 - a2;   // points away from the eye
    vec3 zAxis = normalize(mv[0]);
    vec3 up = vec3(0.0, -zAxis.z, zAxis.y);   // world up: no x part (no roll), at right angles to +Z
    float n = length(up);
    trust = smoothstep(5e-5, 2e-4, n);
    up = n > 1e-7 ? up / n : vec3(0.0, 1.0, 0.0);
    // cos(pitch) >= 0; looking exactly straight up or down is ambiguous, so assume up
    if (up.y < -1e-4 || (up.y <= 1e-4 && up.z > 0.0)) {
        up = -up;
    }
    mat3 view = mat3(cross(up, zAxis), up, zAxis);   // world -> camera
    return transpose(view) * ray;
}

// Gravitational lensing. For a pixel looking along d, finds where its light came from
// (src) and how the hole stretches the sky there: an offset in the far sky along eRad
// (eTan) shows up kRad (kTan) times bigger on screen. False inside the shadow.
bool dsf_lens(vec3 d, out vec3 src, out vec3 eRad, out vec3 eTan, out float kRad, out float kTan,
              out float theta) {
    float c = clamp(dot(d, DSF_H), -1.0, 1.0);
    theta = acos(c);
    src = d;
    eRad = d;
    eTan = d;
    kRad = 1.0;
    kTan = 1.0;
    if (theta <= DSF_TH_SH) {
        return false;
    }
    vec3 perp = d - c * DSF_H;
    float pl = length(perp);
    vec3 e = pl > 1e-6 ? perp / pl : DSF_PERP0;
    float th = max(theta - DSF_TH_SH, 1e-7);
    float f = clamp((log(th / DSF_TH_SH) - DSF_LX0) / (DSF_LX1 - DSF_LX0), 0.0, 1.0) * float(DSF_LN - 1);
    int i = min(int(f), DSF_LN - 2);
    float w = f - float(i);
    float psi = mix(DSF_PSI[i], DSF_PSI[i + 1], w);
    float dpsi = mix(DSF_DPSI[i], DSF_DPSI[i + 1], w) / th;     // d psi / d theta
    float sp = sin(psi);
    src = cos(psi) * DSF_H + sp * e;
    eRad = -sp * DSF_H + cos(psi) * e;
    eTan = cross(DSF_H, e);
    kRad = 1.0 / max(abs(dpsi), 1e-4);
    kTan = sin(theta) / max(abs(sp), 1e-3);
    return true;
}

// The Milky Way: thin disk, bulge, star clouds, dust lanes and pink hydrogen nebulae.
vec3 dsf_galaxy(vec3 d, out float absLat) {
    float b = asin(clamp(dot(d, DSF_GN), -1.0, 1.0));
    float l = atan(dot(d, DSF_GS), dot(d, DSF_GC));
    absLat = abs(b);
    float halo = exp(-abs(b) / 0.35) * 0.06;
    if (abs(b) > 0.7) {
        return DSF_C_DISK * halo;
    }
    float bb = b - (dsf_fbm(d * 2.0 + vec3(3.1, 0.0, 0.0), DSF_OCT_WARP) - 0.5) * 0.06;
    float thick = 0.06 + 0.05 * dsf_fbm(d * 3.0 + vec3(0.0, 7.0, 0.0), DSF_OCT_THICK);
    float disk = exp(-abs(bb) / thick) * (0.22 + 0.78 * exp(-(l / 1.25) * (l / 1.25)));
    float bulge = 1.7 * exp(-((l / 0.24) * (l / 0.24) + (bb / 0.16) * (bb / 0.16)));
    float clouds = 0.25 + 1.6 * pow(dsf_fbm(d * 7.0, DSF_OCT_CLOUDS), 2.4);
    float ridge = 1.0 - abs(2.0 * dsf_fbm(d * 9.0 + vec3(1.3, 0.0, -4.0), DSF_OCT_DUST) - 1.0);
    float lw = 0.03 + 0.03 * dsf_fbm(d * 4.0 + vec3(0.0, 0.0, 2.0), DSF_OCT_LANE);
    float lane = exp(-(bb / lw) * (bb / lw));
    float tau = lane * (0.5 + 4.0 * pow(max(ridge - 0.45, 0.0), 1.2)) + 0.6 * exp(-(bb / 0.012) * (bb / 0.012));
    vec3 col = DSF_C_DISK * (disk * clouds + halo) + DSF_C_BULGE * bulge * (0.55 + 0.6 * clouds);
    col *= exp(-tau / vec3(1.25, 1.0, 0.75));     // dust dims blue light most
    if (DSF_OCT_NEB > 0) {
        float neb = max(dsf_fbm(d * 16.0 + vec3(0.0, -3.0, 0.0), DSF_OCT_NEB) - 0.66, 0.0) * 3.0;
        col += neb * exp(-(bb / 0.05) * (bb / 0.05)) * vec3(0.95, 0.22, 0.30) * exp(-0.5 * tau);
    }
    return col;
}

float dsf_twinkle(float h1, float h2, float t, float amount) {
    return 1.0 + amount * (0.6 * sin(6.2831853 * (t * 3000.0 + h1)) + 0.4 * sin(6.2831853 * (t * 4513.0 + h2)));
}

// The catalogue stars near src. Offsets are mapped to the screen through the lens so each
// star is a round dot about a pixel wide wherever it lands.
vec3 dsf_bright_stars(vec3 src, vec3 eRad, vec3 eTan, float kRad, float kTan, float inv2s2, float invHalo, float t,
                      float tw) {
    int face;
    vec2 uv;
    dsf_face(src, face, uv);
    ivec2 ij = clamp(ivec2((uv + 1.0) * (0.5 * float(DSF_CN))), ivec2(0), ivec2(DSF_CN - 1));
    int cell = (face * DSF_CN + ij.y) * DSF_CN + ij.x;
    vec3 acc = vec3(0.0);
    for (int k = DSF_CELL[cell]; k < DSF_CELL[cell + 1]; k++) {
        vec4 s = DSF_STAR[k];
        float len = length(s.xyz);
        vec3 dl = s.xyz / len - src;
        float dr = dot(dl, eRad) * kRad;
        float dt = dot(dl, eTan) * kTan;
        float d2 = dr * dr + dt * dt;
        float g = 1.0 + 0.18 * clamp(log2(s.w * 20.0), 0.0, 6.0);     // bright stars look bigger
        float w = exp(-d2 * inv2s2 / (g * g)) + DSF_HALO * s.w * exp(-sqrt(d2) * invHalo);   // core + glare
        float h = fract(dot(s.xyz, vec3(431.7, 913.3, 271.1)));
        acc += dsf_blackbody((len - 1.0) * 1e5) * (s.w * w * dsf_twinkle(h, fract(h * 7.31), t, tw));
    }
    return acc;
}

// Fainter stars, made up but realistic: counts grow ~2x per magnitude and crowd into
// the Milky Way. At most one per small cube cell; the 2x2 cells nearest src are checked.
vec3 dsf_faint_stars(vec3 src, vec3 eRad, vec3 eTan, float kRad, float kTan, float inv2s2, float t, float tw,
                     float absLat) {
    int face;
    vec2 uv;
    dsf_face(src, face, uv);
    vec2 g = (uv + 1.0) * (0.5 * float(DSF_FN));
    ivec2 c0 = ivec2(floor(g));
    vec2 fr = g - vec2(c0);
    ivec2 dc = ivec2(fr.x < 0.5 ? -1 : 1, fr.y < 0.5 ? -1 : 1);
    float p = DSF_FAINT_P * (0.2 + 0.8 * exp(-absLat / 0.18));
    float a0 = exp2(1.0962406 * DSF_FAINT_M0);      // 10^(0.33 m)
    float a1 = exp2(1.0962406 * DSF_FAINT_M1);
    vec3 acc = vec3(0.0);
    for (int k = 0; k < 4; k++) {
        ivec2 c = c0 + ivec2(k & 1, k >> 1) * dc;
        if (c.x < 0 || c.y < 0 || c.x >= DSF_FN || c.y >= DSF_FN) {
            continue;
        }
        uint h = dsf_pcg(uint((face * DSF_FN + c.y) * DSF_FN + c.x) ^ 0x9e3779b9u);
        if (dsf_u01(h) > p) {
            continue;
        }
        uint h2 = dsf_pcg(h);
        uint h3 = dsf_pcg(h2);
        uint h4 = dsf_pcg(h3);
        uint h5 = dsf_pcg(h4);
        vec3 sd = dsf_face_dir(face, (vec2(c) + vec2(dsf_u01(h2), dsf_u01(h3))) / float(DSF_FN) * 2.0 - 1.0);
        vec3 dl = sd - src;
        float dr = dot(dl, eRad) * kRad;
        float dt = dot(dl, eTan) * kTan;
        float w = exp(-(dr * dr + dt * dt) * inv2s2);
        float mag = log2(a0 + dsf_u01(h4) * (a1 - a0)) / 1.0962406;
        float u = dsf_u01(h5);
        float temp = u < 0.24 ? 3300.0 : (u < 0.54 ? 4500.0 : (u < 0.70 ? 5600.0 : (u < 0.82 ? 6600.0
                   : (u < 0.92 ? 8500.0 : (u < 0.98 ? 15000.0 : 28000.0)))));
        float f = DSF_STAR_GAIN * exp2(-1.3287712 * mag) * w;
        acc += dsf_blackbody(temp) * (f * dsf_twinkle(dsf_u01(h2 ^ h5), dsf_u01(h3 ^ h4), t, tw));
    }
    return acc;
}

// The night sky (display colour, to be added on top of the vanilla sky) for the world
// direction d. px: angular size of a pixel; t: dsf_time(GameTime).
vec3 dsf_night_sky(vec3 d, float px, float t) {
    if (d.y < -0.02) {
        return vec3(0.0);      // below the horizon
    }
    vec3 src;
    vec3 eRad;
    vec3 eTan;
    float kRad;
    float kTan;
    float theta;
    if (!dsf_lens(d, src, eRad, eTan, kRad, kTan, theta)) {
        return vec3(0.0);      // the shadow: no light comes from in there
    }
    float sigma = 0.7 * max(px, 1e-5);
    float inv2s2 = 0.5 / (sigma * sigma);
    float mu = min(kRad * kTan, 25.0);    // lensing magnification of point sources
    float alt = max(d.y, 0.0);
    float tw = 0.10 + 0.32 * (1.0 - smoothstep(0.0, 0.5, alt));   // more twinkling low down
    float absLat;
    vec3 light = DSF_MW_GAIN * dsf_galaxy(src, absLat);
    vec3 stars = dsf_bright_stars(src, eRad, eTan, kRad, kTan, inv2s2, 1.0 / min(2.0 * px, DSF_HALO_R), t, tw);
    if (DSF_FAINT) {
        stars += dsf_faint_stars(src, eRad, eTan, kRad, kTan, inv2s2, t, tw, absLat);
    }
    light += stars * mu;
    float air = 1.0 / (alt + 0.025 * exp(-11.0 * alt));
    light *= exp2(-1.328771 * DSF_EXT * (air - 1.0));   // extinction: dimmer and redder low down
    light *= smoothstep(-0.02, 0.01, d.y) * smoothstep(DSF_TH_SH, DSF_TH_SH + 1.5 * px, theta);
    return dsf_srgb(1.0 - exp(-light));
}

#endif
""")


def include_blackhole(quality="high"):
    q = QUALITY[quality]
    w2s, n, e1, e2 = scene_frame()
    lut, t_lo, t_hi = blackbody_table()
    return BLACKHOLE_GLSL.substitute(
        QUALITY=quality, DIR=_vec(w2s[2]), SX=_vec(w2s[0]), SY=_vec(w2s[1]), N=_vec(n), E1=_vec(e1), E2=_vec(e2),
        D=_fl(DISTANCE), RIN=_fl(R_IN), ROUT=_fl(R_OUT), TMAX=_fl(T_MAX), OPACITY=_fl(OPACITY),
        FPEAK=_fl((36 / 49) ** 0.75 * (1 / 7) ** 0.25), EXPOSURE=_fl(_exposure()),
        COS_REGION=_fl(math.cos(math.radians(q["region"]))), STEPK=_fl(q["step_k"]), RESC=_fl(1.1 * R_OUT),
        FLOW=_fl(FLOW), STEPS=q["steps"], LAYERS=q["layers"], DISK_OCT=q["disk_octaves"], EXT=_vec(EXTINCTION),
        LUT_LO=_fl(math.log(t_lo)), LUT_HI=_fl(math.log(t_hi)), LUT_N=len(lut), LUT_LAST=_fl(len(lut) - 1),
        LUT=",\n    ".join(_vec(c) for c in lut), TIME_SCALE=_fl(TIME_SCALE))


@lru_cache(maxsize=None)
def _exposure():
    return exposure()


def _rows(items, per_line):
    items = list(items)
    return ",\n    ".join(", ".join(items[i:i + per_line]) for i in range(0, len(items), per_line))


def include_starfield(quality="high"):
    q = QUALITY[quality]
    th_sh, x0, x1, psi, dpsi = lens_table()
    start, entries = star_tables(q["mag_limit"])
    gn, gc, gs = galactic_frame()
    perp0 = bh.normalize(np.cross(BH_DIR, [0.0, 1.0, 0.0]))
    bb, t_lo, t_hi = blackbody_table(n=32, t_lo=2000.0, t_hi=40000.0, normalise=True)
    o = q["octaves"]
    stars = ("vec4(" + ", ".join(_fl(v) for v in e) + ")" for e in entries)
    return STARFIELD_GLSL.substitute(
        QUALITY=quality, MAG_LIMIT=_fl(q["mag_limit"]), H=_vec(BH_DIR), PERP0=_vec(perp0),
        GN=_vec(gn), GC=_vec(gc), GS=_vec(gs), TH_SH=_fl(th_sh), LX0=_fl(x0), LX1=_fl(x1), LN=len(psi),
        PSI=_rows((_fl(v) for v in psi), 8), DPSI=_rows((_fl(v) for v in dpsi), 8),
        CN=CELLS, CELL_N=len(start), CELL=_rows((str(int(v)) for v in start), 20),
        STAR_N=len(entries), STARS=_rows(stars, 2), FAINT="true" if q["faint"] else "false",
        FN=FAINT_CELLS, FAINT_P=_fl(FAINT_DENSITY), FAINT_M1=_fl(FAINT_MAG), STAR_GAIN=_fl(STAR_GAIN),
        MW_GAIN=_fl(MW_GAIN), HALO=_fl(HALO), HALO_R=_fl(HALO_R), EXT=_vec(EXTINCTION),
        C_DISK=_vec(bh.blackbody_colour(5400.0)), C_BULGE=_vec(bh.blackbody_colour(4300.0)),
        OCT_WARP=o["warp"], OCT_THICK=o["thick"], OCT_CLOUDS=o["clouds"], OCT_DUST=o["dust"], OCT_LANE=o["lane"],
        OCT_NEB=o["neb"], BB_LO=_fl(math.log(t_lo)), BB_HI=_fl(math.log(t_hi)), BB_N=len(bb),
        BB_LAST=_fl(len(bb) - 1), BB=",\n    ".join(_vec(c) for c in bb))


# Shader stages. $IMPORT is "moj_import" (1.21.9 - 26.2) or "include" (26.3), which also
# wants explicit locations and Vulkan's gl_VertexIndex.
STYLE = {
    "moj_import": dict(HEAD="#version 330\n", IMPORT="moj_import", IN="in", OUT="out", VID="gl_VertexID",
                       LOC=lambda n: ""),
    "include": dict(HEAD="#version 330\n#extension GL_ARB_separate_shader_objects : require\n", IMPORT="include",
                    IN="in", OUT="out", VID="gl_VertexIndex", LOC=lambda n: f"layout(location = {n}) "),
}

SKY_VSH = """$HEAD
#$IMPORT <minecraft:fog.glsl>
#$IMPORT <minecraft:dynamictransforms.glsl>
#$IMPORT <minecraft:projection.glsl>

${L0}in vec3 Position;

${L0}out float sphericalVertexDistance;
${L1}out float cylindricalVertexDistance;
${L2}out vec3 skyPos;

void main() {
    gl_Position = ProjMat * ModelViewMat * vec4(Position, 1.0);

    sphericalVertexDistance = fog_spherical_distance(Position);
    cylindricalVertexDistance = fog_cylindrical_distance(Position);
    skyPos = Position;   // world-aligned, camera-centred: its direction is the view direction
}
"""

SKY_FSH = """$HEAD
#$IMPORT <minecraft:fog.glsl>
#$IMPORT <minecraft:dynamictransforms.glsl>
#$IMPORT <minecraft:globals.glsl>
#$IMPORT <minecraft:diamond_blackhole.glsl>

${L0}in float sphericalVertexDistance;
${L1}in float cylindricalVertexDistance;
${L2}in vec3 skyPos;

${L0}out vec4 fragColor;

void main() {
    vec4 sky = apply_fog(ColorModulator, sphericalVertexDistance, cylindricalVertexDistance, 0.0, FogSkyEnd, FogSkyEnd, FogSkyEnd, FogColor);
    // Thick fog (water, lava, powder snow) hides the hole; ordinary distance fog does not.
    float clear = smoothstep(0.2, 0.8, 1.0 - 16.0 * FogColor.a / max(FogSkyEnd, 0.001));
    vec3 color = mix(sky.rgb, dbh_sky(sky.rgb, normalize(skyPos), dbh_time(GameTime)), clear);
    fragColor = vec4(color, sky.a);
}
"""

STARS_VSH = """$HEAD
#$IMPORT <minecraft:dynamictransforms.glsl>
#$IMPORT <minecraft:projection.glsl>
#$IMPORT <minecraft:diamond_starfield.glsl>

${L0}in vec3 Position;

${L0}out vec3 skyDir;
${L1}out float skyTrust;

void main() {
    // Vanilla draws ~1500 small star squares with this shader. Diamond SMP turns the first two
    // into one full-screen layer (opposite windings, so exactly one survives culling) and
    // collapses the rest; the fragment shader then paints the real night sky.
    int id = $VID;
    if (id >= 8) {
        gl_Position = vec4(0.0, 0.0, 2.0, 1.0);
        skyDir = Position;
        skyTrust = 0.0;
        return;
    }
    int corner = id & 3;
    vec2 c = vec2(corner == 1 || corner == 2 ? 1.0 : -1.0, corner >= 2 ? 1.0 : -1.0);
    if (id >= 4) {
        c = c.yx;
    }
    gl_Position = vec4(c, 0.99999, 1.0);
    skyDir = dsf_world_ray(mat3(ModelViewMat), ProjMat, c, skyTrust);
}
"""

STARS_FSH = """$HEAD
#$IMPORT <minecraft:dynamictransforms.glsl>
#$IMPORT <minecraft:globals.glsl>
#$IMPORT <minecraft:diamond_starfield.glsl>

${L0}in vec3 skyDir;
${L1}in float skyTrust;

${L0}out vec4 fragColor;

void main() {
    vec3 dir = normalize(skyDir);
    float px = 0.5 * (length(dFdx(dir)) + length(dFdy(dir)));   // angular size of a pixel
    if (!gl_FrontFacing) {
        discard;
    }
    // ColorModulator.a is vanilla's star brightness: 0 by day and in rain, 0.5 on a clear night.
    vec3 color = dsf_night_sky(dir, px, dsf_time(GameTime));
    fragColor = vec4(color * (clamp(2.0 * ColorModulator.a, 0.0, 1.0) * skyTrust), 1.0);
}
"""


def stage_source(template, style):
    s = STYLE[style]
    return Template(template).substitute(HEAD=s["HEAD"], IMPORT=s["IMPORT"], VID=s["VID"],
                                         L0=s["LOC"](0), L1=s["LOC"](1), L2=s["LOC"](2))


@lru_cache(maxsize=None)
def overlay_files(quality="high"):
    sky_inc, star_inc = include_blackhole(quality), include_starfield(quality)
    files = {}
    for d, _, _, _, style in VARIANTS:
        files[f"{d}/{SHADERS}/core/sky.vsh"] = stage_source(SKY_VSH, style)
        files[f"{d}/{SHADERS}/core/sky.fsh"] = stage_source(SKY_FSH, style)
        files[f"{d}/{SHADERS}/core/stars.vsh"] = stage_source(STARS_VSH, style)
        files[f"{d}/{SHADERS}/core/stars.fsh"] = stage_source(STARS_FSH, style)
        files[f"{d}/{SHADERS}/include/diamond_blackhole.glsl"] = sky_inc
        files[f"{d}/{SHADERS}/include/diamond_starfield.glsl"] = star_inc
    return files


def overlay_entries():
    return [{"directory": d, "min_format": lo, "max_format": hi} for d, _, lo, hi, _ in VARIANTS]


# ---------------------------------------------------------------------------
# Checks: compile every shipped shader against the real vanilla includes
# ---------------------------------------------------------------------------


def resolve_includes(src, version, ours):
    """Inline #moj_import / #include like Minecraft does (each file once)."""
    inc_dir = VANILLA / f"mc_{version}" / SHADERS / "include"
    seen = set()

    def expand(text):
        out = []
        for line in text.splitlines():
            m = re.match(r"\s*#(?:moj_import|include)\s*<minecraft:([\w/.]+)>", line)
            if not m:
                out.append(line)
                continue
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            body = ours[name] if name in ours else (inc_dir / name).read_text()
            body = "\n".join(ln for ln in body.splitlines()
                             if not ln.startswith("#version") and not ln.startswith("#extension"))
            out.append(expand(body))
        return "\n".join(out)
    return expand(src)


def validate(quality="high", verbose=True):
    """Compile each overlay's shaders with glslangValidator using every covered version's vanilla
    includes (26.3 in Vulkan mode, which is how it is built). Returns True if all pass."""
    exe = shutil.which("glslangValidator")
    if exe is None:
        print("glslangValidator not installed: skipping shader compile check")
        return True
    ok = True
    files = overlay_files(quality)
    tmp = HERE / ".cache" / "shader_check"
    tmp.mkdir(parents=True, exist_ok=True)
    for d, versions, _, _, style in VARIANTS:
        ours = {name: files[f"{d}/{SHADERS}/include/{name}"]
                for name in ("diamond_blackhole.glsl", "diamond_starfield.glsl")}
        for version in versions:
            if not (VANILLA / f"mc_{version}").exists():
                print(f"  {d}: vanilla {version} shaders not cached, skipping")
                continue
            # 26.3 writes its shaders in Vulkan GLSL (gl_VertexIndex), so check them that way
            modes = ([("Vulkan", ["-V", "--amb", "--aml", "-o", str(tmp / "out.spv")])] if style == "include"
                     else [("GL", [])])
            for prog in ("sky", "stars"):
                for stage, ext in (("vsh", "vert"), ("fsh", "frag")):
                    src = resolve_includes(files[f"{d}/{SHADERS}/core/{prog}.{stage}"], version, ours)
                    path = tmp / f"{quality}_{d}_{version}_{prog}.{ext}"
                    path.write_text(src)
                    for mode, flags in modes:
                        res = subprocess.run([exe, *flags, str(path)], capture_output=True, text=True)
                        good = res.returncode == 0
                        ok &= good
                        if verbose or not good:
                            print(f"  {quality} {d} {prog}.{stage} ({mode}, vanilla {version}): "
                                  f"{'compiles OK' if good else 'FAILED'}")
                        if not good:
                            print(res.stdout[-3000:])
    return ok


def build_addon(quality="high", icon=None):
    q = QUALITY[quality]
    meta = {
        "pack": {
            "description": [
                "",
                {"text": "Diamond SMP ", "color": "aqua", "bold": True},
                {"text": q["label"], "color": "light_purple"},
                {"text": "\nLive black hole + real stars • no mods • 1.21.9+", "color": "gray"},
            ],
            "min_format": MIN_FORMAT,
            "max_format": MAX_FORMAT,
        },
        "overlays": {"entries": overlay_entries()},
    }
    out = ROOT / q["zip"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("pack.mcmeta", json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        if icon is not None and Path(icon).exists():
            z.write(icon, "pack.png")
        for name, text in sorted(overlay_files(quality).items()):
            z.writestr(name, text)
    print(f"wrote {out.name} ({out.stat().st_size / 1e3:.1f} kB)")
    return out


if __name__ == "__main__":
    ok = True
    for qual in QUALITY:
        build_addon(qual, ROOT / "pack" / "pack.png")
        ok &= validate(qual, verbose="-v" in sys.argv)
    print("all shaders compile" if ok else "SHADER COMPILE FAILURES")
    if "--preview" in sys.argv:
        import shader_preview
        shader_preview.main()
    sys.exit(0 if ok else 1)
