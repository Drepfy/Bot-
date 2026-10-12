"""The Earth, seen from space, as Minecraft's moon (all eight phases).

The pack swaps the vanilla moon for our own planet. Every phase texture is a
rendered photograph of a globe built from public-domain Natural Earth map data
(``natural_earth.py``): true-colour surface (``earth_surface.py``), a weather
snapshot of clouds (``earth_clouds.py``) and the city lights of the night side
(``earth_lights.py``).

Geometry
--------
The texture sits on vanilla's moon quad (half-angle tangent 0.2, so it spans
22.6 degrees, see celestial.py). The globe is EARTH_DIAMETER_DEG across, north
up and east to the right, as anyone looking at the Earth from space sees it. The
phases use celestial.PHASE_GEOMETRY: the same Sun-Earth-observer phase angles and
lit sides as the moon textures, so the game's moon cycle becomes an Earth cycle
(full Earth on the first night, lit on the right while "waxing"). Each phase also
shows a different face of the turning planet (VIEWS), chosen so the sunlit side
shows famous continents and the night side famous city lights.

Shading (per sub-sample, then box filtered)
-------------------------------------------
* Land and ice: Lambertian reflectance times the sunlight that got through the
  air on the way down and up (Rayleigh + aerosol extinction with the Kasten-Young
  air mass, so the terminator turns orange-red and fades).
* Ocean: dark Lambertian water plus a wind-roughened specular sun glint
  (GGX microfacets, Schlick Fresnel with F0 = 0.02).
* Clouds: bright, slightly forward-scattering layer on top, casting shadows
  displaced away from the Sun near the terminator.
* Air: single-scattering Rayleigh (blue) and aerosol (Henyey-Greenstein,
  forward) path radiance, so the limb glows blue and a crescent Earth is
  wrapped in a bright rim; the thin atmosphere shell is drawn beyond the limb.
* Night: city lights where the Sun is below the local horizon, dimmed by clouds.
"""

import math
from functools import lru_cache

import numpy as np
from numba import njit, prange

import blackhole as bh
import celestial as cel

EARTH_DIAMETER_DEG = 7.0
R_EARTH_KM = 6371.0
ATMOSPHERE_KM = 120.0        # drawn shell beyond the limb (exaggerated x2.5 for visibility)
SHELL_EXAG = 2.5
SCALE_HEIGHT_KM = 8.0
CLOUD_KM = 8.0               # cloud-top height used for cloud shadows

# Zenith optical depths in the sRGB primaries' effective wavelengths (~610/550/465 nm).
TAU_RAYLEIGH = np.array([0.064, 0.097, 0.190])
TAU_AEROSOL = np.array([0.060, 0.070, 0.085])
AEROSOL_G = 0.70
OCEAN_ROUGHNESS = 0.12       # GGX alpha of the wind-roughened sea
CLOUD_ALBEDO = np.array([0.78, 0.80, 0.84])
LIGHTS_GAIN = 1.0            # display radiance of the brightest city cores
EXPOSURE = 1.25
SHELL_GAIN = 0.12            # brightness of the air shell beyond the limb

# Sub-observer (latitude, longitude) for each phase: which face of the Earth it shows.
VIEWS = {
    "full_moon": (2.0, 18.0),          # Africa, Arabia and Europe in full sun: the Blue Marble view
    "waning_gibbous": (12.0, -65.0),   # the Americas
    "third_quarter": (22.0, 100.0),    # India and Asia by day, China, Korea and Japan lit up at night
    "waning_crescent": (28.0, 62.0),   # a dawn crescent over Africa; Europe, the Gulf and India by night
    "new_moon": (32.0, 18.0),          # night side: Europe, the Nile and the Middle East, ringed by sunlit air
    "waxing_crescent": (28.0, -88.0),  # an evening crescent over the Atlantic; North America by night
    "first_quarter": (18.0, 82.0),     # East Asia and Australia by day; Europe, the Gulf and India by night
    "waxing_gibbous": (5.0, -40.0),    # South America, the Atlantic and West Africa
}


