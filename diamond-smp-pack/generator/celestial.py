"""Photorealistic sun and moon textures for the vanilla Minecraft sky.

Everything here is computed from physics and procedural models; no imagery is
downloaded or shipped.

Geometry (vanilla)
------------------
The sun texture is drawn on a quad whose half-width is 0.3 of its distance
(tangent of the half-angle), i.e. the texture spans 33.4 degrees. The moon quad
has a half-angle tangent of 0.2 (22.6 degrees). Pixel ``(row, col)`` of a size
``S`` texture therefore sits at tangent-plane coordinates
``x = ((col + 0.5) / S * 2 - 1) * T`` (right) and ``y = -((row + 0.5) / S * 2 - 1) * T``
(up), with T = 0.3 or 0.2.

The game draws both additively (``SRC_ALPHA, ONE``). Every texture is encoded so
that ``rgb * alpha`` equals the intended additive sRGB colour, with
``alpha = max(r, g, b)`` (see :func:`encode_additive`); black is invisible.

Sun
---
* Disc 2.5 degrees across (the real sun is 0.53; vanilla's is ~8.5).
* Spectrally integrated photosphere: the disc-integrated spectrum is a 5772 K
  blackbody (the Sun's effective temperature), the specific intensity follows
  the wavelength-dependent quadratic limb-darkening law of Allen's
  Astrophysical Quantities (I(mu) = 1 - u2 (1 - mu) - v2 (1 - mu^2), u2 and v2
  per wavelength), so the limb is darker and redder, the centre a little bluer.
  Spectra are integrated against the CIE 1931 observer (``blackhole._cie_cmf``).
* Granulation (cellular temperature field), two sunspot groups (umbra ~4100 K,
  penumbra ~5350 K, on the solar sphere so they foreshorten near the limb) and
  faculae brightening towards the limb.
* Glare: the disc convolved with a glare PSF made of a narrow optical bloom, the
  theta^-3 / theta^-2 wide-angle scattering of the eye (Spencer et al. 1995) and
  the theta^-2 aerosol aureole, smoothly windowed so it is exactly zero well
  before the texture edge. Film-like per-channel response: the over-exposed core
  bleaches to white, the glare is warm white.

Moon
----
* Disc 4.2 degrees across (real 0.52), shown in the standard Earth view: lunar
  north up, Mare Crisium (lunar east) on the right, so the waxing moon is lit on
  the right exactly like the vanilla phase textures.
* Selenographic maps (equirectangular, near side) of albedo, colour index and
  height: the real near-side maria at their true positions (Procellarum,
  Imbrium, Serenitatis, Tranquillitatis, Crisium, Fecunditatis, Nectaris,
  Nubium, Humorum, Frigoris, ...), ~40 real named craters (Tycho, Copernicus,
  Kepler, Aristarchus, Plato, Clavius, Ptolemaeus, Theophilus, Grimaldi, ...),
  a power-law population of random craters (N(>D) ~ D^-2, far fewer on the
  young maria), basin mountain rings (Apennines, Alps, ...), and the bright ray
  systems of Tycho, Copernicus, Kepler, Aristarchus and smaller fresh craters.
* Shading: McEwen's lunar-Lambert photometric function (pure Lommel-Seeliger at
  opposition, so the full moon is flat and bright to the limb, more Lambertian
  at large phase), a Hapke shadow-hiding opposition surge, bump-mapped crater
  slopes and true cast shadows marched over the height map (soft, with the
  0.53 degree solar disc), so peaks beyond the terminator catch the light.
* Earthshine on the night side, scaled by the phase of the Earth seen from the
  Moon and tinted blue by the Earth's reflectance; a faint aureole glow.
* Colour: sunlight (5772 K) times a reddish lunar reflectance spectrum (B-V of
  the Moon is ~0.27 mag redder than the Sun), partially white balanced so it
  reads as a slightly warm grey.
"""

import math
from functools import lru_cache

import numpy as np
from numba import njit, prange

import blackhole as bh

# ---------------------------------------------------------------------------
# Vanilla geometry and phase conventions
# ---------------------------------------------------------------------------

SUN_HALF_TAN = 0.3      # sun quad: 30 units half-width at distance 100
MOON_HALF_TAN = 0.2     # moon quad: 20 units half-width at distance 100
SUN_DIAMETER_DEG = 2.5
MOON_DIAMETER_DEG = 4.2

# Order of the legacy moon_phases.png sheet (4 columns x 2 rows, row-major),
# which is also Minecraft's phase order (phase 0 = full moon on the first night).
PHASES = ("full_moon", "waning_gibbous", "third_quarter", "waning_crescent",
          "new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous")

# Sun-Moon-Earth phase angle (degrees) and the lit side of the texture
# (+1 = right, -1 = left), matching the vanilla textures: waxing phases are
# lit on the right, waning phases on the left. The crescents and gibbous
# phases sit a little closer to quarter than the even 45 degree spacing
# (illuminated fractions 0.21 / 0.79, vanilla's are ~0.22 / ~0.66) so the
# crescent is not a hair-thin sliver at game resolution.
PHASE_GEOMETRY = {
    "full_moon": (3.0, 1),
    "waning_gibbous": (55.0, -1),
    "third_quarter": (90.0, -1),
    "waning_crescent": (125.0, -1),
    "new_moon": (180.0, 1),
    "waxing_crescent": (125.0, 1),
    "first_quarter": (90.0, 1),
    "waxing_gibbous": (55.0, 1),
}

R_MOON_KM = 1737.4
T_SUN = 5772.0


# ---------------------------------------------------------------------------
# Texture helpers
# ---------------------------------------------------------------------------


def encode_additive(srgb, dither_seed=None):
    """Additive sRGB colour (..., 3) in [0, 1] -> RGBA uint8.

    alpha = max(r, g, b) and rgb = colour / alpha, so that the game's
    ``SRC_ALPHA, ONE`` blend adds exactly ``rgb * alpha`` = colour. Fully black
    pixels get alpha 0 (and rgb 0). Optional +-0.5 LSB dither on the colour
    hides 8-bit banding in smooth glows."""
    c = np.clip(np.asarray(srgb, dtype=np.float64), 0.0, 1.0)
    if dither_seed is not None:
        noise = np.random.default_rng(dither_seed).uniform(-0.5, 0.5, c.shape[:-1])[..., None] / 255.0
        c = np.clip(c + noise * (c.max(-1, keepdims=True) > 0), 0.0, 1.0)
    a8 = np.clip(np.round(c.max(-1) * 255.0), 0, 255)
    af = (a8 / 255.0)[..., None]
    rgb = np.where(af > 0, c / np.maximum(af, 1e-12), 0.0)
    rgb8 = np.clip(np.round(rgb * 255.0), 0, 255)
    out = np.concatenate([rgb8, a8[..., None]], -1).astype(np.uint8)
    return out


def decode_additive(rgba):
    """RGBA uint8 -> the additive sRGB colour the game adds (rgb * alpha), float in [0, 1]."""
    rgba = np.asarray(rgba, dtype=np.float64) / 255.0
    return rgba[..., :3] * rgba[..., 3:4]


def composite_additive(background_srgb, rgba):
    """Preview helper: add a texture onto an sRGB background like the game does."""
    bg = np.asarray(background_srgb, dtype=np.float64)
    if bg.ndim == 1:
        bg = np.broadcast_to(bg, rgba.shape[:2] + (3,))
    return np.clip(bg + decode_additive(rgba), 0.0, 1.0)


def _tan_grid(size, half_tan, ss=1, box=None):
    """Tangent-plane coordinates (x right, y up) of (sub)pixel centres.

    box = (r0, r1, c0, c1) restricts to that pixel window; each pixel is split
    into ss x ss sub-pixels. Returns x, y of shape (rows*ss, cols*ss)."""
    r0, r1, c0, c1 = box if box is not None else (0, size, 0, size)
    cols = (np.arange(c0 * ss, c1 * ss) + 0.5) / (size * ss) * 2.0 - 1.0
    rows = (np.arange(r0 * ss, r1 * ss) + 0.5) / (size * ss) * 2.0 - 1.0
    x, y = np.meshgrid(cols * half_tan, -rows * half_tan)
    return x, y


def _bin(img, ss):
    if ss == 1:
        return img
    h, w = img.shape[0] // ss, img.shape[1] // ss
    return img.reshape(h, ss, w, ss, *img.shape[2:]).mean(axis=(1, 3))


def _disc_box(size, half_tan, radius_tan, margin=1.06):
    """Pixel window (r0, r1, c0, c1) that contains a centred disc."""
    rpx = radius_tan * margin / half_tan * size / 2.0
    lo = max(int(math.floor(size / 2.0 - rpx)) - 1, 0)
    hi = min(int(math.ceil(size / 2.0 + rpx)) + 1, size)
    return lo, hi, lo, hi


def _fft_convolve(img, kern):
    """Linear (non-circular) convolution of img (H, W, C) with a centred kernel (h, w)."""
    h, w = img.shape[:2]
    kh, kw = kern.shape
    ph, pw = h + kh, w + kw
    fi = np.fft.rfft2(img, s=(ph, pw), axes=(0, 1))
    fk = np.fft.rfft2(kern, s=(ph, pw))
    out = np.fft.irfft2(fi * fk[..., None], s=(ph, pw), axes=(0, 1))
    oy, ox = kh // 2, kw // 2
    return out[oy:oy + h, ox:ox + w]


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _film(x):
    """Per-channel film response: linear at the toe, highlights bleach to white."""
    return 1.0 - np.exp(-np.maximum(x, 0.0))


