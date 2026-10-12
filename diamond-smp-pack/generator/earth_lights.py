"""The Earth at night: a city-lights map like NASA's Black Marble.

Built from public-domain Natural Earth data (natural_earth.py):

* Urban cores: ne_10m_urban_areas polygons (the built-up area of ~11,900 towns and
  cities), rasterised anti-aliased, so big conurbations show their real shapes.
* Cities: every ne_10m_populated_places_simple point (7,342 places with their
  metropolitan population). Each is a bright core plus a dimmer suburban halo.
  Emitted light grows a little slower than population (pop^0.85: big cities are
  denser), and the lit radius ~ sqrt(population) (12 km at a million people).
* The countryside: towns and villages too small for the catalogue appear as a
  speckle of faint points wherever the smoothed regional population density is
  high (the Ganges plain, eastern China, Java, the Po valley...), on land only.
* Electrification: lights per person differ hugely. Countries are scaled roughly
  as seen from orbit: North Korea is dark, sub-Saharan Africa dim, the Gulf
  states, the US, Europe, Japan and South Korea bright.
* The Nile: Egypt lives along the river, which shows as a bright thread from
  Aswan to the delta across the black Sahara.
* Gas flares: faint red-orange points over the big oil fields.

Colour is warm high-pressure-sodium orange with whiter LED cores in Europe, North
America and East Asia. Map convention: see natural_earth.py.
"""

import math
from functools import lru_cache

import numpy as np
from numba import njit

import natural_earth as ne

SODIUM = np.array([1.0, 0.52, 0.17])          # linear sRGB of (255, 190, 110)
LED = np.array([1.0, 0.86, 0.66])             # whiter modern street lighting
FLARE = np.array([1.0, 0.33, 0.08])
RADIUS_KM_PER_SQRT_POP = 0.012                # lit radius: 12 km for a million people
URBAN_GAIN = 0.30                             # brightness of a fully built-up pixel
RURAL_GAIN = 0.05
KM_PER_DEG = 111.2

# Lights per person relative to the world average, by country (ISO 3166 alpha-3).
ELECTRIC = {
    "PRK": 0.03, "USA": 1.6, "CAN": 1.4, "JPN": 1.5, "KOR": 1.6, "TWN": 1.5, "SAU": 2.0, "ARE": 2.2,
    "QAT": 2.2, "KWT": 2.2, "BHR": 2.0, "OMN": 1.6, "ISR": 1.6, "AUS": 1.3, "NZL": 1.2,
    "GBR": 1.3, "IRL": 1.2, "FRA": 1.2, "DEU": 1.2, "NLD": 1.4, "BEL": 1.5, "ESP": 1.3, "PRT": 1.2,
    "ITA": 1.3, "CHE": 1.1, "AUT": 1.1, "POL": 1.0, "CZE": 1.1, "RUS": 1.0, "UKR": 0.8, "TUR": 1.1,
    "IRN": 1.1, "IRQ": 0.9, "EGY": 1.2, "LBY": 1.2, "DZA": 0.9, "MAR": 0.9, "ZAF": 0.9, "IND": 0.55,
    "BGD": 0.35, "PAK": 0.45, "CHN": 0.9, "IDN": 0.55, "PHL": 0.6, "VNM": 0.6, "THA": 0.8, "MYS": 1.0,
    "MEX": 0.9, "BRA": 0.8, "ARG": 0.9, "CHL": 1.0, "MMR": 0.2, "AFG": 0.15, "NPL": 0.25,
}
SUB_SAHARAN = 0.22                            # default for sub-Saharan Africa
WHITE_LED = ("USA", "CAN", "GBR", "IRL", "FRA", "DEU", "NLD", "BEL", "ITA", "ESP", "PRT", "CHE", "AUT",
             "JPN", "KOR", "TWN", "SGP", "AUS", "ARE", "QAT", "ISR", "DNK", "NOR", "SWE", "FIN")

# (lat, lon, strength) of the biggest gas-flaring regions
FLARES = ((30.6, 47.4, 1.0), (31.0, 49.0, 0.7), (26.0, 50.0, 0.5), (5.0, 6.4, 1.0), (4.6, 7.2, 0.8),
          (61.2, 73.4, 0.9), (61.9, 75.5, 0.6), (48.0, -103.1, 0.6), (31.7, 6.1, 0.5), (29.0, 19.5, 0.4),
          (30.3, -103.5, 0.4), (38.0, 54.0, 0.3))


