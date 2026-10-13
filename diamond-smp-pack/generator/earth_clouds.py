"""A weather snapshot for the Earth moon: one global cloud opacity map.

The map is what a geostationary mosaic (or a Blue Marble day) shows on a cloudy
day in late September, built from the general circulation of the atmosphere
rather than from imagery. Everything is drawn in 3-D on the unit sphere
(``natural_earth.unit_vectors``), so the map is seamless across the 180th
meridian and nothing pinches at the poles.

Meteorology
-----------
* ITCZ: the rising branch of the Hadley cells, a broken band of deep
  convective clusters (bright cores, cirrus anvils) 7-10 degrees north of the
  equator over the oceans, swelling over the Amazon, the Congo and the Maritime
  Continent, with the South Pacific Convergence Zone slanting off to the
  south-east and the Asian monsoon over the Bay of Bengal.
* Subtropical highs: the sinking branches dry the air, so the deserts (Natural
  Earth desert polygons plus the great dry zones) and most of the subtropical
  ocean are clear apart from a speckle of trade-wind cumulus.
* Marine stratocumulus: under the trade inversion, over the cold upwelling
  currents off the west coasts (California, Peru/Chile, Namibia/Angola, the
  Canaries, Western Australia), a bright deck of closed convective cells starts
  at the coast and breaks up into open cells and cumulus downstream. The decks
  are found from the land itself: sea with a continent upwind (east and
  poleward) inside the subtropical latitude window.
* Storm tracks (35-65 degrees, strongest over the North Pacific, the North
  Atlantic and all around the Southern Ocean): extratropical cyclones in their
  classic comma form. Each one is a frontal template (cold-front band trailing
  equatorward and west, a warm-front shield ahead, a dry slot behind) that is
  wound up by a vortex whose rotation falls off with radius, so the band near the
  low curls into the comma head: counter-clockwise in the north, clockwise in the
  south (the template is mirrored across the parallel). Open-cell cumulus fills
  the cold air behind the fronts; streaky cirrus runs along the jet ahead of them.
* Tropical cyclones: a central dense overcast with a clear eye and logarithmic
  spiral rain bands (pitch ~16 degrees) wound the same way as the extratropical
  lows.
* Patchy fair-weather cumulus over vegetated land, polar stratus over the
  Arctic Ocean and the Southern Ocean's ring of low cloud.

Texture
-------
Gradient noise with an independent random rotation for every octave (no
lattice-aligned artefacts) and a 32-bit integer hash lattice (no repeats),
domain warped, then pushed through a narrow threshold whose offset is the
inverse normal CDF of the local cloud fraction, so the cover follows the
climatology exactly while the edges stay crisp. Worley cells give the closed and
open mesoscale cellular convection. Octaves stop at the map's resolution, so a
larger map shows more detail of the same weather.
"""

import hashlib
import math
from functools import lru_cache

import numpy as np
from numba import njit, prange

import natural_earth as ne

# ---------------------------------------------------------------------------
# Climatology of a late-September day
# ---------------------------------------------------------------------------

COARSE_WIDTH = 1024          # smooth climate fields are built at most this wide and interpolated

# Zonal background cloud fraction (latitude, fraction) of ordinary weather cloud, before
# the explicit systems below are added; low in the subtropics, high in the storm tracks.
BACKGROUND_CF = (
    (-90.0, 0.10), (-78.0, 0.25), (-70.0, 0.75), (-62.0, 0.82), (-52.0, 0.78), (-44.0, 0.66),
    (-35.0, 0.42), (-26.0, 0.24), (-12.0, 0.20), (0.0, 0.26), (12.0, 0.22), (24.0, 0.18),
    (33.0, 0.34), (42.0, 0.55), (52.0, 0.65), (62.0, 0.68), (72.0, 0.70), (82.0, 0.70), (90.0, 0.70),
)
LAND_CF_SHIFT = -0.06        # continents in the late-summer storm tracks are a little clearer
# Optical thickness of that cloud relative to TAU_BG: shallow trade cumulus and stratocumulus in
# the subtropics, deep frontal cloud in the storm tracks, thin stratus over the poles.
BACKGROUND_THICKNESS = (
    (-90.0, 0.30), (-70.0, 0.75), (-55.0, 1.00), (-42.0, 0.90), (-30.0, 0.40), (-15.0, 0.25),
    (0.0, 0.45), (15.0, 0.25), (30.0, 0.40), (42.0, 0.90), (55.0, 1.00), (68.0, 0.70), (90.0, 0.45),
)

# ITCZ control points (longitude, latitude of the band, half-width deg, strength).
ITCZ = (
    (-180.0, 8.0, 6.0, 0.80), (-140.0, 8.5, 5.5, 0.75), (-110.0, 10.0, 6.0, 0.85),
    (-85.0, 9.0, 6.5, 0.90), (-65.0, 5.0, 8.5, 0.90), (-45.0, 7.0, 5.5, 0.80),
    (-25.0, 8.5, 5.0, 0.80), (0.0, 9.5, 6.0, 0.85), (25.0, 6.0, 8.5, 0.90),
    (45.0, 5.0, 6.0, 0.35), (70.0, 4.0, 7.0, 0.55), (90.0, 12.0, 8.0, 0.90),
    (110.0, 4.0, 10.0, 0.95), (130.0, 8.0, 9.0, 0.95), (155.0, 7.0, 7.0, 0.85),
)
SPCZ = ((-6.0, 152.0), (-27.0, -140.0), 4.0, 0.55)        # from, to, half-width deg, strength