@lru_cache(maxsize=None)
def earth_maps(width=2048, seed=1972):
    """All map layers the renderer needs, on one equirectangular grid."""
    import earth_clouds
    import earth_lights
    import earth_surface
    surf = earth_surface.surface_maps(width)
    clouds = earth_clouds.cloud_map(width, seed, land=surf["land"])
    # pre-filter the point-like city lights a little so sampling them on the globe does not alias
    lights = earth_lights.city_lights(width).astype(np.float64)
    lights = np.stack([earth_lights.blur_wrap(lights[..., c], 0.8) for c in range(3)], -1).clip(0.0, None)
    return {
        "albedo": np.ascontiguousarray(surf["albedo"], dtype=np.float64),
        "water": np.ascontiguousarray(surf["water"] * (1.0 - surf["ice"]), dtype=np.float64),
        "relief": np.ascontiguousarray(surf["relief"], dtype=np.float64),
        "clouds": np.ascontiguousarray(clouds, dtype=np.float64),
        "lights": np.ascontiguousarray(lights, dtype=np.float64),
    }


def view_basis(lat_deg, lon_deg):
    """Earth-fixed vectors of the view axes: x right (east), y up (north), z towards us.

    Earth-fixed frame as natural_earth.unit_vectors: x to (0N, 0E), y to (0N, 90E), z north."""
    la, lo = math.radians(lat_deg), math.radians(lon_deg)
    towards = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    east = np.array([-math.sin(lo), math.cos(lo), 0.0])
    north = np.cross(towards, east)
    return np.stack([east, north, towards])          # rows


@njit(inline="always")
def _bil1(m, lat, lon):
    h, w = m.shape
    y = (90.0 - lat) / 180.0 * h - 0.5
    x = (lon + 180.0) / 360.0 * w - 0.5
    y = min(max(y, 0.0), h - 1.001)
    i = int(y)
    fy = y - i
    j = int(math.floor(x))
    fx = x - j
    j0 = j % w
    j1 = (j + 1) % w
    return ((m[i, j0] * (1 - fx) + m[i, j1] * fx) * (1 - fy)
            + (m[i + 1, j0] * (1 - fx) + m[i + 1, j1] * fx) * fy)


@njit(inline="always")
def _bil3(m, lat, lon, k):
    h, w = m.shape[0], m.shape[1]
    y = (90.0 - lat) / 180.0 * h - 0.5
    x = (lon + 180.0) / 360.0 * w - 0.5
    y = min(max(y, 0.0), h - 1.001)
    i = int(y)
    fy = y - i
    j = int(math.floor(x))
    fx = x - j
    j0 = j % w
    j1 = (j + 1) % w
    return ((m[i, j0, k] * (1 - fx) + m[i, j1, k] * fx) * (1 - fy)
            + (m[i + 1, j0, k] * (1 - fx) + m[i + 1, j1, k] * fx) * fy)


@njit(inline="always")
def _airmass(mu):
    """Kasten & Young (1989) relative air mass for a sun or view direction mu = cos(zenith)."""
    mu = min(max(mu, 0.0), 1.0)
    z = math.degrees(math.acos(mu))
    return 1.0 / (mu + 0.50572 * (96.07995 - z) ** -1.6364)


@njit(inline="always")
def _latlon(basis, nx, ny, nz):
    px = nx * basis[0, 0] + ny * basis[1, 0] + nz * basis[2, 0]
    py = nx * basis[0, 1] + ny * basis[1, 1] + nz * basis[2, 1]
    pz = nx * basis[0, 2] + ny * basis[1, 2] + nz * basis[2, 2]
    return math.degrees(math.asin(min(max(pz, -1.0), 1.0))), math.degrees(math.atan2(py, px))


