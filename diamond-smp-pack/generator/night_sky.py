"""More things in the night sky, shared by the painted skybox (build_pack.py) and the live
Shader Sky (shader_sky.py) so both show them in the same places.

Everything sits in the pack's fixed sky (latitude 37 N, Sagittarius A* on the meridian,
see real_sky.py; Minecraft world frame: x east, y up, z south):

* Planets on the ecliptic: Venus low in the west as the evening star, Mars in Virgo,
  Jupiter in Libra and Saturn in Capricornus. They shine steadily (a planet is a disc,
  not a point, so it does not twinkle) and are not bent by the black hole: they are in
  our own solar system, in front of it.
* A great comet in the north-western sky: a bright coma, a broad curved yellow-white
  dust tail and a long straight blue ion tail, both pointing away from the Sun (which,
  at midnight in summer, is below the northern horizon).
* Zodiacal light: sunlight scattered by interplanetary dust, a faint band along the
  ecliptic, brighter towards the horizon nearest the Sun, plus the gegenschein, a faint
  oval glow at the anti-solar point.
* Airglow: the faint green (557.7 nm oxygen) and red glow of the upper atmosphere,
  ~90 km up, brightest a few degrees above the horizon where the line of sight runs
  through the most of the glowing layer (the van Rhijn effect).

Units: linear radiance on the scale of the Shader Sky's starfield, where the Milky Way
glows ~0.02-0.13 and a magnitude 0 star has a peak of 3 in a ~1 pixel dot. Point sources
are returned separately so each renderer can draw them with its own pixel kernel.
"""

import math
from functools import lru_cache

import numpy as np

import blackhole as bh
import real_sky

OBLIQUITY_DEG = 23.4393
SUN_ECL_LON = 86.0          # the Sun at the June solstice: Sgr A* on the meridian at midnight
R_EARTH_KM = 6371.0
AIRGLOW_KM = 90.0

# (name, ecliptic longitude, ecliptic latitude (deg), V magnitude, colour temperature K)
PLANETS = (
    ("Venus", 182.0, 1.5, -4.4, 5900.0),
    ("Mars", 197.0, 1.0, -1.2, 3900.0),
    ("Jupiter", 226.0, 1.1, -2.6, 5400.0),
    ("Saturn", 307.0, -1.8, 0.4, 4900.0),
)
STAR_GAIN = 3.0             # peak brightness of a magnitude 0 point (matches shader_sky.STAR_GAIN)
MW_GAIN = 0.13              # the Milky Way glow's gain in that scale (matches shader_sky.MW_GAIN)

# The comet: head position (its tails stream straight away from the Sun). Lengths in degrees.
COMET_ALT, COMET_AZ = 24.0, 302.0
COMET_DUST_LENGTH = 24.0
COMET_DUST_CURVE = 0.012    # dust tail bends (lags) by curve * s^2 degrees at s degrees along it
COMET_ION_LENGTH = 32.0
COMET_HEAD_MAG = 0.6
COMET_COMA_DEG = 0.35
COMET_DUST = np.array([1.00, 0.88, 0.70])     # sunlight scattered by dust: warm white
COMET_ION = np.array([0.35, 0.62, 1.00])      # CO+ ions: blue
COMET_COMA = np.array([0.80, 0.95, 0.85])     # C2 and CN gas glowing round the nucleus: green-white
COMET_GAIN = 0.22

ZODIACAL_GAIN = 0.030
GEGENSCHEIN_GAIN = 0.010
ZODIACAL_COLOUR = np.array([1.00, 0.93, 0.80])   # sunlight, slightly reddened by the dust
AIRGLOW_GREEN = np.array([0.30, 1.00, 0.45])     # O 557.7 nm
AIRGLOW_RED = np.array([1.00, 0.18, 0.12])       # O 630 nm and OH bands
AIRGLOW_GAIN = 0.010


def ecliptic_to_world(lon_deg, lat_deg):
    """World direction of ecliptic (J2000) longitude/latitude in degrees."""
    lon, lat = np.radians(np.asarray(lon_deg, float)), np.radians(np.asarray(lat_deg, float))
    eps = math.radians(OBLIQUITY_DEG)
    x = np.cos(lat) * np.cos(lon)
    y = np.cos(lat) * np.sin(lon)
    z = np.sin(lat)
    ye, ze = y * math.cos(eps) - z * math.sin(eps), y * math.sin(eps) + z * math.cos(eps)
    ra = np.degrees(np.arctan2(ye, x)) % 360.0
    dec = np.degrees(np.arcsin(np.clip(ze, -1.0, 1.0)))
    return real_sky.equatorial_to_world(ra, dec)


ECLIPTIC_POLE = bh.normalize(np.cross(ecliptic_to_world(0.0, 0.0), ecliptic_to_world(90.0, 0.0)))
SUN_DIR = ecliptic_to_world(SUN_ECL_LON, 0.0)


def planets():
    """[(name, world direction, peak brightness, linear RGB tint)] of the bright planets."""
    out = []
    for name, lon, lat, mag, temp in PLANETS:
        d = bh.normalize(ecliptic_to_world(lon, lat))
        out.append((name, d, STAR_GAIN * 10 ** (-0.4 * mag), bh.blackbody_colour(temp)))
    return out