def _country_factor(adm0, lat, lon):
    f = np.array([ELECTRIC.get(str(a), np.nan) for a in adm0])
    africa = (lat < 15.0) & (lat > -35.0) & (lon > -20.0) & (lon < 52.0)
    default = np.where(africa, SUB_SAHARAN, 0.8)
    return np.where(np.isnan(f), default, f)


@njit
def _splat(img, lat, lon, sig_px, amp, col, width):
    """Add an elliptical Gaussian (wider in x by 1/cos(lat)) for each point, with longitude wrap."""
    h = img.shape[0]
    for k in range(lat.shape[0]):
        y = (90.0 - lat[k]) / 180.0 * h - 0.5
        x = (lon[k] + 180.0) / 360.0 * width - 0.5
        sy = sig_px[k]
        sx = sy / max(math.cos(math.radians(lat[k])), 0.05)
        ry, rx = int(3.0 * sy) + 1, int(3.0 * sx) + 1
        cy, cx = int(round(y)), int(round(x))
        for i in range(cy - ry, cy + ry + 1):
            if i < 0 or i >= h:
                continue
            dy = (i - y) / sy
            for j in range(cx - rx, cx + rx + 1):
                dx = (j - x) / sx
                w = amp[k] * math.exp(-0.5 * (dx * dx + dy * dy))
                if w < 1e-6:
                    continue
                jj = j % width
                for c in range(3):
                    img[i, jj, c] += w * col[k, c]