@njit(parallel=True)
def _earth_kernel(us, vs, basis, lx, ly, lz, albedo, water, relief, clouds, lights,
                  tau_r, tau_a, g, rough, cloud_alb, lights_gain, shell, cloud_shift, shadow_scale,
                  shell_gain, out):
    """out[r, c, 0:3] = linear radiance (sunlight = 1) of the globe and its air shell.

    us, vs: view-plane coordinates in Earth radii (x right, y up); (lx, ly, lz) the
    unit vector to the Sun in the view frame (z towards the observer)."""
    cos_scat = -lz                      # cosine of the scattering angle (sun -> air -> observer)
    p_ray = 0.75 * (1.0 + cos_scat * cos_scat)
    g2 = g * g
    p_mie = (1.0 - g2) / (1.0 + g2 - 2.0 * g * cos_scat) ** 1.5
    # half vector for the sun glint (view direction is +z)
    hx, hy, hz = lx, ly, lz + 1.0
    hn = math.sqrt(hx * hx + hy * hy + hz * hz)
    if hn > 1e-9:
        hx, hy, hz = hx / hn, hy / hn, hz / hn
    a2 = rough * rough
    back = 0.15 + 0.85 * (1.0 + cos_scat) * 0.5          # the shell is faint in backlight-free views
    ring = 3.0 * math.exp(-((1.0 - cos_scat) / 0.012))   # only within ~9 degrees of exact alignment
    for r in prange(vs.shape[0]):
        v = vs[r]
        for c in range(us.shape[0]):
            u = us[c]
            d2 = u * u + v * v
            for k in range(3):
                out[r, c, k] = 0.0
            if d2 < 1.0:
                nz = math.sqrt(1.0 - d2)
                lat, lon = _latlon(basis, u, v, nz)
                mu = nz
                mu0 = u * lx + v * ly + nz * lz
                # subtle relief shading: tilt the normal along the local sun azimuth
                rel = _bil1(relief, lat, lon)
                mu0s = mu0 + 0.06 * rel * (1.0 - abs(mu0))
                m_v = _airmass(mu)
                cl = _bil1(clouds, lat, lon)
                lit = mu0 > -0.12
                for k in range(3):
                    tau = tau_r[k] + tau_a[k]
                    t_view = math.exp(-tau * m_v)
                    rad = 0.0
                    if lit:
                        m_s = _airmass(mu0)
                        t_sun = math.exp(-tau * m_s) if mu0 > 0.0 else math.exp(-tau * 38.0) * math.exp(mu0 / 0.02)
                        # cloud shadow: clouds between the ground and the Sun, shifted sunwards
                        shadow = 0.0
                        if mu0 > 0.0:
                            s = cloud_shift * math.sqrt(max(1.0 - mu0 * mu0, 0.0)) / max(mu0, 0.05)
                            # sunward direction on the surface: projection of L onto the tangent plane
                            tx = lx - mu0 * u
                            ty = ly - mu0 * v
                            tz = lz - mu0 * nz
                            tn = math.sqrt(tx * tx + ty * ty + tz * tz)
                            if tn > 1e-9:
                                qx = u + s * tx / tn
                                qy = v + s * ty / tn
                                qz = nz + s * tz / tn
                                qn = math.sqrt(qx * qx + qy * qy + qz * qz)
                                la2, lo2 = _latlon(basis, qx / qn, qy / qn, qz / qn)
                                shadow = _bil1(clouds, la2, lo2)
                        e0 = max(mu0s, 0.0) * t_sun
                        wat = _bil1(water, lat, lon)
                        ground = _bil3(albedo, lat, lon, k) * e0 * (1.0 - 0.75 * shadow)
                        # sun glint on open water (GGX, Schlick Fresnel, Smith G approx)
                        glint = 0.0
                        if wat > 0.0 and mu0 > 0.0:
                            nh = max(u * hx + v * hy + nz * hz, 0.0)
                            dd = nh * nh * (a2 - 1.0) + 1.0
                            dist = a2 / (math.pi * dd * dd)
                            vh = max(hz, 0.0)
                            fres = 0.02 + 0.98 * (1.0 - vh) ** 5
                            k_g = rough * 0.5
                            geo = (mu / (mu * (1 - k_g) + k_g)) * (mu0 / (mu0 * (1 - k_g) + k_g))
                            glint = wat * dist * fres * geo / (4.0 * max(mu, 1e-3)) * t_sun * (1.0 - shadow)
                        surface = (ground + glint * math.pi) * t_view
                        cloud = cloud_alb[k] * e0 * (0.85 + 0.25 * max(cos_scat, 0.0)) * math.exp(-0.4 * tau * m_v)
                        rad = surface * (1.0 - cl) + cloud * cl
                        # air: single-scattered sunlight along the line of sight
                        mus = max(mu0, 0.0) + 0.02
                        att = 1.0 - math.exp(-tau * (m_v + _airmass(mus)))
                        sca = (tau_r[k] * p_ray + tau_a[k] * p_mie) / tau
                        twilight = 1.0 if mu0 > 0.0 else math.exp(mu0 / 0.035)
                        rad += 0.25 * sca * mus / (mus + mu) * att * twilight * t_sun ** 0.3
                    # city lights where the Sun has set, seen through clouds and air
                    night = min(max((-mu0 + 0.02) / 0.14, 0.0), 1.0)
                    if night > 0.0:
                        rad += lights_gain * _bil3(lights, lat, lon, k) * night * (1.0 - 0.7 * cl) * t_view
                    out[r, c, k] = rad
            elif d2 < (1.0 + shell) * (1.0 + shell):
                # The air shell beyond the limb, at tangent height z (0..1 of the drawn shell).
                d = math.sqrt(d2)
                z = (d - 1.0) / shell
                tx, ty = u / d, v / d
                sun_up = tx * lx + ty * ly          # sine of the Sun's elevation at the limb point
                # Below the night-side limb the Earth's shadow reaches up to R (1 / cos(depression) - 1).
                dep = math.asin(min(max(-sun_up, 0.0), 1.0))
                h_shadow = shadow_scale * (1.0 / max(math.cos(dep), 1e-3) - 1.0)
                lit = min(max((z - h_shadow) / 0.12 + 0.5, 0.0), 1.0)
                dens = math.exp(-z * 4.0)
                graze = 38.0 * math.exp(-max(sun_up, 0.0) / 0.12)   # sunlight crossing the limb sideways
                for k in range(3):
                    tau = tau_r[k] + tau_a[k]
                    tau_t = tau * 40.0 * dens          # along our line of sight, ~sqrt(2 pi R / H)
                    sca = (tau_r[k] * p_ray + tau_a[k] * p_mie) / tau
                    t_in = math.exp(-tau * graze * dens)
                    rad = shell_gain * back * sca * (1.0 - math.exp(-tau_t)) * lit * t_in
                    # With the Sun right behind the Earth, sunlight refracted through the lower air
                    # reaches us directly: the red ring of all the world's sunsets at once.
                    rad += ring * math.exp(-tau * 76.0 * dens) * math.exp(-((z - 0.28) / 0.22) ** 2)
                    out[r, c, k] = rad