# Extra deep convection (lat, lon, radius deg, strength): monsoon and rainforests.
CONVECTION = (
    (19.0, 88.0, 9.0, 0.75),      # Bay of Bengal monsoon
    (16.0, 102.0, 8.0, 0.60),     # Indochina
    (-1.0, -64.0, 11.0, 0.55),    # Amazon
    (1.0, 21.0, 8.0, 0.55),       # Congo
    (-3.0, 115.0, 10.0, 0.60),    # Maritime Continent
    (-5.0, 142.0, 6.0, 0.55),     # New Guinea
    (12.0, -86.0, 6.0, 0.50),     # Central America
    (10.0, 38.0, 5.0, 0.45),      # Ethiopian highlands
)

# Dry zones (lat, lon, radius deg, strength) under the subtropical highs and in rain shadows;
# also the summer-dry Mediterranean, Red Sea and Gulf, and the September dry seasons.
DRY_ZONES = (
    (22.0, 6.0, 13.0, 1.0), (24.0, 26.0, 10.0, 1.0),       # Sahara
    (22.0, 46.0, 9.0, 1.0), (20.0, 38.0, 4.0, 0.9),        # Arabia, Red Sea
    (27.0, 51.0, 3.0, 0.8), (31.0, 59.0, 7.0, 0.85),       # the Gulf, Iran and Afghanistan
    (26.0, 70.0, 4.5, 0.7), (42.0, 62.0, 8.0, 0.6),        # Thar, the Kazakh steppe
    (39.0, 83.0, 5.0, 0.7), (42.0, 103.0, 6.5, 0.6),       # Taklamakan, Gobi
    (32.0, -111.0, 6.0, 0.65),                             # Sonora, Mojave
    (-25.0, 131.0, 11.0, 0.95), (-17.0, 128.0, 7.0, 0.6),  # Australian interior, the dry north
    (-24.0, 20.0, 7.0, 0.9), (-16.0, 28.0, 9.0, 0.65),     # Kalahari, the southern African dry season
    (-23.0, -69.0, 4.0, 0.9), (-44.0, -68.0, 4.0, 0.4),    # Atacama, Patagonia
    (-13.0, -46.0, 9.0, 0.55), (-8.0, -39.0, 5.0, 0.6),    # cerrado dry season, caatinga
    (7.0, 46.0, 5.0, 0.6), (36.0, 17.0, 9.0, 0.55),        # Horn of Africa, the Mediterranean
)
DESERT_SKIP = ("PUNJAB",)

# Marine stratocumulus decks: subtropical sea with a coast upwind (east, then poleward).
DECK_DIST = (0.6, 1.5, 3.0, 5.0, 7.5, 10.5, 14.0, 18.0, 23.0)       # deg sampled upwind
DECK_AZ = ((60.0, 85.0, 105.0), (75.0, 95.0, 120.0))                  # azimuths (N, S hemisphere)
DECK_LAT = ((24.0, 9.0), (-17.0, 11.0))                               # centre, half-width
DECK_COLD = (                                                         # upwelling boost (lat, lon, r, s)
    (28.0, -128.0, 16.0, 1.0), (-17.0, -84.0, 18.0, 1.0), (-17.0, 4.0, 15.0, 1.0),
    (24.0, -22.0, 12.0, 0.8), (-27.0, 106.0, 12.0, 0.55),
)
DECK_BASE = 0.35

# Extratropical cyclones (lat, lon, size, swirl turns, cold-front length deg).
CYCLONES = (
    (58.0, -27.0, 1.10, 0.85, 36.0),     # mature low south of Iceland
    (45.0, -50.0, 0.80, 0.40, 26.0),     # a young wave off Newfoundland
    (49.0, 167.0, 1.00, 0.70, 34.0),     # north-west Pacific
    (54.0, -146.0, 1.05, 0.90, 32.0),    # occluded low in the Gulf of Alaska
    (61.0, 48.0, 0.80, 0.60, 22.0),      # over Russia
    (56.0, -98.0, 0.80, 0.55, 22.0),     # over Canada
    (-55.0, -105.0, 1.10, 0.80, 36.0),
    (-50.0, -38.0, 1.00, 0.70, 34.0),
    (-53.0, 25.0, 1.05, 0.80, 36.0),
    (-58.0, 82.0, 1.15, 0.90, 38.0),
    (-50.0, 138.0, 1.00, 0.65, 34.0),
    (-60.0, -168.0, 1.10, 0.85, 34.0),
)
CYCLONE_JITTER = (3.0, 7.0)          # seed-dependent lat/lon jitter, deg

# Tropical cyclones (lat, lon, eye radius, central dense overcast radius, outer band radius), deg.
HURRICANES = (
    (23.5, -63.0, 0.30, 2.1, 7.5),       # a major Atlantic hurricane
    (19.0, 133.0, 0.40, 2.8, 9.5),       # a super typhoon in the Philippine Sea
    (15.5, -112.0, 0.22, 1.4, 5.0),      # a smaller eastern Pacific hurricane
)
SPIRAL_PITCH_DEG = 16.0
CONV_CORE, CONV_ANVIL = 0.40, 0.80

# Optical depths. Opacity is tau / (tau + TAU_HALF), the shape of the two-stream albedo of a
# cloud layer, so thin edges and cirrus stay translucent and cores saturate smoothly.
TAU_HALF = 8.0
TAU_BG = 30.0                # ordinary weather cloud at one standard deviation above threshold
TAU_FRONT = 90.0             # frontal bands and comma heads
TAU_CELL = 8.0               # open-cell walls
TAU_DECK = 16.0              # marine stratocumulus
TAU_CORE = 130.0             # deep convective cores, hurricanes
TAU_ANVIL = 5.0              # cirrus anvils
TAU_CU = 4.0                 # fair-weather cumulus
TAU_CIRRUS = 3.5             # jet-stream cirrus
CELL_MEAN = 0.3              # mean wall coverage of unresolved open cells