# ---------------------------------------------------------------------------
# Spectral colour
# ---------------------------------------------------------------------------

_LAM = np.arange(380.0, 781.0, 5.0)          # nm
_CMF = bh._cie_cmf(_LAM)                      # (n, 3) CIE 1931 x, y, z


def _planck(lam_nm, temp):
    lam = np.asarray(lam_nm, dtype=np.float64) * 1e-9
    t = np.asarray(temp, dtype=np.float64)[..., None]
    return 1.0 / (lam ** 5 * np.expm1(1.4387769e-2 / (lam * t)))


def _spec_to_rgb(spec):
    """Spectra (..., n) on _LAM -> linear sRGB (unnormalised)."""
    return (spec @ _CMF) @ bh.XYZ_TO_SRGB.T


_SUN_RGB = _spec_to_rgb(_planck(_LAM, T_SUN))
_SUN_NORM = 1.0 / float(_SUN_RGB @ bh.LUMA)


def atmosphere_transmission(lam_nm, airmass, aerosol_tau=0.05):
    """Direct-beam transmission of a clear atmosphere: Rayleigh (Hansen & Travis 1974)
    plus a clean continental aerosol (Angstrom exponent 1.3)."""
    lam = np.asarray(lam_nm, dtype=np.float64) / 1000.0
    tau_r = 0.008569 * lam ** -4 * (1.0 + 0.0113 * lam ** -2 + 0.00013 * lam ** -4)
    tau_a = aerosol_tau * (lam / 0.55) ** -1.3
    return np.exp(-airmass * (tau_r + tau_a))


def _bb_ratio(temp, t_ref=T_SUN):
    """Per-channel radiance ratio of a blackbody at `temp` to one at `t_ref` (linear sRGB)."""
    temp = np.asarray(temp, dtype=np.float64)
    a = _spec_to_rgb(_planck(_LAM, temp))
    b = _spec_to_rgb(_planck(_LAM, t_ref))
    return a / b


# ---------------------------------------------------------------------------
# Numba noise helpers (on the unit sphere / in 3D)
# ---------------------------------------------------------------------------


@njit(parallel=True, cache=False)
def _fbm_points(px, py, pz, freq, octaves, seed, out):
    for i in prange(px.shape[0]):
        out[i] = bh.fbm3(px[i] * freq, py[i] * freq, pz[i] * freq, octaves, seed)


def fbm(p, freq, octaves, seed):
    """Fractal value noise in [0, 1] at points p (..., 3)."""
    shape = p.shape[:-1]
    q = np.ascontiguousarray(p.reshape(-1, 3), dtype=np.float64)
    out = np.empty(q.shape[0])
    _fbm_points(q[:, 0].copy(), q[:, 1].copy(), q[:, 2].copy(), float(freq), int(octaves), int(seed), out)
    return out.reshape(shape)


@njit(inline="always")
def _worley3(x, y, z, seed):
    """Distances to the nearest and second nearest feature point (one per unit cell)."""
    ix, iy, iz = int(math.floor(x)), int(math.floor(y)), int(math.floor(z))
    f1, f2 = 9.0, 9.0
    for dz in range(-1, 2):
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                cx, cy, cz = ix + dx, iy + dy, iz + dz
                fx = cx + bh._hash3(cx, cy, cz, seed)
                fy = cy + bh._hash3(cx, cy, cz, seed + 1)
                fz = cz + bh._hash3(cx, cy, cz, seed + 2)
                d = math.sqrt((x - fx) ** 2 + (y - fy) ** 2 + (z - fz) ** 2)
                if d < f1:
                    f2 = f1
                    f1 = d
                elif d < f2:
                    f2 = d
    return f1, f2


@njit(parallel=True)
def _granulation_points(px, py, pz, freq, seed, out):
    for i in prange(px.shape[0]):
        x, y, z = px[i] * freq, py[i] * freq, pz[i] * freq
        # domain warp so the cells are irregular polygons
        wx = (bh.value_noise3(x * 0.7, y * 0.7, z * 0.7, seed + 5) - 0.5) * 0.6
        wy = (bh.value_noise3(x * 0.7 + 3.1, y * 0.7, z * 0.7, seed + 6) - 0.5) * 0.6
        f1, f2 = _worley3(x + wx, y + wy, z, seed)
        lane = min((f2 - f1) / 0.22, 1.0)          # 0 in the dark intergranular lanes
        centre = math.exp(-f1 * f1 / 0.18)         # hot upflow at the granule centre
        out[i] = 0.55 * lane + 0.45 * centre


# ---------------------------------------------------------------------------
# The Sun
# ---------------------------------------------------------------------------

# Allen's Astrophysical Quantities (Cox 2000), solar limb darkening
# I(mu)/I(1) = 1 - u2 (1 - mu) - v2 (1 - mu^2).
_LD_TABLE = np.array([
    # lambda nm, u2, v2
    (320.0, 0.88, 0.03),
    (350.0, 0.98, -0.10),
    (370.0, 1.03, -0.16),
    (380.0, 0.92, -0.05),
    (400.0, 0.91, -0.05),
    (450.0, 0.99, -0.17),
    (500.0, 0.97, -0.22),
    (550.0, 0.93, -0.23),
    (600.0, 0.88, -0.23),
    (800.0, 0.73, -0.22),
    (1000.0, 0.64, -0.20),
])


def limb_darkening_coeffs(lam_nm):
    """(u2, v2) of the solar limb-darkening law at the given wavelengths."""
    lam = np.asarray(lam_nm, dtype=np.float64)
    return (np.interp(lam, _LD_TABLE[:, 0], _LD_TABLE[:, 1]),
            np.interp(lam, _LD_TABLE[:, 0], _LD_TABLE[:, 2]))


def sun_limb_lut(n=256, airmass=0.0):
    """Linear sRGB specific intensity of the photosphere vs mu = cos(heliocentric angle).

    The disc-integrated flux is a 5772 K blackbody (optionally seen through
    `airmass` of clear atmosphere); the result is normalised so the disc centre
    has luminance 1. Returns (mu (n,), rgb (n, 3))."""
    u2, v2 = limb_darkening_coeffs(_LAM)
    flux = _planck(_LAM, T_SUN) * atmosphere_transmission(_LAM, airmass)
    centre = flux / (1.0 - u2 / 3.0 - v2 / 2.0)   # Eddington flux integral of the law
    mu = np.linspace(0.0, 1.0, n)
    spec = centre[None, :] * (1.0 - u2[None, :] * (1.0 - mu[:, None]) - v2[None, :] * (1.0 - mu[:, None] ** 2))
    rgb = _spec_to_rgb(spec)
    return mu, rgb / float(rgb[-1] @ bh.LUMA)


# (lat, lon) in degrees on the visible solar hemisphere (lon 0 = central meridian,
# positive towards the right of the texture), radii in heliographic degrees.
SUNSPOTS = (
    # a large bipolar active region in the northern hemisphere
    (14.0, -26.0, 1.70, 3.60),
    (15.5, -18.0, 1.10, 2.50),
    (12.8, -14.0, 0.55, 1.40),
    (16.5, -22.0, 0.40, 1.10),
    (12.0, -10.0, 0.35, 0.90),
    # a smaller group in the south, closer to the limb
    (-9.0, 40.0, 1.10, 2.40),
    (-10.5, 46.0, 0.50, 1.20),
)


def _sun_surface(px, py, pz, seed):
    """Temperature (K) of the photosphere at points on the visible solar sphere.

    x = right, y = up, z = towards the observer; |p| = 1."""
    p = np.stack([px, py, pz], -1)
    # Granulation: ~4 cells per final pixel would be invisible, so the cells are
    # drawn at the scale of supergranulation-sized mottling seen at this resolution.
    flat = np.ascontiguousarray(p.reshape(-1, 3))
    gran = np.empty(flat.shape[0])
    _granulation_points(flat[:, 0].copy(), flat[:, 1].copy(), flat[:, 2].copy(), 34.0, seed, gran)
    gran = gran.reshape(px.shape)
    mottle = fbm(p, 9.0, 4, seed + 11)
    temp = T_SUN * (1.0 + 0.020 * (gran - 0.5) + 0.010 * (mottle - 0.5))

    # Solar rotation axis tilted a little towards the observer (B0 ~ 5 deg) and
    # rotated on the sky (P ~ 12 deg) so the spots do not sit on a perfect row.
    b0, p0 = math.radians(5.0), math.radians(12.0)
    spot = np.zeros(px.shape)          # 1 in umbrae
    pen = np.zeros(px.shape)           # 1 in penumbrae
    fac = np.zeros(px.shape)           # facular field strength
    rough = fbm(p, 60.0, 3, seed + 3)
    for lat, lon, r_u, r_p in SUNSPOTS:
        la, lo = math.radians(lat), math.radians(lon)
        c = np.array([math.cos(la) * math.sin(lo), math.sin(la), math.cos(la) * math.cos(lo)])
        # tilt by B0 about x, then roll by P about z
        c = np.array([c[0], c[1] * math.cos(b0) + c[2] * math.sin(b0), -c[1] * math.sin(b0) + c[2] * math.cos(b0)])
        c = np.array([c[0] * math.cos(p0) - c[1] * math.sin(p0), c[0] * math.sin(p0) + c[1] * math.cos(p0), c[2]])
        d = np.degrees(np.arccos(np.clip(p @ c, -1.0, 1.0)))
        d = d * (1.0 + 0.35 * (rough - 0.5))   # ragged penumbral edges
        spot = np.maximum(spot, _smoothstep(r_u * 1.15, r_u * 0.8, d))
        pen = np.maximum(pen, _smoothstep(r_p * 1.1, r_p * 0.85, d))
        fac = np.maximum(fac, np.exp(-(d / (r_p * 4.5)) ** 2))
    plage = fbm(p, 22.0, 4, seed + 7)
    mu = np.clip(pz, 0.0, 1.0)
    temp = temp * (1.0 + 0.045 * fac * np.clip(plage - 0.35, 0, 1) * (1.0 - mu) ** 1.5)
    temp = np.where(pen > 0, temp * (1.0 - pen) + 5350.0 * pen, temp)
    temp = temp * (1.0 - spot) + 4100.0 * spot
    return temp