EARTH_GLOW = (
    (0.025, "gauss", 0.25),
    (0.015, "lorentz2", 0.9),
)


def _tone(rgb):
    return cel._tone_moon(rgb)


def render_earth(lat_deg, lon_deg, alpha_deg, side, size=512, ss=3, maps=None, map_width=2048):
    """One Earth texture (size, size, 4) uint8, additive-alpha encoded like the moon."""
    mp = maps if maps is not None else earth_maps(map_width)
    radius_tan = math.tan(math.radians(EARTH_DIAMETER_DEG / 2.0))
    shell = ATMOSPHERE_KM * SHELL_EXAG / R_EARTH_KM
    box = cel._disc_box(size, cel.MOON_HALF_TAN, radius_tan * (1 + shell), margin=1.04)
    x, y = cel._tan_grid(size, cel.MOON_HALF_TAN, ss, box)
    us = np.ascontiguousarray(x[0] / radius_tan)
    vs = np.ascontiguousarray(y[:, 0] / radius_tan)
    a = math.radians(alpha_deg)
    lx, ly, lz = side * math.sin(a), 0.0, math.cos(a)
    out = np.zeros((len(vs), len(us), 3))
    _earth_kernel(us, vs, view_basis(lat_deg, lon_deg), lx, ly, lz, mp["albedo"], mp["water"], mp["relief"],
                  mp["clouds"], mp["lights"], TAU_RAYLEIGH, TAU_AEROSOL, AEROSOL_G, OCEAN_ROUGHNESS,
                  CLOUD_ALBEDO, LIGHTS_GAIN, shell, CLOUD_KM / R_EARTH_KM, R_EARTH_KM / ATMOSPHERE_KM,
                  SHELL_GAIN, out)
    out = cel._bin(out, ss)
    hdr = np.zeros((size, size, 3))
    r0, r1, c0, c1 = box
    hdr[r0:r1, c0:c1] = out * EXPOSURE
    kern = cel._glare_kernel(size, cel.MOON_HALF_TAN, EARTH_GLOW, taper=(4.0, 9.0))
    total = sum(wt for wt, _, _ in EARTH_GLOW)
    hdr = hdr * (1.0 - total) + cel._fft_convolve(hdr, kern)
    srgb = bh.srgb_encode(_tone(np.maximum(hdr, 0.0)))
    return cel.encode_additive(srgb, dither_seed=int(abs(lon_deg) * 10 + alpha_deg))