# Texture
WARP_TROPICS, WARP_MIDLAT, WARP_CIRRUS = 0.008, 0.022, 0.03    # domain-warp amplitudes (radians)
LACUNARITY = 2.03
PERLIN_STD = 0.27            # standard deviation of one octave of 3-D gradient noise
EDGE = 0.30                  # half-width of the cloud/clear threshold, in noise standard deviations
N_ROT = 64

# ---------------------------------------------------------------------------
# Noise
# ---------------------------------------------------------------------------


@njit(cache=True, inline="always")
def _hash(ix, iy, iz, seed):
    h = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ (seed * 2654435761)
    h &= 0xFFFFFFFF
    h = ((h ^ (h >> 16)) * 0x45D9F3B) & 0xFFFFFFFF
    h = ((h ^ (h >> 16)) * 0x45D9F3B) & 0xFFFFFFFF
    return h ^ (h >> 16)


@njit(cache=True, inline="always")
def _grad(h, x, y, z):
    h &= 15
    u = x if h < 8 else y
    v = y if h < 4 else (x if (h == 12 or h == 14) else z)
    return (u if (h & 1) == 0 else -u) + (v if (h & 2) == 0 else -v)


@njit(cache=True, inline="always")
def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


@njit(cache=True)
def _perlin(x, y, z, seed):
    fx, fy, fz = math.floor(x), math.floor(y), math.floor(z)
    ix, iy, iz = int(fx), int(fy), int(fz)
    x -= fx
    y -= fy
    z -= fz
    u, v, w = _fade(x), _fade(y), _fade(z)
    n000 = _grad(_hash(ix, iy, iz, seed), x, y, z)
    n100 = _grad(_hash(ix + 1, iy, iz, seed), x - 1.0, y, z)
    n010 = _grad(_hash(ix, iy + 1, iz, seed), x, y - 1.0, z)
    n110 = _grad(_hash(ix + 1, iy + 1, iz, seed), x - 1.0, y - 1.0, z)
    n001 = _grad(_hash(ix, iy, iz + 1, seed), x, y, z - 1.0)
    n101 = _grad(_hash(ix + 1, iy, iz + 1, seed), x - 1.0, y, z - 1.0)
    n011 = _grad(_hash(ix, iy + 1, iz + 1, seed), x, y - 1.0, z - 1.0)
    n111 = _grad(_hash(ix + 1, iy + 1, iz + 1, seed), x - 1.0, y - 1.0, z - 1.0)
    x00 = n000 + u * (n100 - n000)
    x10 = n010 + u * (n110 - n010)
    x01 = n001 + u * (n101 - n001)
    x11 = n011 + u * (n111 - n011)
    y0 = x00 + v * (x10 - x00)
    y1 = x01 + v * (x11 - x01)
    return y0 + w * (y1 - y0)


@njit(cache=True)
def _fbm(rots, k0, x, y, z, freq, octaves, gain, seed):
    """Unit-variance fractal gradient noise; every octave in its own random orientation."""
    s, a, norm = 0.0, 1.0, 0.0
    n = rots.shape[0]
    for o in range(octaves):
        k = (k0 + o) % n
        rx = rots[k, 0, 0] * x + rots[k, 0, 1] * y + rots[k, 0, 2] * z
        ry = rots[k, 1, 0] * x + rots[k, 1, 1] * y + rots[k, 1, 2] * z
        rz = rots[k, 2, 0] * x + rots[k, 2, 1] * y + rots[k, 2, 2] * z
        s += a * _perlin(rx * freq, ry * freq, rz * freq, seed + 101 * (k0 + o))
        norm += a * a
        a *= gain
        freq *= LACUNARITY
    if norm == 0.0:
        return 0.0
    return s / (PERLIN_STD * math.sqrt(norm))


@njit(cache=True)
def _worley(x, y, z, seed):
    """Distances to the nearest and second-nearest feature point (lattice units)."""
    fx, fy, fz = math.floor(x), math.floor(y), math.floor(z)
    ix, iy, iz = int(fx), int(fy), int(fz)
    f1, f2 = 9.0, 9.0
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            for dz in range(-1, 2):
                h = _hash(ix + dx, iy + dy, iz + dz, seed)
                px = ix + dx + (h & 1023) / 1023.0
                py = iy + dy + ((h >> 10) & 1023) / 1023.0
                pz = iz + dz + ((h >> 20) & 1023) / 1023.0
                d = (px - x) ** 2 + (py - y) ** 2 + (pz - z) ** 2
                if d < f1:
                    f2 = f1
                    f1 = d
                elif d < f2:
                    f2 = d
    return math.sqrt(f1), math.sqrt(f2)


@njit(cache=True)
def _cells(px, py, pz, freq, seed):
    """F2 - F1 of Worley cells on a warped lattice (wavy walls): 0 on a wall, ~0.5 inside."""
    f2 = 2.0 * freq
    ux = _perlin(px * f2, py * f2, pz * f2, seed + 1)
    uy = _perlin(py * f2, pz * f2, px * f2, seed + 2)
    uz = _perlin(pz * f2, px * f2, py * f2, seed + 3)
    a, b = _worley(px * freq + 1.3 * ux, py * freq + 1.3 * uy, pz * freq + 1.3 * uz, seed)
    return b - a