def blur_wrap(a, sigma_px):
    """Gaussian blur of an equirectangular field (FFT, wraps in longitude, mirrored at the poles)."""
    h, w = a.shape
    ext = np.concatenate([a[::-1], a, a[::-1]], 0)
    fy = np.fft.fftfreq(3 * h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    k = np.exp(-2.0 * (math.pi * sigma_px) ** 2 * (fx * fx + fy * fy))
    out = np.real(np.fft.ifft2(np.fft.fft2(ext) * k))
    return out[h:2 * h]


def _hash01(i, j, seed):
    """Deterministic per-pixel uniform random numbers in [0, 1)."""
    x = (i.astype(np.uint64) * np.uint64(73856093)) ^ (j.astype(np.uint64) * np.uint64(19349663)) ^ np.uint64(seed)
    x ^= x >> np.uint64(13)
    x *= np.uint64(0x5bd1e995)
    x ^= x >> np.uint64(15)
    return (x & np.uint64(0xFFFFFF)).astype(np.float64) / float(0x1000000)


@lru_cache(maxsize=None)
def city_lights(width=2048):
    """(H, W, 3) float32 linear radiance of the night side; brightest megacity cores ~1.0, dark elsewhere."""
    h = width // 2
    km_per_px = 180.0 * KM_PER_DEG / h
    img = np.zeros((h, width, 3))

    # Cities and towns
    lon, lat, p = ne.points(ne.load("ne_10m_populated_places_simple"), "pop_max", "adm0_a3")
    pop = np.maximum(p["pop_max"].astype(float), 1000.0)
    adm0 = p["adm0_a3"]
    elec = _country_factor(adm0, lat, lon)
    elec = np.where((adm0 == "RUS") & (lon > 60.0), elec * 0.55, elec)   # Siberia: sparse and dim
    white = np.isin(adm0.astype(str), WHITE_LED).astype(float)
    col = SODIUM[None, :] * (1 - 0.55 * white[:, None]) + LED[None, :] * (0.55 * white[:, None])
    radius_px = RADIUS_KM_PER_SQRT_POP * np.sqrt(pop) / km_per_px
    total = elec * (pop / 1e6) ** 0.85                               # light emitted, ~ population
    for scale, share in ((0.45, 0.7), (1.2, 0.3)):                    # core + suburban halo
        sig = np.maximum(radius_px * scale, 0.55)
        amp = share * total / (sig * sig)
        _splat(img, lat, lon, sig, amp, col, width)

    # Built-up areas: the real shapes of the conurbations
    urban = ne.rasterize(ne.load("ne_10m_urban_areas"), width, ss=4).astype(np.float64)
    lat_g, lon_g = ne.grid(width)
    la, lo = np.meshgrid(lat_g, lon_g, indexing="ij")

    # Regional population density (smoothed) -> how electrified and how crowded the land is
    dens = np.zeros((h, width))
    yi = np.clip(((90.0 - lat) / 180.0 * h).astype(int), 0, h - 1)
    xi = np.clip(((lon + 180.0) / 360.0 * width).astype(int), 0, width - 1)
    np.add.at(dens, (yi, xi), pop * elec)
    dens = np.maximum(blur_wrap(dens, 60.0 / km_per_px), 0.0)
    dens /= np.cos(np.radians(la)).clip(0.05) * km_per_px ** 2          # people (electrified) per km^2
    land = ne.rasterize(ne.load("ne_50m_land"), width, ss=2).astype(np.float64)

    urban_light = URBAN_GAIN * urban * np.clip(dens / 150.0, 0.25, 1.0)
    img += urban_light[..., None] * SODIUM[None, None, :]

    # Countryside: a speckle of small towns where the region is crowded
    ii, jj = np.meshgrid(np.arange(h), np.arange(width), indexing="ij")
    u = _hash01(ii, jj, 0x5EED)
    v = _hash01(ii, jj, 0xBEEF)
    p_town = np.clip(dens / 350.0, 0.0, 0.7) * land
    town = (u < p_town) * (0.25 + 1.5 * v ** 3)
    glow = np.clip(dens / 600.0, 0.0, 1.0) * land                       # unresolved villages
    img += (RURAL_GAIN * town + 0.012 * glow)[..., None] * SODIUM[None, None, :]

    # The Nile: a thread of light from Aswan to Cairo, then the delta fans out
    nile = np.zeros((h, width))
    for ft in ne.load("ne_50m_rivers_lake_centerlines"):
        if (ft["properties"].get("name") or "") != "Nile":
            continue
        for line in _lines(ft["geometry"]):
            for (x0, y0), (x1, y1) in zip(line[:-1], line[1:]):
                n = max(int(math.hypot(x1 - x0, y1 - y0) / (180.0 / h) * 2) + 1, 2)
                for t in np.linspace(0, 1, n):
                    lo_, la_ = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                    if 23.5 < la_ < 31.6:
                        i = int((90 - la_) / 180 * h)
                        j = int((lo_ + 180) / 360 * width) % width
                        nile[i, j] = 1.0
    nile = blur_wrap(nile, 0.6)
    img += (0.35 * np.clip(nile * 3.0, 0, 1))[..., None] * SODIUM[None, None, :]

    # Gas flares
    fl = np.array(FLARES)
    _splat(img, fl[:, 0], fl[:, 1], np.full(len(fl), 0.7), 0.25 * fl[:, 2], np.tile(FLARE, (len(fl), 1)), width)

    # Normalise: the brightest megacity cores -> ~1, gentle shoulder above
    ref = float(np.percentile(img.max(-1)[img.max(-1) > 0], 99.97))
    img /= max(ref, 1e-9)
    peak = img.max(-1, keepdims=True)
    soft = (1.0 + np.log(np.maximum(peak, 1.0))) / np.maximum(peak, 1.0)   # log shoulder above 1
    img = np.where(peak > 1.0, img * soft, img)
    return np.clip(img, 0.0, 1.5).astype(np.float32)


def _lines(geom):
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return geom["coordinates"]
    return []


if __name__ == "__main__":
    import os
    import time
    from PIL import Image
    t = time.time()
    m = city_lights(4096)
    print(f"city_lights(4096): {time.time() - t:.1f} s, max {m.max():.2f}, lit fraction {(m.max(-1) > 0.01).mean():.4f}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "earth_preview")
    os.makedirs(out, exist_ok=True)
    disp = (np.clip(m * 1.6, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)
    Image.fromarray(disp).save(os.path.join(out, "lights.png"))
    Image.fromarray(disp[400:1000, 1900:2600]).save(os.path.join(out, "lights_europe.png"))
    Image.fromarray(disp[600:1200, 2900:3500]).save(os.path.join(out, "lights_asia.png"))
    Image.fromarray(disp[500:1000, 300:1300]).save(os.path.join(out, "lights_usa.png"))