def render_earth_phase(name, size=512, ss=3, maps=None, map_width=2048):
    alpha_deg, side = cel.PHASE_GEOMETRY[name]
    lat, lon = VIEWS[name]
    return render_earth(lat, lon, alpha_deg, side, size, ss, maps, map_width)


def make_earth_phases(size=512, ss=3, map_width=2048):
    """All eight phases: {name: (size, size, 4) uint8}, keyed like celestial.make_moon_phases
    (the 1.21.11+ texture names textures/environment/celestial/moon/<name>.png)."""
    maps = earth_maps(map_width)
    return {name: render_earth_phase(name, size, ss, maps) for name in cel.PHASES}


def pack_textures(moon_size=512):
    """Every Earth texture the pack ships: {pack-relative path: RGBA uint8}."""
    phases = make_earth_phases(moon_size)
    files = {"textures/environment/moon_phases.png": cel.moon_phase_sheet(phases)}   # <= 1.21.10
    for name, img in phases.items():
        files[f"textures/environment/celestial/moon/{name}.png"] = img                 # 1.21.11+
    return files


def preview_sheet(phases, path, size=None):
    """All eight phases on a starless night background, labelled, in Minecraft's cycle order."""
    from PIL import Image, ImageDraw
    import preview
    order = ["full_moon", "waning_gibbous", "third_quarter", "waning_crescent",
             "new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous"]
    labels = ["Full Earth", "Waning gibbous", "Last quarter", "Waning crescent",
              "New Earth", "Waxing crescent", "First quarter", "Waxing gibbous"]
    tiles = []
    for name, text in zip(order, labels):
        img = phases[name]
        s = img.shape[0]
        lo, hi = int(s * 0.31), int(s * 0.69)
        tile = cel.composite_additive(np.full(3, 4.0 / 255.0), img[lo:hi, lo:hi])
        tile = Image.fromarray((tile * 255).astype(np.uint8)).resize((300, 300), Image.LANCZOS)
        d = ImageDraw.Draw(tile)
        d.text((150, 284), text, fill=(200, 210, 230), font=preview.font(16), anchor="mm")
        tiles.append(np.asarray(tile))
    sheet = np.concatenate([np.concatenate(tiles[:4], 1), np.concatenate(tiles[4:], 1)], 0)
    Image.fromarray(sheet).save(path, optimize=True)
    return path


if __name__ == "__main__":
    import sys
    from pathlib import Path
    out = Path(__file__).resolve().parent.parent / "previews" / "earth_phases.png"
    print("wrote", preview_sheet(make_earth_phases(int(sys.argv[1]) if len(sys.argv) > 1 else 512), out))
