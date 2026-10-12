"""Natural Earth vector data (public domain), rasterised onto equirectangular maps.

Natural Earth (naturalearthdata.com, "Made with Natural Earth") is in the public
domain. The GeoJSON layers are fetched once from the project's GitHub mirror into
generator/.cache/naturalearth/ and never shipped.

Map convention used by every Earth map in this pack
---------------------------------------------------
An equirectangular map of width W has shape (W // 2, W). Row i is centred on
latitude 90 - (i + 0.5) * 180 / H (row 0 = the north edge), column j on longitude
-180 + (j + 0.5) * 360 / W (east positive, column 0 = the 180th meridian).
"""

import json
import os
import urllib.request
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, ".cache", "naturalearth")
URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/{}.geojson"


def path(name):
    return os.path.join(DATA_DIR, f"{name}.geojson")


@lru_cache(maxsize=None)
def load(name):
    """Features of a Natural Earth layer, e.g. load('ne_50m_land') (downloaded on first use)."""
    p = path(name)
    if not os.path.exists(p):
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = p + ".part"
        urllib.request.urlretrieve(URL.format(name), tmp)
        os.replace(tmp, p)
    with open(p, encoding="utf-8") as fh:
        return tuple(json.load(fh)["features"])


def grid(width):
    """Pixel-centre latitudes (H,) and longitudes (W,) in degrees."""
    h = width // 2
    lat = 90.0 - (np.arange(h) + 0.5) * 180.0 / h
    lon = -180.0 + (np.arange(width) + 0.5) * 360.0 / width
    return lat, lon


def polygons(features):
    """Every polygon of the features as a list of rings (each an (N, 2) lon/lat array);
    the first ring is the outline, the rest are holes."""
    out = []
    for ft in features:
        g = ft.get("geometry")
        if not g:
            continue
        if g["type"] == "Polygon":
            out.append([np.asarray(r, dtype=np.float64)[:, :2] for r in g["coordinates"]])
        elif g["type"] == "MultiPolygon":
            out.extend([np.asarray(r, dtype=np.float64)[:, :2] for r in poly] for poly in g["coordinates"])
    return out


def rasterize(features, width, ss=4):
    """Fraction of each map pixel covered by the features' polygons (float32, (W//2, W)).

    Drawn ss x ss supersampled and box filtered, so coastlines are anti-aliased. Holes
    are cut out of their own polygon only; a polygon drawn later fills them again."""
    h = width // 2
    big = Image.new("L", (width * ss, h * ss), 0)
    draw = ImageDraw.Draw(big)
    sx, sy = width * ss / 360.0, h * ss / 180.0
    for rings in polygons(features):
        for k, ring in enumerate(rings):
            if len(ring) < 3:
                continue
            xy = np.stack([(ring[:, 0] + 180.0) * sx, (90.0 - ring[:, 1]) * sy], -1)
            draw.polygon([tuple(p) for p in xy], fill=255 if k == 0 else 0)
    small = big.resize((width, h), Image.BOX)
    return np.asarray(small, dtype=np.float32) / 255.0


def points(features, *keys):
    """Point features as (lon, lat, {key: values}) arrays."""
    lon, lat, props = [], [], {k: [] for k in keys}
    for ft in features:
        g = ft.get("geometry")
        if not g or g["type"] != "Point":
            continue
        lon.append(g["coordinates"][0])
        lat.append(g["coordinates"][1])
        for k in keys:
            props[k].append(ft["properties"].get(k))
    return np.asarray(lon, float), np.asarray(lat, float), {k: np.asarray(v) for k, v in props.items()}


def sample(m, lat_deg, lon_deg):
    """Bilinear sample of an equirectangular map (H, W[, C]) at lat/lon arrays (wraps in longitude)."""
    h, w = m.shape[:2]
    y = (90.0 - np.asarray(lat_deg, float)) / 180.0 * h - 0.5
    x = (np.asarray(lon_deg, float) + 180.0) / 360.0 * w - 0.5
    y = np.clip(y, 0.0, h - 1.0)
    i0 = np.clip(np.floor(y).astype(int), 0, h - 2)
    fy = y - i0
    j0 = np.floor(x).astype(int)
    fx = x - j0
    j0 %= w
    j1 = (j0 + 1) % w
    if m.ndim == 3:
        fy, fx = fy[..., None], fx[..., None]
    top = m[i0, j0] * (1 - fx) + m[i0, j1] * fx
    bot = m[i0 + 1, j0] * (1 - fx) + m[i0 + 1, j1] * fx
    return top * (1 - fy) + bot * fy


def unit_vectors(width):
    """Unit vectors (H, W, 3) of the map pixel centres: x towards (0N, 0E), y towards
    (0N, 90E), z to the north pole. Handy for seamless 3-D noise on the sphere."""
    lat, lon = grid(width)
    la, lo = np.radians(lat)[:, None], np.radians(lon)[None, :]
    return np.stack(np.broadcast_arrays(np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)), -1)


def great_circle_deg(lat1, lon1, lat2, lon2):
    a, b = np.radians(lat1), np.radians(lat2)
    d = np.radians(np.asarray(lon2) - np.asarray(lon1))
    c = np.sin(a) * np.sin(b) + np.cos(a) * np.cos(b) * np.cos(d)
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


if __name__ == "__main__":
    import time
    t = time.time()
    land = rasterize(load("ne_50m_land"), 2048)
    lat, lon = grid(2048)
    print(f"land fraction {float((land * np.cos(np.radians(lat))[:, None]).sum() / (np.cos(np.radians(lat)).sum() * 2048)):.3f}"
          f" (real 0.292), {time.time() - t:.1f} s")
    print("London land", float(sample(land, 51.5, -0.1)), "mid-Atlantic", float(sample(land, 30, -40)),
          "Sahara", float(sample(land, 23, 10)), "Pacific", float(sample(land, 0, -150)))
    Image.fromarray((land * 255).astype(np.uint8)).save(os.path.join(HERE, ".cache", "land_test.png"))