def comet_frame():
    """Head direction H and the unit tangent T along which the tails stream at the head: on the
    sky, straight away from the Sun (the solar wind blows the ion tail exactly anti-sunward)."""
    h = bh.normalize(real_sky.horizontal_to_world(COMET_ALT, COMET_AZ))
    s = bh.normalize(SUN_DIR)
    t = bh.normalize(h * float(h @ s) - s)
    return h, t


def comet_head():
    h, _ = comet_frame()
    return h, STAR_GAIN * 10 ** (-0.4 * COMET_HEAD_MAG), np.array([0.92, 0.97, 1.0])


def _comet(d):
    h, t = comet_frame()
    n = np.cross(h, t)
    ch = np.clip(d @ h, -1.0, 1.0)
    # tangent-plane (gnomonic) coordinates around the head, in degrees
    s = np.degrees(np.arctan2(d @ t, ch))
    u = np.degrees(np.arctan2(d @ n, ch))
    front = ch > 0.2
    s_pos = np.maximum(s, 0.0)
    # Dust tail: curved, broadening, fading with distance from the head
    centre = COMET_DUST_CURVE * s_pos ** 2
    width = 0.35 + 0.16 * s_pos
    dust = np.exp(-0.5 * ((u - centre) / width) ** 2) * np.exp(-s_pos / (0.38 * COMET_DUST_LENGTH))
    dust *= (s > 0) * (1.0 - np.exp(-s_pos / 0.4))
    # Ion tail: narrow, straight, streaky, longer
    streak = 0.75 + 0.25 * np.cos(u * 9.0 + 0.6 * np.sin(s * 0.7))
    ion = np.exp(-0.5 * (u / (0.18 + 0.025 * s_pos)) ** 2) * np.exp(-s_pos / (0.45 * COMET_ION_LENGTH)) * streak
    ion *= (s > 0) * (1.0 - np.exp(-s_pos / 0.6))
    # Coma: the glowing gas cloud around the nucleus
    r = np.hypot(s, u)
    coma = np.exp(-r / COMET_COMA_DEG) * 3.0
    col = dust[..., None] * COMET_DUST + ion[..., None] * COMET_ION * 0.55 + coma[..., None] * COMET_COMA
    return COMET_GAIN * col * front[..., None]


def _zodiacal(d):
    beta = np.degrees(np.arcsin(np.clip(d @ ECLIPTIC_POLE, -1.0, 1.0)))      # ecliptic latitude
    elong = np.degrees(np.arccos(np.clip(d @ SUN_DIR, -1.0, 1.0)))           # angle from the Sun
    # Brightness falls steeply with elongation (roughly elong^-2.3 away from the Sun) and
    # with ecliptic latitude; the band widens towards the Sun.
    width = 9.0 + 14.0 * np.exp(-(elong - 40.0) / 45.0)
    band = np.exp(-np.abs(beta) / width) * (np.maximum(elong, 30.0) / 60.0) ** -2.3
    anti = np.exp(-0.5 * (((180.0 - elong) / 9.0) ** 2 + (beta / 6.0) ** 2))
    return (ZODIACAL_GAIN * band + GEGENSCHEIN_GAIN * anti)[..., None] * ZODIACAL_COLOUR


def _airglow(d):
    y = np.clip(d[..., 1], 0.0, 1.0)
    sin_z = np.sqrt(1.0 - y * y)
    k = R_EARTH_KM / (R_EARTH_KM + AIRGLOW_KM)
    van_rhijn = 1.0 / np.sqrt(1.0 - (k * sin_z) ** 2)                        # path length through the layer
    above = np.clip(d[..., 1] / 0.02, 0.0, 1.0)                              # cut off at the horizon
    green = van_rhijn * (0.6 + 0.4 * np.exp(-y / 0.25))
    red = van_rhijn * np.exp(-y / 0.08) * 0.35
    return AIRGLOW_GAIN * above[..., None] * (green[..., None] * AIRGLOW_GREEN + red[..., None] * AIRGLOW_RED)


def extended_radiance(dirs):
    """Linear radiance (..., 3) of the comet's tails and coma, zodiacal light and airglow."""
    d = bh.normalize(np.asarray(dirs, float))
    above = (d[..., 1] > -0.05)[..., None]
    return (_comet(d) + _zodiacal(d) + _airglow(d)) * above


def point_sources():
    """Planets and the comet's nucleus: [(name, world dir, peak brightness, RGB tint)]."""
    h, peak, col = comet_head()
    return planets() + [("Comet", h, peak, col)]


@lru_cache(maxsize=None)
def check_layout():
    """Altitude, azimuth and distance from the black hole of each object (degrees)."""
    rows = []
    for name, d, peak, _ in point_sources():
        alt, az = real_sky.horizontal(d)
        sep = math.degrees(math.acos(float(np.clip(d @ bh.normalize(real_sky.SGR_A_WORLD), -1, 1))))
        rows.append((name, float(alt), float(az), sep, float(peak)))
    return tuple(rows)


if __name__ == "__main__":
    for row in check_layout():
        print("%-8s alt %5.1f az %5.1f  %5.1f deg from the hole, peak %.2f" % row)