@njit(cache=True, inline="always")
def _pos(x):
    return x if x > 0.0 else 0.0


@njit(cache=True, inline="always")
def _sstep(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _random_rotations(n, rng):
    q, r = np.linalg.qr(rng.standard_normal((n, 3, 3)))
    q = q * np.sign(np.diagonal(r, axis1=1, axis2=2))[:, None, :]
    q[np.linalg.det(q) < 0, :, 0] *= -1.0
    return np.ascontiguousarray(q)


def _octaves(width, freq, px=1.6):
    """Octaves until the lattice spacing of the finest one is ~px map pixels."""
    f_max = width / (2.0 * math.pi * px)
    return max(1, int(math.floor(math.log(max(f_max / freq, 1.0)) / math.log(LACUNARITY))) + 1)


# ---------------------------------------------------------------------------
# Climate fields (smooth, built on a coarse grid with numpy)
# ---------------------------------------------------------------------------


def _inv_phi(p):
    """Inverse standard normal CDF (table based; p is clipped to [0.002, 0.998])."""
    z = np.linspace(-3.2, 3.2, 1281)
    cdf = 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))
    return np.interp(np.clip(p, 0.002, 0.998), cdf, z)


def _blur(m, sigma_deg):
    """Gaussian blur of an equirectangular map that is isotropic on the sphere."""
    h, w = m.shape
    lat, _ = ne.grid(w)
    k = np.fft.rfftfreq(w)                       # cycles per pixel
    sx = sigma_deg / (360.0 / w) / np.maximum(np.cos(np.radians(lat)), 1e-3)
    spec = np.fft.rfft(m, axis=1) * np.exp(-2.0 * (math.pi * k[None, :] * sx[:, None]) ** 2)
    out = np.fft.irfft(spec, n=w, axis=1)
    sy = sigma_deg / (180.0 / h)
    r = int(math.ceil(3.0 * sy))
    if r > 0:
        g = np.exp(-0.5 * (np.arange(-r, r + 1) / sy) ** 2)
        g /= g.sum()
        # across the pole the map continues on the opposite meridian
        top = np.roll(out[:r][::-1], w // 2, axis=1)
        bot = np.roll(out[-r:][::-1], w // 2, axis=1)
        pad = np.concatenate([top, out, bot], 0)
        out = sum(g[i] * pad[i:i + h] for i in range(2 * r + 1))
    return out


def _gc_dist(lat, lon, lat0, lon0):
    return ne.great_circle_deg(lat, lon, lat0, lon0)


def _zones(lat, lon, zones, power=2.0):
    out = np.zeros(np.broadcast(lat, lon).shape)
    for la, lo, r, s in zones:
        out = np.maximum(out, s * np.exp(-(_gc_dist(lat, lon, la, lo) / r) ** power))
    return out


def _destination(lat, lon, az_deg, d_deg):
    """Point reached from (lat, lon) after d degrees along initial azimuth az (from north)."""
    la, lo = np.radians(lat), np.radians(lon)
    az, d = math.radians(az_deg), math.radians(d_deg)
    la2 = np.arcsin(np.sin(la) * math.cos(d) + np.cos(la) * math.sin(d) * math.cos(az))
    lo2 = lo + np.arctan2(math.sin(az) * math.sin(d) * np.cos(la), math.cos(d) - np.sin(la) * np.sin(la2))
    return np.degrees(la2), (np.degrees(lo2) + 180.0) % 360.0 - 180.0


def _segment_dist(lat, lon, a, b):
    """Angular distance (deg) to the great-circle segment a-b."""
    def v(la, lo):
        la, lo = np.radians(la), np.radians(lo)
        return np.stack(np.broadcast_arrays(np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)), -1)
    p, va, vb = v(lat, lon), v(*a)[()], v(*b)[()]
    n = np.cross(va, vb)
    n /= np.linalg.norm(n)
    off = np.degrees(np.arcsin(np.clip(p @ n, -1, 1)))
    # inside the segment if the projection lies between a and b
    proj = p - (p @ n)[..., None] * n
    inside = (np.cross(va, proj) @ n >= 0) & (np.cross(proj, vb) @ n >= 0)
    da = _gc_dist(lat, lon, *a)
    db = _gc_dist(lat, lon, *b)
    return np.where(inside, np.abs(off), np.minimum(da, db))


def _desert_mask(width):
    feats = [f for f in ne.load("ne_10m_geography_regions_polys")
             if f["properties"].get("FEATURECLA") == "Desert" and f["properties"].get("NAME") not in DESERT_SKIP]
    return ne.rasterize(feats, width, ss=2)


def _climate(width, land):
    """Smooth climate fields on a coarse grid, stacked (K, H, W) float64.

    0 background cloud bias (inverse normal CDF of the cloud fraction), 1 deep convection
    activity, 2-3 convective core and anvil biases, 4 stratocumulus deck strength, 5 open-cell
    weight, 6 cumulus speckle weight, 7 cirrus weight, 8 aridity, 9 open sea, 10 thickness of
    the ordinary weather cloud."""
    lat, lon = ne.grid(width)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    land_s = _blur(land, 1.5)
    sea = 1.0 - np.clip(_blur(land, 0.35) * 1.8, 0.0, 1.0)

    arid = np.maximum(np.clip(_blur(_desert_mask(width), 2.0) * 1.6, 0, 1) * np.clip(land_s * 2, 0, 1),
                      _zones(la, lo, DRY_ZONES, power=3.0))
    arid = np.clip(arid, 0.0, 1.0)

    # Deep convection: ITCZ band, SPCZ, monsoon and rainforests.
    pts = np.array(ITCZ)
    xp = np.concatenate([pts[:, 0], [pts[0, 0] + 360.0]])
    def itp(col):
        return np.interp(lo, xp, np.concatenate([pts[:, col], [pts[0, col]]]))
    conv = itp(3) * np.exp(-((la - itp(1)) / itp(2)) ** 2)
    (a, b, wd, st) = SPCZ
    conv = np.maximum(conv, st * np.exp(-(_segment_dist(la, lo, a, b) / wd) ** 2))
    conv = np.maximum(conv, _zones(la, lo, CONVECTION, power=2.0) * (0.5 + 0.5 * np.clip(land_s * 1.5, 0, 1)))
    conv *= 1.0 - arid

    # Background weather.
    tab = np.array(BACKGROUND_CF)
    cf = np.interp(la, tab[:, 0], tab[:, 1])
    mid = np.exp(-((np.abs(la) - 48.0) / 14.0) ** 2)
    cf = cf + LAND_CF_SHIFT * land_s * mid
    cf = cf * (1.0 - 0.95 * arid)
    bias = _inv_phi(cf)
    tab = np.array(BACKGROUND_THICKNESS)
    thickness = np.interp(la, tab[:, 0], tab[:, 1])

    # Stratocumulus decks: a coast upwind within the subtropical window over cold water.
    coast = np.clip((_blur(land, 0.5) - 0.3) / 0.4, 0, 1)
    deck = np.zeros_like(la)
    for hemi, sel in ((0, la >= 0), (1, la < 0)):
        up = np.zeros_like(la)
        for d in DECK_DIST:
            g = 1.0 if d <= 7.0 else math.exp(-((d - 7.0) / 11.0) ** 2)
            for az in DECK_AZ[hemi]:
                l2, o2 = _destination(la, lo, az, d)
                up = np.maximum(up, ne.sample(coast, l2, o2) * g)
        c, w = DECK_LAT[hemi]
        deck = np.where(sel, up * np.exp(-((la - c) / w) ** 2), deck)
    cold = np.clip(DECK_BASE + _zones(la, lo, DECK_COLD, power=2.0), 0, 1)
    deck = _blur(deck, 1.0) * cold * sea * (1.0 - np.clip(conv * 1.5, 0, 1))

    # Open cells: the Southern Ocean's cold-air cumulus and the northern storm tracks.
    ocean = 1.0 - np.clip(land_s * 1.3, 0, 1)
    opencells = ocean * (0.85 * np.exp(-((la + 53.0) / 9.0) ** 2) + 0.45 * np.exp(-((la - 52.0) / 8.0) ** 2))

    # Cumulus speckle: trade cumulus over the subtropical sea and fair-weather cumulus on land.
    trade = ocean * np.exp(-((np.abs(la) - 16.0) / 11.0) ** 2) * 0.85
    cu_land = np.clip(land_s * 1.4, 0, 1) * (0.35 + 0.45 * np.exp(-(la / 18.0) ** 2)) * (np.abs(la) < 72)
    speck = np.maximum(trade, cu_land) * (1.0 - arid)

    # Cirrus: the subtropical and polar jets, and anvil debris around tropical convection.
    cirrus = 0.55 * np.exp(-((np.abs(la) - 42.0) / 11.0) ** 2) + 0.7 * _blur(conv, 4.0)
    cirrus *= (1.0 - 0.85 * arid) * (np.abs(la) < 72)

    # Convective cores cover ~40 % and anvils ~80 % of the most active convergence zones.
    core = _inv_phi(CONV_CORE * conv)
    anvil = _inv_phi(CONV_ANVIL * conv)

    return np.ascontiguousarray(np.stack([bias, conv, core, anvil, deck, opencells, speck, cirrus, arid, ocean,
                                          thickness]))


@lru_cache(maxsize=4)
def _climate_cached(width, land):
    return _climate(width, land.arr.astype(np.float64))


def _storms(seed):
    """Cyclone and hurricane parameter tables: centre, local east and north vectors, shape."""
    rng = np.random.default_rng(seed + 7)

    def frame(la, lo):
        a, b = math.radians(la), math.radians(lo)
        c = [math.cos(a) * math.cos(b), math.cos(a) * math.sin(b), math.sin(a)]
        e = [-math.sin(b), math.cos(b), 0.0]
        n = [-math.sin(a) * math.cos(b), -math.sin(a) * math.sin(b), math.cos(a)]
        return c + e + n

    cy = []
    for la, lo, size, turns, length in CYCLONES:
        la += rng.uniform(-1, 1) * CYCLONE_JITTER[0]
        lo += rng.uniform(-1, 1) * CYCLONE_JITTER[1]
        hemi = 1.0 if la >= 0 else -1.0
        cy.append(frame(la, lo) + [hemi, size * rng.uniform(0.92, 1.08), turns * rng.uniform(0.85, 1.15),
                                   length, rng.uniform(-0.3, 0.3), float(rng.integers(1, 1 << 20))])
    hu = []
    for la, lo, r_eye, r_cdo, r_out in HURRICANES:
        hemi = 1.0 if la >= 0 else -1.0
        hu.append(frame(la, lo) + [hemi, r_eye, r_cdo, r_out, float(rng.integers(1, 1 << 20))])
    return np.array(cy, dtype=np.float64), np.array(hu, dtype=np.float64)


# ---------------------------------------------------------------------------
# The per-pixel weather kernel
# ---------------------------------------------------------------------------

N_LAYERS = 8     # background, cyclones, cells, deck, convection, cumulus, cirrus, hurricanes


@njit(cache=True, inline="always")
def _local(st, px, py, pz):
    """Gnomonic-angle coordinates (deg) of p around a storm: x east, y north (mirrored in the south)."""
    cd = px * st[0] + py * st[1] + pz * st[2]
    ex = px * st[3] + py * st[4] + pz * st[5]
    ny = px * st[6] + py * st[7] + pz * st[8]
    return cd, math.degrees(math.atan2(ex, cd)), st[9] * math.degrees(math.atan2(ny, cd))


@njit(cache=True)
def _streaks(x, y, seed, octaves):
    """Noise stretched 6:1 along y in a storm's (wound-up) frame: cloud streets along the flow."""
    s, a, norm, f = 0.0, 1.0, 0.0, 0.35
    for o in range(octaves):
        s += a * _perlin(x * f, y * f / 6.0, 0.5 + 7.3 * o, seed + o)
        norm += a * a
        a *= 0.6
        f *= LACUNARITY
    return s / (PERLIN_STD * math.sqrt(norm))


@njit(cache=True)
def _cyclone(x, y, size, turns, length, tilt, seed, octaves):
    """Comma-cloud template of a northern-hemisphere low at the origin (deg, x east, y north).

    Returns (frontal cloud thickness, cold-air cell weight, dry-slot weight, jet cirrus weight)."""
    x /= size
    y /= size
    r = math.sqrt(x * x + y * y)
    # wind it up: the rotation is concentrated in the core, so only the band's poleward end curls
    # into the comma head while the trailing front stays nearly straight
    th = turns * 2.0 * math.pi * math.exp(-(r / 5.5) ** 2)
    c, s = math.cos(th), math.sin(th)
    xs = x * c + y * s
    ys = -x * s + y * c
    # cold front: sharp on the cold (west) side, frayed on the warm side, fading at its far end
    xf = 3.0 + (0.30 + tilt * 0.2) * ys - 0.012 * ys * ys
    w = max(3.6 + 0.05 * ys, 1.6)
    d = xs - xf
    if d < 0.0:
        prof = math.exp(-(d / (0.8 * w)) ** 4)
    else:
        prof = math.exp(-(d / (1.5 * w)) ** 2)
    along = _sstep(-length, -0.5 * length, ys) * _sstep(11.0, 6.0, ys)
    front = prof * along
    # warm-front shield north-east of the low
    e = ((xs - 8.0) / 12.0) ** 2 + ((ys - 5.0) / 6.0) ** 2
    head = math.exp(-e ** 1.5)
    dry = math.exp(-(((xs + 2.0) / 5.0) ** 2 + ((ys + 3.5) / 4.5) ** 2) ** 1.5)
    thick = max(front, head) * (1.0 - 0.9 * dry)
    if thick > 0.05:
        thick *= max(0.8 + 0.2 * _streaks(xs, ys, seed, octaves), 0.45)
    cold = _sstep(0.5, 5.0, -(d + w)) * _sstep(-length, -0.4 * length, ys) * _sstep(4.0, -3.0, ys)
    cold *= math.exp(-(r / length) ** 2) * (1.0 - dry)
    jet = math.exp(-((d - 1.8 * w) / (1.8 * w)) ** 2) * _sstep(-0.9 * length, -0.3 * length, ys) * _sstep(14.0, 2.0, ys)
    return thick, cold, dry, jet


@njit(cache=True)
def _hurricane(x, y, r_eye, r_cdo, r_out, n1, n2, n3):
    r = math.sqrt(x * x + y * y) + 1e-6
    phi = math.atan2(y, x)
    eye = _sstep(0.55 * r_eye, 1.35 * r_eye, r + 0.15 * r_eye * n3)
    wall = math.exp(-((r - 1.6 * r_eye) / (0.8 * r_eye)) ** 2)
    cdo = _sstep(1.25, 0.75, r / r_cdo + 0.12 * n1)
    s = phi + math.log(r / r_cdo) / math.tan(math.radians(SPIRAL_PITCH_DEG))
    band = 0.5 + 0.5 * math.cos(2.0 * s + 0.9 * n2)
    band = _sstep(0.45, 0.9, band) * _sstep(r_out, 0.9 * r_cdo, r + 0.6 * n1) * _sstep(0.6 * r_cdo, r_cdo, r)
    halo = _sstep(1.25 * r_out, 0.8 * r_cdo, r) * 0.45 * _sstep(-1.0, 1.0, n2)
    return max(max(cdo * (0.9 + 0.1 * wall), 0.85 * band), halo) * eye


@njit(parallel=True, cache=True)
def _cloud_kernel(width, r0, c0, fields, land, rots, cyc, hur, oct_bg, oct_det, f_max, seed, out, layers):
    """out[i, j] = cloud opacity of map pixel (r0 + i, (c0 + j) mod width); `layers` (N_LAYERS,
    rows, cols) receives the separate layers when it has the shape of out, else is ignored."""
    h = width // 2
    hc, wc = fields.shape[1], fields.shape[2]
    nf = fields.shape[0]
    # open cells are drawn only where the map resolves them, else replaced by their mean
    cell_vis = min(max((f_max / 30.0 - 2.5) / 2.5, 0.0), 1.0)
    debug = layers.shape[1] == out.shape[0] and layers.shape[2] == out.shape[1]
    for ii in prange(out.shape[0]):
        i = r0 + ii
        lat = math.radians(90.0 - (i + 0.5) * 180.0 / h)
        cl, sl = math.cos(lat), math.sin(lat)
        yc = min(max((i + 0.5) * hc / h - 0.5, 0.0), hc - 1.0)
        i0 = min(int(yc), hc - 2)
        fy = yc - i0
        fv = np.empty(nf)
        lay = np.zeros(N_LAYERS)
        for jj in range(out.shape[1]):
            j = (c0 + jj) % width
            lon = math.radians(-180.0 + (j + 0.5) * 360.0 / width)
            px, py, pz = cl * math.cos(lon), cl * math.sin(lon), sl
            # climate fields, bilinear (wrapping in longitude)
            xc = (j + 0.5) * wc / width - 0.5
            j0 = int(math.floor(xc))
            fx = xc - j0
            j0 %= wc
            j1 = (j0 + 1) % wc
            for k in range(nf):
                top = fields[k, i0, j0] * (1.0 - fx) + fields[k, i0, j1] * fx
                bot = fields[k, i0 + 1, j0] * (1.0 - fx) + fields[k, i0 + 1, j1] * fx
                fv[k] = top * (1.0 - fy) + bot * fy
            bias, conv, core_b, anvil_b, deck = fv[0], fv[1], fv[2], fv[3], fv[4]
            opencell, speck, cirrus_w, arid, sea, thk = fv[5], fv[6], fv[7], fv[8], fv[9], fv[10]

            # large-scale domain warp: the westerlies stretch mid-latitude cloud into filaments,
            # the tropics are barely sheared
            wx = _fbm(rots, 0, px, py, pz, 1.6, 2, 0.4, seed + 1)
            wy = _fbm(rots, 3, px, py, pz, 1.6, 2, 0.4, seed + 2)
            wz = _fbm(rots, 6, px, py, pz, 1.6, 2, 0.4, seed + 3)
            amp = WARP_TROPICS + (WARP_MIDLAT - WARP_TROPICS) * _sstep(0.42, 0.77, abs(pz))
            qx, qy, qz = px + amp * wx, py + amp * wy, pz + amp * wz

            # shared detail: ragged edges (det) and the brightness texture of cloud tops (tex)
            det = _fbm(rots, 30, px, py, pz, 14.0, oct_det, 0.55, seed + 5)
            tex = _fbm(rots, 40, qx, qy, qz, 6.0, oct_det + 1, 0.6, seed + 6)

            # storms: comma clouds and hurricanes
            thick, cold, dry, jet, hurr = 0.0, 0.0, 0.0, 0.0, 0.0
            for c in range(cyc.shape[0]):
                cd, x, y = _local(cyc[c], px, py, pz)
                if cd < 0.64:
                    continue
                t, co, dr, je = _cyclone(x + 5.0 * wx, y + 5.0 * wy, cyc[c, 10], cyc[c, 11], cyc[c, 12],
                                         cyc[c, 13], int(cyc[c, 14]), oct_det)
                thick = max(thick, t)
                cold = max(cold, co)
                dry = max(dry, dr)
                jet = max(jet, je)
            for c in range(hur.shape[0]):
                cd, x, y = _local(hur[c], px, py, pz)
                if cd < 0.97:
                    continue
                n1 = _fbm(rots, 20, px, py, pz, 40.0, 3, 0.5, seed + 31)
                n2 = _fbm(rots, 23, px, py, pz, 90.0, 2, 0.5, seed + 32)
                n3 = _fbm(rots, 25, px, py, pz, 200.0, 1, 0.5, seed + 33)
                hurr = max(hurr, _hurricane(x, y, hur[c, 10], hur[c, 11], hur[c, 12], n1, n2, n3))

            # Each layer is an optical depth that grows from zero at the cloud edge with the
            # "water excess" w of its noise above the local threshold; depths of overlapping
            # layers add.

            # ordinary weather: warped large scales, unwarped fine scales, thresholded at the
            # local cloud fraction
            lo_n = _fbm(rots, 9, qx, qy, qz * 1.25, 2.2, 4, 0.5, seed + 4)
            hi_n = _fbm(rots, 13, px, py, pz, 2.2 * LACUNARITY ** 4, max(oct_bg - 4, 1), 0.6, seed + 14)
            w = (lo_n + 0.45 * hi_n) * 0.912 + bias - 1.8 * dry
            t_bg = TAU_BG * thk * _pos(w) ** 1.5 * math.exp(0.35 * tex)

            w = thick - 0.24 + 0.26 * det * min(3.0 * thick, 1.0)
            t_cy = TAU_FRONT * _pos(w) ** 1.3 * math.exp(0.25 * tex) * (1.0 - 0.8 * arid)

            # mesoscale cellular convection (Worley cells): open cells behind cold fronts and
            # over the Southern Ocean, closed cells in the stratocumulus decks
            t_cell, t_deck = 0.0, 0.0
            wcell = max(opencell * (1.0 - dry), cold * sea)
            if wcell > 0.01:
                # open cells: rings of cumulus (beaded walls) around clear centres
                walls = CELL_MEAN
                if cell_vis > 0.0:
                    bead = _sstep(-0.8, 0.8, _perlin(px * 75.0, py * 75.0, pz * 75.0, seed + 18) / PERLIN_STD)
                    ring = (1.0 - _sstep(0.0, 0.22, _cells(px, py, pz, 30.0, seed + 7))) * (0.5 + 0.5 * bead)
                    walls = cell_vis * ring + (1.0 - cell_vis) * CELL_MEAN
                t_cell = TAU_CELL * wcell * walls * _sstep(-1.0, 0.6, det + 1.5 * wcell - 0.7)
            if deck > 0.01:
                closed = 0.82 + 0.18 * _sstep(0.02, 0.25, _cells(px, py, pz, 80.0, seed + 8))
                w = min(0.35 * det + 2.2 * (deck - 0.38), 1.2)
                t_deck = TAU_DECK * _pos(w) ** 1.2 * closed * math.exp(0.2 * tex)
                # where the deck thins out downstream it breaks into open cells
                brk = deck * _sstep(0.75, 0.25, deck)
                if brk > 0.01:
                    ring = CELL_MEAN
                    if cell_vis > 0.0:
                        ring = cell_vis * (1.0 - _sstep(0.0, 0.25, _cells(px, py, pz, 38.0, seed + 9))) \
                            + (1.0 - cell_vis) * CELL_MEAN
                    t_deck += TAU_CELL * brk * ring

            # deep convection: clusters with bright cores and cirrus anvils
            t_cv = 0.0
            if conv > 0.01:
                nc = _fbm(rots, 50, px + 0.006 * wx, py + 0.006 * wy, pz + 0.006 * wz, 8.0, oct_det + 1, 0.6, seed + 9)
                t_cv = TAU_CORE * _pos(nc + core_b) ** 1.3
                t_cv += TAU_ANVIL * _pos(nc + anvil_b) ** 0.8 * (0.5 + 0.5 * _sstep(-1.2, 1.2, det))

            # fair-weather and trade cumulus: small, sparse, thin
            t_sp = 0.0
            if speck > 0.01:
                ns = _fbm(rots, 60, px, py, pz, 30.0, max(oct_det - 1, 1), 0.65, seed + 10)
                t_sp = TAU_CU * _pos(ns - 2.0 + 1.2 * speck + 0.5 * det) ** 1.2

            # cirrus: zonally stretched, meandering streaks
            t_ci = 0.0
            cw = max(cirrus_w, 0.75 * jet)
            if cw > 0.01:
                cx, cy, cz = px + WARP_CIRRUS * wx, py + WARP_CIRRUS * wy, pz + WARP_CIRRUS * wz
                nci = _fbm(rots, 70, cx * 2.0, cy * 2.0, cz * 9.0, 3.0, oct_det, 0.62, seed + 11)
                t_ci = TAU_CIRRUS * cw * _pos(nci + 1.4 * cw - 0.8)

            t_hu = TAU_CORE * hurr ** 1.5

            lay[0], lay[1], lay[2], lay[3] = t_bg, t_cy, t_cell, t_deck
            lay[4], lay[5], lay[6], lay[7] = t_cv, t_sp, t_ci, t_hu
            tau = 0.0
            for k in range(N_LAYERS):
                tau += lay[k]
                if debug:
                    layers[k, ii, jj] = lay[k] / (lay[k] + TAU_HALF)
            out[ii, jj] = tau / (tau + TAU_HALF)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class _Frozen:
    """Hashable wrapper so an array argument can key functools.lru_cache."""

    def __init__(self, arr):
        self.arr = np.ascontiguousarray(arr, dtype=np.float32)
        self.key = (self.arr.shape, hashlib.blake2b(self.arr.tobytes(), digest_size=16).hexdigest())

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return isinstance(other, _Frozen) and other.key == self.key


def _resample(m, width):
    h = width // 2
    if m.shape == (h, width):
        return np.asarray(m, dtype=np.float64)
    k = m.shape[1] // width
    if k >= 1 and m.shape == (h * k, width * k):
        return m.reshape(h, k, width, k).mean(axis=(1, 3)).astype(np.float64)
    lat, lon = ne.grid(width)
    return ne.sample(np.asarray(m, dtype=np.float64), lat[:, None], lon[None, :])


def cloud_map(width=2048, seed=1972, land=None):
    """Cloud opacity (W//2, W) float32 in 0..1 (1 = thick bright cloud, 0.2-0.5 = thin cirrus
    or haze the ground shows through). `land` is an optional land-fraction map in the same
    convention (any width); without it ne_50m_land is rasterised."""
    return _cloud_map(int(width), int(seed), None if land is None else _Frozen(land))


@lru_cache(maxsize=8)
def _cloud_map(width, seed, land):
    out = _render(width, seed, None if land is None else land.arr)[0]
    out.setflags(write=False)
    return out


def _render(width, seed, land=None, window=None, debug=False):
    """Cloud opacity of a window (row0, row1, col0, col1) of the map (columns may wrap past
    the dateline: col1 > width), optionally with the separate layers (N_LAYERS, rows, cols)."""
    land = ne.rasterize(ne.load("ne_50m_land"), width) if land is None else _resample(land, width)
    cw = min(width, COARSE_WIDTH)
    fields = _climate_cached(cw, _Frozen(_resample(land, cw)))
    cyc, hur = _storms(seed)
    rots = _random_rotations(N_ROT, np.random.default_rng(seed))
    r0, r1, c0, c1 = window if window is not None else (0, width // 2, 0, width)
    out = np.zeros((r1 - r0, c1 - c0), dtype=np.float32)
    layers = np.zeros((N_LAYERS, r1 - r0, c1 - c0) if debug else (N_LAYERS, 0, 0), dtype=np.float32)
    f_max = width / (2.0 * math.pi * 1.6)
    _cloud_kernel(width, r0, c0, fields, np.ascontiguousarray(land, dtype=np.float32), rots, cyc, hur,
                  _octaves(width, 2.2), _octaves(width, 14.0), f_max, seed, out, layers)
    return out, layers