def _glare_kernel(size, half_tan, comps, taper):
    """Radially symmetric glare PSF on the texture grid (angles in degrees).

    comps: list of (weight, kind, scale). Each component is normalised to unit
    volume (over the texture grid) and then weighted. taper = (start, end) deg."""
    n = size + 1 if size % 2 == 0 else size
    t = (np.arange(n) - n // 2) * (2.0 * half_tan / size)
    x, y = np.meshgrid(t, t)
    theta = np.degrees(np.arctan(np.hypot(x, y)))
    win = 1.0 - _smoothstep(taper[0], taper[1], theta)
    px_deg = math.degrees(2.0 * half_tan / size)
    th = np.maximum(theta, 0.35 * px_deg)
    kern = np.zeros_like(theta)
    for weight, kind, s in comps:
        if kind == "gauss":
            k = np.exp(-0.5 * (theta / s) ** 2)
        elif kind == "lorentz2":   # ~theta^-2 beyond s
            k = 1.0 / (th * th + s * s)
        elif kind == "power3":     # ~theta^-3 beyond s
            k = 1.0 / (th * th + s * s) ** 1.5
        else:
            raise ValueError(kind)
        k = k * win
        kern += weight * k / k.sum()
    return kern


SUN_GLARE = (
    # (energy fraction, shape, scale deg)
    (0.090, "gauss", 0.30),      # optical bloom hugging the limb
    (0.070, "power3", 0.6),      # eye / lens wide-angle scatter (Spencer et al. theta^-3 term)
    (0.120, "lorentz2", 1.4),    # eye scatter theta^-2 term + forward-scattering aerosol aureole
)


def make_sun(size=512, ss=6, exposure=4.0, airmass=1.0, seed=5772):
    """Vanilla sun texture (size, size, 4) uint8, additive-alpha encoded.

    The disc is SUN_DIAMETER_DEG across; ss is the supersampling of the disc.
    airmass: clear atmosphere the sun is seen through (1 = overhead)."""
    radius_tan = math.tan(math.radians(SUN_DIAMETER_DEG / 2.0))
    box = _disc_box(size, SUN_HALF_TAN, radius_tan)
    x, y = _tan_grid(size, SUN_HALF_TAN, ss, box)
    # Exact projection of a sphere seen from afar: rho = sin(theta) / sin(R).
    r_t = np.hypot(x, y)
    theta = np.arctan(r_t)
    rho = np.sin(theta) / math.sin(math.atan(radius_tan))
    inside = rho < 1.0
    scale = np.where(r_t > 0, rho / np.maximum(r_t, 1e-12), 0.0)
    dx, dy = x * scale, y * scale
    mu = np.sqrt(np.clip(1.0 - rho * rho, 0.0, 1.0))

    mus, lut = sun_limb_lut(airmass=airmass)
    ld = np.stack([np.interp(mu, mus, lut[:, c]) for c in range(3)], -1)
    temp = _sun_surface(dx, dy, mu, seed)
    ratio = _bb_ratio(temp.ravel()).reshape(temp.shape + (3,))
    disc = ld * ratio * inside[..., None]

    hdr = np.zeros((size, size, 3))
    r0, r1, c0, c1 = box
    hdr[r0:r1, c0:c1] = _bin(disc, ss)

    kern = _glare_kernel(size, SUN_HALF_TAN, SUN_GLARE, taper=(5.5, 14.0))
    total = sum(w for w, _, _ in SUN_GLARE)
    hdr = hdr * (1.0 - total) + _fft_convolve(hdr, kern)
    srgb = bh.srgb_encode(_film(hdr * exposure))
    return encode_additive(srgb, dither_seed=seed)


# ---------------------------------------------------------------------------
# The Moon: selenographic data
# ---------------------------------------------------------------------------
# Frame: x = lunar east (towards Mare Crisium, the right of the texture),
# y = lunar north (up), z = towards the Earth (the viewer). A point at
# selenographic (lat, lon) is (cos lat sin lon, sin lat, cos lat cos lon).

# Maria: (lat, lon, a_km E-W semi-axis, b_km N-S semi-axis, rotation deg,
#         normal albedo, colour index (-1 blue high-Ti ... +1 red), floor depth km)
# Large irregular maria are unions of several blobs.
MARIA = (
    # Oceanus Procellarum (+ Sinus Roris)
    (44.0, -54.0, 300, 230, 20, 0.078, -0.25, 1.2),
    (54.0, -42.0, 260, 120, 10, 0.084, 0.0, 1.0),
    (30.0, -58.0, 330, 330, 0, 0.074, -0.45, 1.3),
    (16.0, -52.0, 380, 360, 0, 0.072, -0.55, 1.4),
    (3.0, -50.0, 360, 330, 15, 0.075, -0.35, 1.4),
    (-6.0, -42.0, 300, 260, -20, 0.078, -0.2, 1.3),
    (-3.0, -61.0, 230, 330, 0, 0.074, -0.4, 1.3),
    (20.0, -38.0, 260, 220, 0, 0.078, -0.3, 1.3),
    (-14.0, -34.0, 200, 150, 30, 0.082, -0.1, 1.2),
    # Mare Imbrium (Sinus Iridum on its north-western shore)
    (34.0, -16.0, 560, 540, 0, 0.078, -0.15, 2.5),
    (40.0, -26.0, 300, 260, 0, 0.076, -0.3, 2.3),
    (44.5, -31.5, 125, 115, 0, 0.083, -0.1, 2.0),
    # Mare Frigoris (a long thin band in the far north)
    (57.0, -38.0, 230, 110, 8, 0.092, 0.25, 0.8),
    (57.5, -12.0, 250, 105, -4, 0.093, 0.3, 0.8),
    (56.0, 10.0, 240, 100, 0, 0.094, 0.35, 0.8),
    (56.5, 30.0, 200, 95, -8, 0.095, 0.35, 0.8),
    (58.0, 45.0, 130, 80, 0, 0.096, 0.3, 0.6),
    # Mare Serenitatis, Lacus Somniorum, Lacus Mortis
    (28.0, 17.5, 345, 340, 0, 0.088, 0.15, 2.2),
    (37.0, 29.5, 190, 140, 0, 0.094, 0.25, 1.0),
    (45.0, 27.0, 80, 75, 0, 0.096, 0.2, 0.8),
    # Mare Tranquillitatis
    (8.5, 30.0, 330, 270, 25, 0.068, -0.85, 1.8),
    (15.0, 36.5, 210, 190, 0, 0.069, -0.8, 1.6),
    (2.0, 24.0, 210, 160, 0, 0.071, -0.7, 1.5),
    # Mare Crisium (isolated oval near the east limb)
    (17.0, 59.0, 285, 225, 0, 0.078, -0.25, 2.8),
    # Mare Fecunditatis, Undarum, Spumans
    (-7.5, 51.5, 230, 330, 10, 0.084, 0.0, 1.4),
    (-2.0, 46.0, 150, 150, 0, 0.082, -0.1, 1.2),
    (6.8, 68.4, 110, 90, 0, 0.086, 0.0, 1.0),
    (1.1, 65.1, 70, 60, 0, 0.086, 0.0, 1.0),
    # Mare Nectaris
    (-15.2, 35.0, 175, 170, 0, 0.083, 0.1, 2.0),
    # Mare Vaporum, Sinus Aestuum, Sinus Medii
    (13.3, 3.6, 135, 115, 0, 0.077, 0.1, 1.2),
    (11.5, -8.5, 150, 110, 0, 0.074, -0.1, 1.2),
    (2.4, 1.7, 115, 95, 0, 0.090, 0.2, 1.0),
    # Mare Insularum, Mare Cognitum, Mare Nubium, Mare Humorum
    (7.5, -30.5, 260, 210, 0, 0.080, -0.15, 1.2),
    (-10.0, -23.0, 200, 170, 0, 0.083, 0.0, 1.2),
    (-20.5, -16.5, 360, 300, 0, 0.083, 0.05, 1.6),
    (-26.0, -9.0, 160, 120, 0, 0.086, 0.1, 1.2),
    (-24.4, -38.6, 200, 195, 0, 0.074, -0.2, 2.4),
    # Near-limb maria
    (13.3, 86.1, 210, 160, 0, 0.088, 0.0, 1.0),     # Marginis
    (1.3, 87.5, 190, 180, 0, 0.086, 0.0, 1.0),      # Smythii
    (-38.9, 88.0, 300, 220, 0, 0.098, 0.2, 0.8),    # Australe (patchy)
    (56.8, 81.5, 140, 130, 0, 0.088, 0.1, 1.0),     # Humboldtianum
    (-19.4, -92.8, 200, 200, 0, 0.085, 0.0, 1.0),   # Orientale (only its rim shows)
    # Dark, lava-flooded crater floors
    (51.6, -9.4, 44, 44, 0, 0.066, -0.1, 0.0),      # Plato
    (-5.2, -68.6, 85, 85, 0, 0.060, -0.2, 0.0),     # Grimaldi
    (-3.3, -74.6, 50, 50, 0, 0.068, -0.1, 0.0),     # Riccioli
    (53.9, 57.0, 52, 52, 0, 0.074, 0.0, 0.0),       # Endymion
    (29.7, -4.0, 38, 38, 0, 0.082, 0.0, 0.0),       # Archimedes
    (-44.3, -54.6, 45, 40, 0, 0.088, 0.1, 0.0),     # Schickard (dark patch)
    (-49.7, -60.4, 40, 40, 0, 0.090, 0.1, 0.0),     # Wargentin
)

# Named craters: (lat, lon, diameter km, freshness 0..1, floor flooded 0..1)
CRATERS = (
    (-43.31, -11.36, 85, 1.00, 0.0),    # Tycho
    (9.62, -20.08, 93, 0.95, 0.0),      # Copernicus
    (8.12, -38.01, 32, 0.95, 0.0),      # Kepler
    (23.73, -47.49, 40, 1.00, 0.0),     # Aristarchus
    (16.1, 46.8, 28, 0.90, 0.0),        # Proclus
    (73.4, -10.1, 51, 0.85, 0.0),       # Anaxagoras
    (-24.5, -63.7, 19, 0.90, 0.0),      # Byrgius A
    (8.1, -77.6, 43, 0.90, 0.0),        # Olbers A (Glushko)
    (-33.5, 59.0, 11, 0.90, 0.0),       # Furnerius A
    (-31.8, 51.6, 8, 0.90, 0.0),        # Stevinus A
    (61.8, 50.3, 31, 0.85, 0.0),        # Thales
    (16.3, 16.0, 27, 0.80, 0.0),        # Menelaus
    (2.8, 17.3, 18, 0.80, 0.0),         # Dionysius
    (-0.4, 32.7, 4, 0.80, 0.0),         # Censorinus
    (-1.9, 47.6, 11, 0.85, 0.0),        # Messier
    (-2.0, 47.0, 13, 0.85, 0.0),        # Messier A
    (14.5, -11.3, 58, 0.45, 0.0),       # Eratosthenes
    (-8.9, 61.1, 132, 0.45, 0.0),       # Langrenus
    (-11.4, 26.4, 100, 0.40, 0.0),      # Theophilus
    (-13.2, 24.0, 98, 0.10, 0.0),       # Cyrillus
    (-18.1, 23.4, 100, 0.05, 0.0),      # Catharina
    (-20.7, -22.2, 61, 0.35, 0.0),      # Bullialdus
    (-25.1, 60.4, 177, 0.20, 0.0),      # Petavius
    (-58.4, -14.4, 225, 0.05, 0.3),     # Clavius
    (-50.0, -6.2, 194, 0.02, 0.0),      # Maginus
    (-49.6, -21.7, 145, 0.05, 0.0),     # Longomontanus
    (-9.3, -1.9, 153, 0.02, 0.7),       # Ptolemaeus
    (-13.4, -3.2, 108, 0.05, 0.4),      # Alphonsus
    (-18.2, -1.9, 96, 0.20, 0.2),       # Arzachel
    (-11.2, 4.0, 136, 0.05, 0.2),       # Albategnius
    (-5.1, 5.2, 138, 0.01, 0.3),        # Hipparchus
    (-33.1, -5.2, 234, 0.01, 0.2),      # Deslandres
    (-33.1, 1.0, 128, 0.05, 0.3),       # Walther
    (-41.1, 6.0, 126, 0.03, 0.3),       # Stoefler
    (-42.0, 14.0, 114, 0.08, 0.0),      # Maurolycus
    (-45.4, 40.3, 199, 0.02, 0.0),      # Janssen
    (-29.9, -13.5, 106, 0.03, 0.6),     # Pitatus
    (-17.6, -40.1, 110, 0.10, 0.5),     # Gassendi
    (-44.3, -54.6, 206, 0.02, 0.4),     # Schickard
    (-49.7, -60.4, 84, 0.02, 0.9),      # Wargentin
    (-5.2, -68.6, 172, 0.02, 0.8),      # Grimaldi
    (-3.3, -74.6, 139, 0.02, 0.5),      # Riccioli
    (51.6, -9.4, 101, 0.10, 1.0),       # Plato
    (29.7, -4.0, 82, 0.15, 1.0),        # Archimedes
    (50.2, 17.4, 88, 0.35, 0.0),        # Aristoteles
    (44.3, 16.3, 67, 0.35, 0.0),        # Eudoxus
    (31.8, 29.9, 95, 0.05, 0.8),        # Posidonius
    (46.7, 44.4, 87, 0.15, 0.3),        # Atlas
    (46.8, 39.1, 69, 0.20, 0.2),        # Hercules
    (53.9, 57.0, 125, 0.05, 1.0),       # Endymion
    (27.7, 56.0, 125, 0.05, 0.5),       # Cleomedes
    (-36.0, 60.6, 135, 0.03, 0.0),      # Furnerius
    (-6.1, -17.0, 101, 0.01, 0.5),      # Fra Mauro
    (-66.5, -69.1, 287, 0.01, 0.0),     # Bailly
    (23.2, -49.7, 34, 0.10, 0.9),       # Herodotus
    (-3.0, -15.0, 59, 0.10, 0.0),       # Lalande-ish (fills the central highlands)
    (21.8, 17.9, 15, 0.70, 0.0),        # Bessel
    (35.0, -2.5, 50, 0.40, 0.0),        # Aristillus (approx.)
    (-28.0, -9.0, 30, 0.6, 0.0),        # Birt-ish bright crater in Nubium
)

# Ray systems: (lat, lon, crater diameter km, number of rays, mean ray length km,
#               brightness, (avoid azimuth deg, half-width deg) or None, seed)
RAYS = (
    (-43.31, -11.36, 85, 46, 650, 1.00, (270.0, 55.0), 11),   # Tycho
    (9.62, -20.08, 93, 70, 330, 0.85, None, 12),              # Copernicus
    (8.12, -38.01, 32, 40, 230, 0.80, None, 13),              # Kepler
    (23.73, -47.49, 40, 30, 200, 0.85, None, 14),             # Aristarchus
    (16.1, 46.8, 28, 16, 260, 0.70, (225.0, 50.0), 15),       # Proclus
    (73.4, -10.1, 51, 24, 300, 0.60, None, 16),               # Anaxagoras
    (-24.5, -63.7, 19, 16, 220, 0.60, None, 17),              # Byrgius A
    (8.1, -77.6, 43, 20, 320, 0.60, None, 18),                # Olbers A
    (-33.5, 59.0, 11, 14, 260, 0.55, None, 19),               # Furnerius A
    (-31.8, 51.6, 8, 12, 220, 0.50, None, 20),                # Stevinus A
    (61.8, 50.3, 31, 16, 240, 0.50, None, 21),                # Thales
    (16.3, 16.0, 27, 10, 120, 0.45, None, 22),                # Menelaus
    (-1.9, 47.6, 11, 4, 140, 0.55, (90.0, 120.0), 23),        # Messier (westward tails)
)

# Mountain rings of the big impact basins: (lat, lon, ring radius km, height km,
#   width km, arc centre azimuth deg, arc half-width deg)
BASIN_RINGS = (
    (34.0, -16.0, 640, 3.2, 70, 130.0, 70.0),     # Imbrium: Apenninus / Caucasus / Alpes
    (34.0, -16.0, 640, 1.8, 60, 200.0, 40.0),     # Imbrium: Carpatus
    (40.0, -26.0, 380, 2.0, 50, 300.0, 40.0),     # Montes Jura around Sinus Iridum
    (28.0, 17.5, 400, 2.0, 60, 220.0, 70.0),      # Serenitatis: Haemus
    (17.0, 59.0, 330, 2.2, 55, 180.0, 180.0),     # Crisium rim
    (-15.2, 35.0, 430, 1.6, 45, 225.0, 60.0),     # Nectaris: Rupes Altai
    (-24.4, -38.6, 250, 1.4, 45, 180.0, 180.0),   # Humorum rim
    (-19.4, -92.8, 480, 2.5, 60, 90.0, 60.0),     # Orientale: Montes Cordillera
)

# Additional ray geometry: a few very long rays of Tycho (azimuth deg from
# north through east, length km, width km, brightness). The longest one
# crosses Mare Nubium and runs all the way to Mare Serenitatis.
TYCHO_LONG_RAYS = (
    (16.0, 2300.0, 22.0, 0.95),
    (31.0, 1500.0, 26.0, 0.75),
    (-10.0, 1350.0, 22.0, 0.70),
    (58.0, 1200.0, 24.0, 0.70),
    (95.0, 900.0, 22.0, 0.60),
    (150.0, 800.0, 22.0, 0.55),
    (185.0, 700.0, 22.0, 0.55),
)

# Small albedo features: (lat, lon, radius km, albedo factor).
# < 1: dark pyroclastic mantles; > 1: bright swirls / highland patches.
ALBEDO_SPOTS = (
    (19.6, 11.5, 90, 0.78),      # Sulpicius Gallus: dark rim of Serenitatis (SW)
    (20.0, 30.5, 80, 0.80),      # Taurus-Littrow dark mantle (SE rim of Serenitatis)
    (22.0, 23.0, 110, 0.88),     # dark south rim of Serenitatis
    (26.0, -51.0, 110, 0.75),    # Aristarchus plateau (dark, reddish pyroclastics)
    (12.0, -7.0, 70, 0.82),      # Sinus Aestuum dark mantle
    (-10.0, -14.0, 50, 0.92),    # Fra Mauro region mottling
    (7.4, -59.1, 30, 1.45),      # Reiner Gamma swirl
)

# Normal albedo of the highlands (the mare albedos live in MARIA).
HIGHLAND_ALBEDO = 0.150
RAY_ALBEDO = 0.235           # immature (fresh) ejecta
HEIGHT_EXAGGERATION = 1.6    # relief exaggeration used for shading and shadows

# McEwen (1991) lunar-Lambert partition L(alpha) = 1 + A a + B a^2 + C a^3 (a in deg).
_LL_POLY = (-0.019, 2.42e-4, -1.46e-6)


def lunar_lambert_weight(alpha_deg):
    """McEwen's L(alpha): 1 = pure Lommel-Seeliger (full moon), 0 = pure Lambert."""
    a = float(alpha_deg)
    v = 1.0 + _LL_POLY[0] * a + _LL_POLY[1] * a * a + _LL_POLY[2] * a ** 3
    return min(max(v, 0.0), 1.0)


def lunar_phase_curve(alpha_deg):
    """Disc-integrated brightness of the Moon relative to full (Allen's
    V(alpha) = 0.026 |alpha| + 4e-9 alpha^4 magnitudes)."""
    a = min(abs(float(alpha_deg)), 150.0)
    return 10.0 ** (-0.4 * (0.026 * a + 4.0e-9 * a ** 4))


def opposition_surge(alpha_deg, b0=0.4, h=0.05):
    """Hapke shadow-hiding opposition surge 1 + B0 / (1 + tan(alpha/2) / h)."""
    return 1.0 + b0 / (1.0 + math.tan(math.radians(min(abs(alpha_deg), 179.0)) / 2.0) / h)


def earth_phase_irradiance(alpha_deg):
    """Earthshine irradiance on the Moon relative to the 'full Earth' (new Moon):
    a Lambert sphere seen at phase angle 180 - alpha."""
    b = math.radians(180.0 - float(alpha_deg))
    return (math.sin(b) + (math.pi - b) * math.cos(b)) / math.pi


# ---------------------------------------------------------------------------
# The Moon: building the selenographic maps
# ---------------------------------------------------------------------------


def _sel_vec(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    return np.array([math.cos(la) * math.sin(lo), math.sin(la), math.cos(la) * math.cos(lo)])


def _east_north(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    e = np.array([math.cos(lo), 0.0, -math.sin(lo)])
    n = np.array([-math.sin(la) * math.sin(lo), math.cos(la), -math.sin(la) * math.cos(lo)])
    return e, n


def _map_grid(w, h):
    lat = math.pi / 2 - (np.arange(h) + 0.5) * math.pi / h
    lon = -math.pi + (np.arange(w) + 0.5) * 2 * math.pi / w
    cl, sl = np.cos(lat)[:, None], np.sin(lat)[:, None]
    p = np.stack(np.broadcast_arrays(cl * np.sin(lon)[None, :], sl, cl * np.cos(lon)[None, :]), -1)
    return lat, lon, np.ascontiguousarray(p)


@njit(inline="always")
def _sstep(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


@njit(parallel=True)
def _maria_kernel(p, blobs, edge, mask_a, mask_h, alb, col, depth):
    """Union of noisy elliptical mare blobs on the sphere.

    blobs[k]: centre(3), east(3), north(3), a, b (rad), cos rot, sin rot,
    albedo, colour, depth km, cos(max extent)."""
    h, w = p.shape[0], p.shape[1]
    for i in prange(h):
        for j in range(w):
            px, py, pz = p[i, j, 0], p[i, j, 1], p[i, j, 2]
            keep, keep_h = 1.0, 1.0
            ws, wa, wc, wh, wd = 0.0, 0.0, 0.0, 0.0, 0.0
            for k in range(blobs.shape[0]):
                b = blobs[k]
                d = px * b[0] + py * b[1] + pz * b[2]
                if d < b[16]:
                    continue
                s = math.acos(min(d, 1.0))
                te = px * b[3] + py * b[4] + pz * b[5]
                tn = px * b[6] + py * b[7] + pz * b[8]
                nn = math.sqrt(te * te + tn * tn)
                u, v = 0.0, 0.0
                if nn > 1e-12:
                    u, v = s * te / nn, s * tn / nn
                ur = u * b[11] + v * b[12]
                vr = -u * b[12] + v * b[11]
                q = math.sqrt((ur / b[9]) ** 2 + (vr / b[10]) ** 2) * edge[i, j]
                m = _sstep(1.10, 0.84, q)
                if m <= 0.0:
                    continue
                keep *= 1.0 - m
                ws += m
                wa += m * b[13]
                wc += m * b[14]
                if b[15] > 0.0:
                    keep_h *= 1.0 - m
                    wh += m
                    wd += m * b[15]
            mask_a[i, j] = 1.0 - keep
            mask_h[i, j] = 1.0 - keep_h
            alb[i, j] = wa / ws if ws > 0 else 0.0
            col[i, j] = wc / ws if ws > 0 else 0.0
            depth[i, j] = wd / wh if wh > 0 else 0.0


@njit
def _splat_craters(hmap, bright, slat, clat, slon, clon, cr):
    """Stamp craters (in the given order, old first) into the height map (km).

    cr[k]: lat, lon (rad), R (rad), depth, rim height, peak height (km),
    floor radius fraction, flood level fraction, albedo brightening.
    Younger craters overwrite the terrain they excavate; their rims and
    ejecta are added on top of it."""
    h, w = hmap.shape
    for k in range(cr.shape[0]):
        lat0, lon0, rr = cr[k, 0], cr[k, 1], cr[k, 2]
        dep, rim, peak, ffl, flood, brt = cr[k, 3], cr[k, 4], cr[k, 5], cr[k, 6], cr[k, 7], cr[k, 8]
        cx = math.cos(lat0) * math.sin(lon0)
        cy = math.sin(lat0)
        cz = math.cos(lat0) * math.cos(lon0)
        ext = min(3.0 * rr, math.pi)
        i0 = max(int((math.pi / 2 - (lat0 + ext)) / math.pi * h) - 1, 0)
        i1 = min(int((math.pi / 2 - (lat0 - ext)) / math.pi * h) + 1, h - 1)
        # two passes: (1) local datum = mean height around the crater, (2) stamp
        datum_s, datum_n, base = 0.0, 0.0, 0.0
        for npass in range(2):
            acc, cnt = 0.0, 0.0
            if npass == 1:
                base = hmap[min(max(int((math.pi / 2 - lat0) / math.pi * h), 0), h - 1),
                            int((lon0 + math.pi) / (2 * math.pi) * w) % w]
                if datum_n > 0:
                    base = datum_s / datum_n
            for i in range(i0, i1 + 1):
                cmin = min(clat[i], math.cos(lat0))
                if ext >= math.pi / 2 or cmin <= math.sin(ext) + 1e-9:
                    j0, j1 = 0, w - 1
                else:
                    dlon = math.asin(math.sin(ext) / cmin)
                    j0 = int(math.floor((lon0 - dlon + math.pi) / (2 * math.pi) * w)) - 1
                    j1 = int(math.ceil((lon0 + dlon + math.pi) / (2 * math.pi) * w)) + 1
                    if j1 - j0 >= w:
                        j0, j1 = 0, w - 1
                for jj in range(j0, j1 + 1):
                    j = jj % w
                    d = clat[i] * slon[j] * cx + slat[i] * cy + clat[i] * clon[j] * cz
                    if d <= 0.0:
                        continue
                    x = math.acos(min(d, 1.0)) / rr
                    if x >= 3.0:
                        continue
                    if npass == 0:
                        if x < 1.6:
                            acc += hmap[i, j]
                            cnt += 1.0
                        continue
                    if x < 1.0:
                        if x < ffl:
                            prof = -dep
                        else:
                            t = (x - ffl) / (1.0 - ffl)
                            prof = -dep + (dep + rim) * t * t
                        prof += peak * math.exp(-(x / 0.13) ** 2)
                        if flood > 0.0:
                            prof = max(prof, -dep * (1.0 - flood))
                    else:
                        prof = rim * x ** -3 * _sstep(3.0, 1.8, x)
                    wgt = _sstep(1.35, 0.85, x)
                    hmap[i, j] = hmap[i, j] + wgt * (base - hmap[i, j]) + prof
                    if brt > 0.0:
                        g = 1.0 if x < 1.0 else math.exp(-((x - 1.0) / 0.55) ** 2)
                        bright[i, j] = max(bright[i, j] * (1.0 - wgt), brt * g)
                    elif wgt > 0.0:
                        bright[i, j] *= 1.0 - wgt
            if npass == 0:
                datum_s, datum_n = acc, cnt


@njit(parallel=True)
def _ray_kernel(p, noise, systems, rays, out):
    """Bright ray systems. systems[k]: centre(3), east(3), north(3), crater
    radius (rad), max extent (rad), nimbus brightness, first ray, ray count.
    rays[r]: azimuth (rad), half width (rad), length (rad), brightness."""
    h, w = p.shape[0], p.shape[1]
    for i in prange(h):
        for j in range(w):
            px, py, pz = p[i, j, 0], p[i, j, 1], p[i, j, 2]
            total = 0.0
            for k in range(systems.shape[0]):
                sy = systems[k]
                d = px * sy[0] + py * sy[1] + pz * sy[2]
                s = math.acos(min(max(d, -1.0), 1.0))
                if s > sy[10]:
                    continue
                rc = sy[9]
                # nimbus: the bright continuous ejecta blanket
                if s < rc:
                    total += sy[11] * 1.6
                else:
                    total += sy[11] * 1.6 * math.exp(-((s - rc) / (1.1 * rc)) ** 2)
                te = px * sy[3] + py * sy[4] + pz * sy[5]
                tn = px * sy[6] + py * sy[7] + pz * sy[8]
                az = math.atan2(te, tn)
                ss = math.sin(s)
                start = _sstep(1.2 * rc, 3.5 * rc, s)   # rays leave from outside the rim
                if start <= 0.0:
                    continue
                for r in range(int(sy[12]), int(sy[12] + sy[13])):
                    da = az - rays[r, 0]
                    da = (da + math.pi) % (2 * math.pi) - math.pi
                    if abs(da) > 1.2:
                        continue
                    lat_off = math.asin(min(max(ss * math.sin(da), -1.0), 1.0))
                    ln = rays[r, 2]
                    wd = rays[r, 1] * (1.0 + 0.8 * min(s / ln, 1.5))
                    if abs(lat_off) > 4.0 * wd:
                        continue
                    env = start * (1.0 - _sstep(0.45 * ln, ln, s)) * math.exp(-0.8 * s / ln)
                    total += rays[r, 3] * env * math.exp(-(lat_off / wd) ** 2)
            out[i, j] = (1.0 - math.exp(-total)) * (0.35 + 0.65 * noise[i, j]) if total > 0 else 0.0


def _crater_shape(d_km, fresh):
    """Depth, rim height, peak height (km) and floor radius fraction of a
    crater of diameter d_km (Pike 1977 morphometry), degraded with age."""
    if d_km < 15.0:
        depth, rim, ffl, peak = 0.196 * d_km, 0.036 * d_km, 0.0, 0.0
    else:
        depth = 1.044 * d_km ** 0.301
        rim = 0.236 * d_km ** 0.399
        ffl = 0.2 + 0.3 * min((d_km - 15.0) / 120.0, 1.0)
        peak = 0.3 * depth if d_km > 26.0 else 0.0
    deg = 0.3 + 0.7 * fresh ** 0.6       # erosion softens and fills old craters
    return depth * deg, rim * (0.25 + 0.75 * fresh ** 0.6), peak * deg, ffl


def _crater_rows(lat, lon, d_km, fresh, flood, bright):
    rows = []
    for la, lo, d, f, fl, b in zip(lat, lon, d_km, fresh, flood, bright):
        depth, rim, peak, ffl = _crater_shape(d, f)
        rows.append((math.radians(la), math.radians(lo), d / 2.0 / R_MOON_KM,
                     depth, rim, peak, ffl, fl, b))
    return np.array(rows, dtype=np.float64).reshape(-1, 9)


def _random_craters(rng, n, d_min, d_max, slope=2.0):
    """n craters uniformly on the sphere with cumulative N(>D) ~ D^-slope."""
    u = rng.uniform(size=n)
    a = (d_min / d_max) ** slope
    d = d_min * (1.0 - u * (1.0 - a)) ** (-1.0 / slope)
    v = bh.normalize(rng.standard_normal((n, 3)))
    lat = np.degrees(np.arcsin(v[:, 1]))
    lon = np.degrees(np.arctan2(v[:, 0], v[:, 2]))
    return lat, lon, d


def _sample_map_np(arr, lat_deg, lon_deg):
    h, w = arr.shape[:2]
    i = np.clip(((90.0 - np.asarray(lat_deg)) / 180.0 * h).astype(int), 0, h - 1)
    j = (((np.asarray(lon_deg) + 180.0) / 360.0 * w).astype(int)) % w
    return arr[i, j]


@lru_cache(maxsize=2)
def moon_maps(width=2048, seed=1969):
    """Selenographic maps of the whole Moon (equirectangular, lon -180..180,
    lat 90..-90, (width/2, width) pixels).

    Returns a read-only float32 array (H, W, 5): height (km), normal albedo,
    colour index (-1 blue ... +1 red), d height / d east and d height / d north
    (dimensionless slopes)."""
    w, h = int(width), int(width) // 2
    lat, lon, p = _map_grid(w, h)
    rng = np.random.default_rng(seed)

    # --- maria -------------------------------------------------------------
    # Ragged, multi-scale coastlines: real mare shores are lobate and embayed, not ovals.
    # (fbm values cluster tightly around 0.5, so standardise them before scaling.)
    def zn(freq, octaves, sd):
        f = fbm(p, freq, octaves, sd)
        return (f - f.mean()) / max(f.std(), 1e-6)
    edge = 1.0 + 0.15 * zn(3.5, 5, seed + 1) + 0.09 * zn(11.0, 4, seed + 2) + 0.045 * zn(32.0, 3, seed + 12)
    edge = np.clip(edge, 0.55, 1.6)
    blobs = []
    for la, lo, a_km, b_km, rot_deg, alb, ci, dep in MARIA:
        c = _sel_vec(la, lo)
        e, n = _east_north(la, lo)
        a, b = a_km / R_MOON_KM, b_km / R_MOON_KM
        r = math.radians(rot_deg)
        blobs.append((*c, *e, *n, a, b, math.cos(r), math.sin(r), alb, ci, dep,
                      math.cos(min(1.6 * max(a, b), math.pi))))
    blobs = np.array(blobs)
    mask_a, mask_h, m_alb, m_col, m_dep = (np.zeros((h, w)) for _ in range(5))
    _maria_kernel(p, blobs, np.ascontiguousarray(edge), mask_a, mask_h, m_alb, m_col, m_dep)

    # --- albedo and colour -------------------------------------------------
    n_hi = fbm(p, 3.0, 5, seed + 3)
    n_hi2 = fbm(p, 14.0, 4, seed + 4)
    n_mare = fbm(p, 7.0, 5, seed + 5)
    n_col = fbm(p, 5.0, 4, seed + 6)
    south = np.clip(-p[..., 1], 0.0, 1.0)              # southern highlands are brighter
    alb_hi = HIGHLAND_ALBEDO * (1.0 + 0.16 * (n_hi - 0.5) + 0.10 * (n_hi2 - 0.5) + 0.06 * south)
    # Lava floors are mottled (flows of different titanium content) and darkest in the
    # deep basin centres.
    n_flow = fbm(p, 20.0, 4, seed + 13)
    core = np.clip((mask_a - 0.55) / 0.45, 0.0, 1.0)
    alb_mare = m_alb * (1.0 + 0.30 * (n_mare - 0.5) + 0.16 * (n_flow - 0.5) + 0.08 * (n_hi2 - 0.5)) \
        * (1.0 - 0.10 * core)
    albedo = alb_hi * (1.0 - mask_a) + alb_mare * mask_a
    colour = (0.15 + 0.5 * (n_col - 0.5)) * (1.0 - mask_a) + (m_col + 0.4 * (n_col - 0.5)) * mask_a
    for la, lo, r_km, fac in ALBEDO_SPOTS:
        c = _sel_vec(la, lo)
        s = np.arccos(np.clip(p @ c, -1.0, 1.0)) * R_MOON_KM
        g = np.exp(-(s / r_km) ** 2 * (1.0 + 0.6 * (n_hi2 - 0.5)))
        albedo *= 1.0 + (fac - 1.0) * g
        if fac < 1.0:
            colour += 0.4 * g

    # --- topography --------------------------------------------------------
    ridged = 1.0 - np.abs(2.0 * fbm(p, 6.0, 5, seed + 7) - 1.0)
    hmap = 2.2 * (fbm(p, 2.5, 6, seed + 8) - 0.5) + 1.4 * (ridged - 0.5)
    slat, clat = np.sin(lat), np.cos(lat)
    slon, clon = np.sin(lon), np.cos(lon)
    bright = np.zeros((h, w))

    # Pre-mare craters: a saturated highland population, mostly degraded.
    n_pre = int(26000 * (w / 2048.0) ** 0.5)
    rl, ro, rd = _random_craters(rng, n_pre, 7.0, 320.0)
    age = rng.uniform(size=n_pre)
    fresh = np.clip((age - 0.55) / 0.45, 0.0, 1.0) ** 2 * np.clip(1.6 - rd / 120.0, 0.0, 1.0)
    pre_named = [c for c in CRATERS if c[3] < 0.3 and c[4] < 0.5]
    post_named = [c for c in CRATERS if not (c[3] < 0.3 and c[4] < 0.5)]
    lat_all = np.concatenate([rl, [c[0] for c in pre_named]])
    lon_all = np.concatenate([ro, [c[1] for c in pre_named]])
    d_all = np.concatenate([rd, [c[2] for c in pre_named]])
    f_all = np.concatenate([fresh, [c[3] for c in pre_named]])
    fl_all = np.concatenate([np.zeros(n_pre), [c[4] for c in pre_named]])
    order = np.argsort(f_all, kind="stable")
    br_all = 0.07 * f_all ** 3
    cr = _crater_rows(lat_all[order], lon_all[order], d_all[order], f_all[order], fl_all[order], br_all[order])
    _splat_craters(hmap, bright, slat, clat, slon, clon, cr)

    # Mare flooding buries everything older: smooth lava plains with wrinkle ridges.
    wr = 1.0 - np.abs(2.0 * fbm(p, 16.0, 3, seed + 9) - 1.0)
    floor = -m_dep + 0.25 * (n_mare - 0.5) + 0.22 * np.clip(wr - 0.72, 0.0, 1.0) / 0.28
    hmap = hmap * (1.0 - mask_h) + floor * mask_h
    bright *= 1.0 - mask_a

    # Basin mountain rings stick out of the lava (Apennines, Alps, Altai, ...).
    for la, lo, r_km, hgt, w_km, az0, half in BASIN_RINGS:
        c = _sel_vec(la, lo)
        e, n = _east_north(la, lo)
        s = np.arccos(np.clip(p @ c, -1.0, 1.0)) * R_MOON_KM
        az = np.degrees(np.arctan2(p @ e, p @ n))
        daz = np.abs((az - az0 + 180.0) % 360.0 - 180.0)
        arc = 1.0 - _smoothstep(half, half + 25.0, daz)
        ring = np.exp(-((s - r_km) / w_km) ** 2) * arc
        hmap += hgt * ring * (0.25 + 0.75 * ridged ** 2)
        albedo = albedo + (alb_hi - albedo) * np.clip(ring * 1.3, 0.0, 1.0) * 0.8

    # Post-mare craters: far fewer, younger, on maria and highlands alike.
    n_post = int(2600 * (w / 2048.0) ** 0.5)
    rl, ro, rd = _random_craters(rng, n_post, 6.0, 60.0)
    age = rng.uniform(size=n_post)
    fresh = 0.35 + 0.65 * age ** 2
    lat_all = np.concatenate([rl, [c[0] for c in post_named]])
    lon_all = np.concatenate([ro, [c[1] for c in post_named]])
    d_all = np.concatenate([rd, [c[2] for c in post_named]])
    f_all = np.concatenate([fresh, [c[3] for c in post_named]])
    fl_all = np.concatenate([np.zeros(n_post), [c[4] for c in post_named]])
    order = np.argsort(f_all, kind="stable")
    br_all = np.where(np.arange(len(f_all)) >= n_post, 0.10, 0.06) * f_all ** 3
    cr = _crater_rows(lat_all[order], lon_all[order], d_all[order], f_all[order], fl_all[order], br_all[order])
    _splat_craters(hmap, bright, slat, clat, slon, clon, cr)

    # Fresh crater interiors and ejecta are bright (immature regolith) and bluer.
    albedo = albedo + (RAY_ALBEDO + 0.08 - albedo) * np.clip(bright / 0.10, 0.0, 1.0) * 0.85
    colour -= 0.6 * np.clip(bright / 0.10, 0.0, 1.0)

    # --- ray systems -------------------------------------------------------
    systems, rays = [], []
    for k, (la, lo, d_km, n_rays, l_km, b, avoid, rseed) in enumerate(RAYS):
        rr = np.random.default_rng(rseed)
        c = _sel_vec(la, lo)
        e, n = _east_north(la, lo)
        first = len(rays)
        az = rr.uniform(0.0, 360.0, n_rays)
        if avoid is not None:
            daz = np.abs((az - avoid[0] + 180.0) % 360.0 - 180.0)
            az = np.where(daz < avoid[1], (az + 2.0 * avoid[1] * np.sign(az - avoid[0] + 1e-9)) % 360.0, az)
        lens = l_km * rr.lognormal(0.0, 0.45, n_rays)
        for a, ln in zip(az, lens):
            rays.append((math.radians(a), rr.uniform(0.12, 0.35) * d_km / R_MOON_KM,
                         ln / R_MOON_KM, b * rr.uniform(0.35, 1.0)))
        if k == 0:          # Tycho
            for a, ln, wd, bb in TYCHO_LONG_RAYS:
                rays.append((math.radians(a), wd / R_MOON_KM, ln / R_MOON_KM, bb))
        ext = max(r[2] for r in rays[first:]) * 1.05
        systems.append((*c, *e, *n, d_km / 2.0 / R_MOON_KM, ext, b, first, len(rays) - first))
    ray_noise = fbm(p, 45.0, 4, seed + 10)
    ray_noise = np.clip((ray_noise - 0.3) / 0.5, 0.0, 1.0)
    ray = np.zeros((h, w))
    _ray_kernel(p, np.ascontiguousarray(ray_noise), np.array(systems), np.array(rays), ray)
    albedo = albedo + (RAY_ALBEDO - albedo) * np.clip(ray, 0.0, 1.0) * 0.9
    colour -= 0.35 * ray

    # --- slopes ------------------------------------------------------------
    dl = 2.0 * math.pi / w * R_MOON_KM
    dphi = math.pi / h * R_MOON_KM
    ge = (np.roll(hmap, -1, 1) - np.roll(hmap, 1, 1)) / (2.0 * dl * np.maximum(clat, 0.02)[:, None])
    gn = np.zeros_like(hmap)
    gn[1:-1] = (hmap[:-2] - hmap[2:]) / (2.0 * dphi)

    out = np.stack([hmap, albedo, np.clip(colour, -1.5, 1.5), ge, gn], -1).astype(np.float32)
    out.setflags(write=False)
    return out


# ---------------------------------------------------------------------------
# The Moon: shading
# ---------------------------------------------------------------------------


@njit(inline="always")
def _map_coords(x, y, z, h, w):
    lat = math.asin(min(max(y, -1.0), 1.0))
    lon = math.atan2(x, z)
    fi = (0.5 * math.pi - lat) / math.pi * h - 0.5
    fi = min(max(fi, 0.0), h - 1.001)
    fj = (lon + math.pi) / (2.0 * math.pi) * w - 0.5
    i0 = int(fi)
    fl = math.floor(fj)
    j0 = int(fl) % w
    return i0, j0, (j0 + 1) % w, fi - i0, fj - fl


@njit(inline="always")
def _bil(m, c, i0, j0, j1, di, dj):
    return ((m[i0, j0, c] * (1.0 - dj) + m[i0, j1, c] * dj) * (1.0 - di)
            + (m[i0 + 1, j0, c] * (1.0 - dj) + m[i0 + 1, j1, c] * dj) * di)


@njit(parallel=True)
def _moon_kernel(xs, ys, sin_rad, mp, r_km, exag, lx, ly, lz, ll_w, sun_r,
                 t0, t1, e0, e1, out):
    """Shade the Moon seen from the Earth (x right = lunar east, y up = north,
    z towards the viewer) lit by the Sun from direction (lx, ly, lz).

    out[..., 0:3] sunlit radiance factor x colour, out[..., 3:6] earthshine
    (albedo x colour, the caller scales it)."""
    nr, nc = ys.shape[0], xs.shape[0]
    h, w = mp.shape[0], mp.shape[1]
    hs = exag / r_km
    for r in prange(nr):
        for c in range(nc):
            x, y = xs[c], ys[r]
            rt = math.sqrt(x * x + y * y)
            rho = math.sin(math.atan(rt)) / sin_rad
            for k in range(6):
                out[r, c, k] = 0.0
            if rho >= 1.0:
                continue
            px, py = 0.0, 0.0
            if rt > 0.0:
                px, py = x / rt * rho, y / rt * rho
            pz = math.sqrt(max(1.0 - rho * rho, 0.0))
            i0, j0, j1, di, dj = _map_coords(px, py, pz, h, w)
            hh = _bil(mp, 0, i0, j0, j1, di, dj)
            alb = _bil(mp, 1, i0, j0, j1, di, dj)
            ci = _bil(mp, 2, i0, j0, j1, di, dj)
            ge = _bil(mp, 3, i0, j0, j1, di, dj) * exag
            gn = _bil(mp, 4, i0, j0, j1, di, dj) * exag
            # local east / north on the sphere
            clat = math.sqrt(max(1.0 - py * py, 1e-12))
            ex, ez = pz / clat, -px / clat
            nx_, ny_, nz_ = -py * px / clat, clat, -py * pz / clat
            vx = px - ge * ex - gn * nx_
            vy = py - gn * ny_
            vz = pz - ge * ez - gn * nz_
            vn = math.sqrt(vx * vx + vy * vy + vz * vz)
            vx, vy, vz = vx / vn, vy / vn, vz / vn
            mu0 = vx * lx + vy * ly + vz * lz
            mu = max(vz, 0.02)
            lit = 0.0
            mu0g = px * lx + py * ly + pz * lz
            if mu0 > 0.0 and mu0g > -0.08:
                lit = 2.0 * ll_w * mu0 / (mu0 + mu) + (1.0 - ll_w) * mu0
                # cast shadows: march towards the Sun over the relief, with the
                # penumbra of the 0.53 degree solar disc
                rad = 1.0 + hh * hs
                ox, oy, oz = px * rad, py * rad, pz * rad
                t = 0.0012
                vis = 1.0
                for _ in range(90):
                    qx, qy, qz = ox + t * lx, oy + t * ly, oz + t * lz
                    rq = math.sqrt(qx * qx + qy * qy + qz * qz)
                    a0, b0, b1, da, db = _map_coords(qx / rq, qy / rq, qz / rq, h, w)
                    surf = 1.0 + _bil(mp, 0, a0, b0, b1, da, db) * hs
                    occ = (rq - surf) / t
                    vis = min(vis, min(max(0.5 + 0.5 * occ / sun_r, 0.0), 1.0))
                    if vis <= 0.0:
                        break
                    t *= 1.07
                    if t > 0.3 or rq > 1.0 + 12.0 * hs:
                        break
                lit *= vis
            for k in range(3):
                col = t0[k] + ci * t1[k]
                out[r, c, k] = alb * lit * col
                out[r, c, 3 + k] = alb * (e0[k] + ci * e1[k])


def _moon_tints(desat=0.55, es_desat=0.25):
    """Linear sRGB tints, white balanced to sunlight: the lunar reflectance
    spectrum (reddish, colour index varying its slope) for sunlight, and the
    same for earthshine (sunlight reflected by the blue Earth first). The
    tints are normalised to luminance 1 and partially desaturated (`desat`),
    like a daylight white-balanced photograph of the Moon.

    Returns t0, t1, e0, e1: colour = t0 + ci * t1 (sunlit), e0 + ci * e1 (earthshine)."""
    sun = _planck(_LAM, T_SUN)
    ref = 1.0 + 0.20 * (_LAM - 550.0) / 100.0       # B-V(Moon) - B-V(Sun) ~ 0.27 mag
    dref = 0.05 * (_LAM - 550.0) / 100.0            # per unit colour index
    earth = (_LAM / 550.0) ** -1.6                  # Rayleigh + ocean dominated Earth albedo
    white = _spec_to_rgb(sun)

    def tint(spec):
        return _spec_to_rgb(spec) / white

    t0, t1 = tint(sun * ref), tint(sun * dref)
    e0, e1 = tint(sun * earth * ref), tint(sun * earth * dref)
    y0, ye = float(t0 @ bh.LUMA), float(e0 @ bh.LUMA)
    t0s = (1.0 - desat) * t0 / y0 + desat
    e0s = (1.0 - es_desat) * e0 / ye + es_desat
    return t0s, (1.0 - desat) * t1 / y0, e0s, (1.0 - es_desat) * e1 / ye


def _phase_brightness(alpha_deg):
    """Relative surface brightness factor of the lunar disc at phase angle alpha
    (beyond the per-pixel lunar-Lambert shading): the empirical lunar phase
    curve divided by the disc integral of the shading law, times the surge."""
    a = min(float(alpha_deg), 150.0)
    n = 400
    t = (np.arange(n) + 0.5) / n * 2 - 1
    x, y = np.meshgrid(t, t)
    inside = x * x + y * y < 1
    z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))

    def integral(al):
        ar = math.radians(al)
        mu0 = np.clip(x * math.sin(ar) + z * math.cos(ar), 0, None)
        llw = lunar_lambert_weight(al)
        s = 2 * llw * mu0 / (mu0 + np.maximum(z, 1e-6)) + (1 - llw) * mu0
        return float(s[inside].sum())

    f = lunar_phase_curve(a) / (integral(a) / integral(0.0))
    return f * opposition_surge(a) / opposition_surge(0.0)


MOON_GLOW = (
    (0.030, "gauss", 0.22),       # scattering in the eye / optics hugging the limb
    (0.020, "lorentz2", 0.9),     # thin-haze aureole
)

MOON_EXPOSURE = 5.0       # display scale: full-moon highlands (albedo 0.15) -> ~0.75 linear
PHASE_COMPENSATION = 0.6  # 0 = constant exposure for all phases, 1 = every phase equally bright
EARTHSHINE = 0.035        # display radiance of earthshine (full Earth) per unit albedo


def _tone_moon(rgb):
    """Linear toe, soft highlight shoulder on luminance (keeps the hue)."""
    y = np.maximum(rgb @ bh.LUMA, 1e-12)
    k = 0.62
    y2 = np.where(y < k, y, k + (1 - k) * (1 - np.exp(-(y - k) / (1 - k))))
    return np.clip(rgb * (y2 / y)[..., None], 0.0, 1.0)


def render_moon_phase(name, size=512, ss=3, map_width=2048, seed=1969):
    """One moon phase texture (size, size, 4) uint8, additive-alpha encoded."""
    alpha_deg, side = PHASE_GEOMETRY[name]
    return _render_moon(alpha_deg, side, size, ss, map_width, seed)


def _render_moon(alpha_deg, side, size=512, ss=3, map_width=2048, seed=1969, exag=HEIGHT_EXAGGERATION):
    mp = moon_maps(map_width, seed)
    radius_tan = math.tan(math.radians(MOON_DIAMETER_DEG / 2.0))
    box = _disc_box(size, MOON_HALF_TAN, radius_tan, margin=1.03)
    x, y = _tan_grid(size, MOON_HALF_TAN, ss, box)
    xs = np.ascontiguousarray(x[0])
    ys = np.ascontiguousarray(y[:, 0])
    a = math.radians(alpha_deg)
    lx, ly, lz = side * math.sin(a), 0.0, math.cos(a)
    t0, t1, e0, e1 = _moon_tints()
    out = np.zeros((len(ys), len(xs), 6))
    _moon_kernel(xs, ys, math.sin(math.atan(radius_tan)), mp, R_MOON_KM, float(exag),
                 lx, ly, lz, lunar_lambert_weight(alpha_deg), math.radians(0.2665),
                 t0, t1, e0, e1, out)
    out = _bin(out, ss)

    pb = _phase_brightness(alpha_deg)
    lit_scale = MOON_EXPOSURE * pb ** (1.0 - PHASE_COMPENSATION)
    es_scale = EARTHSHINE * earth_phase_irradiance(alpha_deg)
    hdr = np.zeros((size, size, 3))
    r0, r1, c0, c1 = box
    hdr[r0:r1, c0:c1] = out[..., :3] * lit_scale + out[..., 3:] * es_scale

    kern = _glare_kernel(size, MOON_HALF_TAN, MOON_GLOW, taper=(3.5, 9.0))
    total = sum(wt for wt, _, _ in MOON_GLOW)
    hdr = hdr * (1.0 - total) + _fft_convolve(hdr, kern)
    srgb = bh.srgb_encode(_tone_moon(np.maximum(hdr, 0.0)))
    return encode_additive(srgb, dither_seed=seed + int(alpha_deg) * 2 + (side > 0))


def make_moon_phases(size=512, ss=3, map_width=2048, seed=1969):
    """All eight moon phases: {name: (size, size, 4) uint8}, keyed by the
    1.21.11+ texture names (textures/environment/celestial/moon/<name>.png)."""
    return {name: render_moon_phase(name, size, ss, map_width, seed) for name in PHASES}


def _resize_rgba(rgba, size):
    """Resample an additive-encoded texture in linear light and re-encode it."""
    from PIL import Image
    if rgba.shape[0] == size and rgba.shape[1] == size:
        return rgba
    lin = _srgb_to_linear(decode_additive(rgba))
    chans = [np.asarray(Image.fromarray(lin[..., c].astype(np.float32), "F").resize((size, size), Image.LANCZOS))
             for c in range(3)]
    return encode_additive(bh.srgb_encode(np.clip(np.stack(chans, -1), 0.0, 1.0)))


def _srgb_to_linear(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def moon_phase_sheet(phases, size=None):
    """Legacy (<= 1.21.10) textures/environment/moon_phases.png: 4 columns x 2
    rows in Minecraft's phase order (row-major: full, waning gibbous, third
    quarter, waning crescent / new, waxing crescent, first quarter, waxing
    gibbous). Returns (2 s, 4 s, 4) uint8; s = size or the phases' size."""
    s = int(size) if size is not None else phases[PHASES[0]].shape[0]
    sheet = np.zeros((2 * s, 4 * s, 4), dtype=np.uint8)
    for k, name in enumerate(PHASES):
        r, c = divmod(k, 4)
        sheet[r * s:(r + 1) * s, c * s:(c + 1) * s] = _resize_rgba(phases[name], s)
    return sheet


def pack_textures(sun_size=512, moon_size=512):
    """Every celestial texture the pack ships: {pack-relative path: RGBA uint8}."""
    sun = make_sun(sun_size)
    phases = make_moon_phases(moon_size)
    files = {
        "textures/environment/sun.png": sun,                  # <= 1.21.10
        "textures/environment/celestial/sun.png": sun,        # 1.21.11+
        "textures/environment/moon_phases.png": moon_phase_sheet(phases),
    }
    for name, img in phases.items():
        files[f"textures/environment/celestial/moon/{name}.png"] = img
    return files
