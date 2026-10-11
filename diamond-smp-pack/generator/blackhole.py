"""Physically based Schwarzschild black hole renderer for the Diamond SMP skies.

Units: the Schwarzschild radius is 1 (so M = 0.5). Light rays are traced
backwards from the camera with the exact null-geodesic orbit equation written
in Cartesian form,

    d2x/dl2 = -1.5 * h^2 * x / r^5,      h = |x cross v|

which gives the true shadow size, the photon ring and every lensed image of
the disk. The accretion disk is a thin, optically thick Novikov-Thorne disk:

* each ring glows as a blackbody at T(r) ~ r^-3/4 (1 - sqrt(r_in/r))^1/4,
* the observed colour is the blackbody at g*T, where g is the exact redshift
  for gas on circular geodesic orbits (relativistic Doppler + gravitational
  redshift), so the approaching side is bluer and brighter,
* surfaces are limb-darkened (Chandrasekhar's electron-scattering law),
* blackbody colours are integrated against the CIE 1931 observer.

The background is a synthetic but realistic galaxy: stars with real
magnitude/colour statistics and a Milky Way band with a bulge, star clouds,
dark dust lanes and emission nebulae. It is lensed by the hole as well.
"""

import math

import numpy as np
from numba import njit, prange

# ---------------------------------------------------------------------------
# Small vector helpers
# ---------------------------------------------------------------------------


def normalize(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def rot(deg, axis):
    """3x3 rotation matrix with the same meaning as glRotatef."""
    x, y, z = normalize(axis)
    a = math.radians(deg)
    c, s, t = math.cos(a), math.sin(a), 1 - math.cos(a)
    return np.array([
        [c + x * x * t, x * y * t - z * s, x * z * t + y * s],
        [y * x * t + z * s, c + y * y * t, y * z * t - x * s],
        [z * x * t - y * s, z * y * t + x * s, c + z * z * t],
    ])


def mc_direction(yaw, pitch):
    """Minecraft look vector: yaw 0 = south (+z), yaw 90 = west, pitch -90 = up."""
    y, p = math.radians(yaw), math.radians(pitch)
    return np.array([-math.sin(y) * math.cos(p), -math.sin(p), math.cos(y) * math.cos(p)])


def world_to_scene(target_dir, up=(0.0, 1.0, 0.0)):
    """Rotation that maps world directions so that `target_dir` becomes +z."""
    f = normalize(target_dir)
    r = normalize(np.cross(f, up))
    u = np.cross(r, f)
    # scene basis: forward (0,0,1), up (0,1,0), right = f x u = (-1,0,0)
    return np.stack([-r, u, f])  # rows: scene x, y, z expressed in world coords


# ---------------------------------------------------------------------------
# Colour science
# ---------------------------------------------------------------------------

XYZ_TO_SRGB = np.array([
    [3.2406, -1.5372, -0.4986],
    [-0.9689, 1.8758, 0.0415],
    [0.0557, -0.2040, 1.0570],
])
LUMA = np.array([0.2126, 0.7152, 0.0722])


def _cie_cmf(lam):
    """CIE 1931 2-degree colour matching functions (Wyman, Sloan & Shirley fit)."""
    def g(mu, s1, s2):
        s = np.where(lam < mu, s1, s2)
        return np.exp(-0.5 * ((lam - mu) / s) ** 2)
    x = 1.056 * g(599.8, 37.9, 31.0) + 0.362 * g(442.0, 16.0, 26.7) - 0.065 * g(501.1, 20.4, 26.2)
    y = 0.821 * g(568.8, 46.9, 40.5) + 0.286 * g(530.9, 16.3, 31.1)
    z = 1.217 * g(437.0, 11.8, 36.0) + 0.681 * g(459.0, 26.0, 13.8)
    return np.stack([x, y, z], -1)


def blackbody_lut(n=2048, t_min=600.0, t_max=1.0e6):
    """Linear sRGB radiance of a blackbody vs temperature (6500 K has luminance 1)."""
    lam = np.arange(380.0, 781.0, 2.0)
    cmf = _cie_cmf(lam)
    temps = np.geomspace(t_min, t_max, n)
    lm = lam * 1e-9
    with np.errstate(over="ignore"):
        planck = 1.0 / (lm[None, :] ** 5 * np.expm1(1.4387769e-2 / (lm[None, :] * temps[:, None])))
    xyz = planck @ cmf
    rgb = np.clip(xyz @ XYZ_TO_SRGB.T, 0, None)
    y6500 = np.interp(math.log(6500.0), np.log(temps), xyz[:, 1])
    return np.ascontiguousarray(rgb / y6500), math.log(t_min), math.log(t_max)


BB_LUT, BB_LO, BB_HI = blackbody_lut()


def blackbody_colour(temp):
    """Blackbody tint (luminance normalised to 1) for an array of temperatures."""
    temp = np.asarray(temp, dtype=np.float64)
    x = (np.log(np.clip(temp, 600, 1e6)) - BB_LO) / (BB_HI - BB_LO) * (len(BB_LUT) - 1)
    i = np.clip(x.astype(int), 0, len(BB_LUT) - 2)
    f = (x - i)[..., None]
    rgb = BB_LUT[i] * (1 - f) + BB_LUT[i + 1] * f
    return rgb / (rgb @ LUMA)[..., None]


@njit(inline="always")
def _bb(lut, lo, hi, temp):
    n = lut.shape[0]
    x = (math.log(max(temp, 1.0)) - lo) / (hi - lo) * (n - 1)
    if x <= 0.0:
        return lut[0, 0], lut[0, 1], lut[0, 2]
    if x >= n - 1:
        return lut[n - 1, 0], lut[n - 1, 1], lut[n - 1, 2]
    i = int(x)
    f = x - i
    return (lut[i, 0] * (1 - f) + lut[i + 1, 0] * f,
            lut[i, 1] * (1 - f) + lut[i + 1, 1] * f,
            lut[i, 2] * (1 - f) + lut[i + 1, 2] * f)


# ---------------------------------------------------------------------------
# Cube map helpers (background galaxy). Face order: +x, -x, +y, -y, +z, -z
# ---------------------------------------------------------------------------


def cube_face_dirs(size, face):
    t = (np.arange(size) + 0.5) / size * 2 - 1
    a, b = np.meshgrid(t, t)
    one = np.ones_like(a)
    d = [(one, -b, -a), (-one, -b, a), (a, one, b), (a, -one, -b), (a, -b, one), (-a, -b, -one)][face]
    d = np.stack(d, axis=-1)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


@njit(inline="always")
def _cube_coords(x, y, z):
    ax, ay, az = abs(x), abs(y), abs(z)
    if ax >= ay and ax >= az:
        if x > 0:
            return 0, -z / ax, -y / ax
        return 1, z / ax, -y / ax
    if ay >= az:
        if y > 0:
            return 2, x / ay, z / ay
        return 3, x / ay, -z / ay
    if z > 0:
        return 4, x / az, -y / az
    return 5, -x / az, -y / az


@njit(inline="always")
def _sample_cube(cube, x, y, z):
    face, a, b = _cube_coords(x, y, z)
    s = cube.shape[1]
    fu = min(max((a + 1) * 0.5 * s - 0.5, 0.0), s - 1.001)
    fv = min(max((b + 1) * 0.5 * s - 0.5, 0.0), s - 1.001)
    iu, iv = int(fu), int(fv)
    du, dv = fu - iu, fv - iv
    r = np.zeros(3)
    for c in range(3):
        r[c] = ((cube[face, iv, iu, c] * (1 - du) + cube[face, iv, iu + 1, c] * du) * (1 - dv)
                + (cube[face, iv + 1, iu, c] * (1 - du) + cube[face, iv + 1, iu + 1, c] * du) * dv)
    return r


# ---------------------------------------------------------------------------
# Procedural noise
# ---------------------------------------------------------------------------


@njit(inline="always")
def _hash3(ix, iy, iz, seed):
    h = (ix * 374761393 + iy * 668265263 + iz * 2147483647 + seed * 144269504) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return (h & 0xFFFFFF) / 16777215.0


@njit(inline="always")
def _smooth(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


@njit
def value_noise3(x, y, z, seed):
    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = _smooth(x - ix), _smooth(y - iy), _smooth(z - iz)
    ix, iy, iz = int(ix), int(iy), int(iz)
    c000 = _hash3(ix, iy, iz, seed)
    c100 = _hash3(ix + 1, iy, iz, seed)
    c010 = _hash3(ix, iy + 1, iz, seed)
    c110 = _hash3(ix + 1, iy + 1, iz, seed)
    c001 = _hash3(ix, iy, iz + 1, seed)
    c101 = _hash3(ix + 1, iy, iz + 1, seed)
    c011 = _hash3(ix, iy + 1, iz + 1, seed)
    c111 = _hash3(ix + 1, iy + 1, iz + 1, seed)
    x00 = c000 + (c100 - c000) * fx
    x10 = c010 + (c110 - c010) * fx
    x01 = c001 + (c101 - c001) * fx
    x11 = c011 + (c111 - c011) * fx
    y0 = x00 + (x10 - x00) * fy
    y1 = x01 + (x11 - x01) * fy
    return y0 + (y1 - y0) * fz


@njit
def fbm3(x, y, z, octaves, seed):
    total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
    for o in range(octaves):
        total += amp * value_noise3(x * freq, y * freq, z * freq, seed + o * 17)
        norm += amp
        amp *= 0.5
        freq *= 2.03
    return total / norm


def periodic_noise(h, w, seed, aniso=6.0, alpha=1.6):
    """Tileable fractal noise, stretched along the width axis (orbital streaks)."""
    rng = np.random.default_rng(seed)
    white = rng.standard_normal((h, w))
    fu = np.fft.fftfreq(w)[None, :] * w
    fv = np.fft.fftfreq(h)[:, None] * h
    k = np.sqrt((fu / aniso) ** 2 + fv ** 2) + 1.0
    field = np.real(np.fft.ifft2(np.fft.fft2(white) * k ** (-alpha)))
    lo, hi = np.percentile(field, [1, 99])
    return np.clip((field - lo) / (hi - lo), 0, 1)


# ---------------------------------------------------------------------------
# Background galaxy
# ---------------------------------------------------------------------------


@njit(parallel=True)
def _galaxy_kernel(dirs, gn, gc, gs, seed, c_disk, c_bulge, c_young, out):
    for i in prange(dirs.shape[0]):
        x, y, z = dirs[i, 0], dirs[i, 1], dirs[i, 2]
        sb = x * gn[0] + y * gn[1] + z * gn[2]
        b = math.asin(min(max(sb, -1.0), 1.0))
        l = math.atan2(x * gs[0] + y * gs[1] + z * gs[2], x * gc[0] + y * gc[1] + z * gc[2])
        warp = (fbm3(x * 2.0 + 3.1, y * 2.0, z * 2.0, 4, seed + 1) - 0.5) * 0.06
        bb = b - warp
        thick = 0.06 + 0.05 * fbm3(x * 3.0, y * 3.0 + 7.0, z * 3.0, 4, seed + 2)
        disk = math.exp(-abs(bb) / thick) * (0.22 + 0.78 * math.exp(-(l / 1.25) ** 2))
        halo = math.exp(-abs(bb) / 0.35) * 0.06
        bulge = 1.7 * math.exp(-((l / 0.24) ** 2 + (bb / 0.16) ** 2))
        clouds = fbm3(x * 7.0, y * 7.0, z * 7.0, 6, seed + 3)
        clouds = 0.25 + 1.6 * clouds ** 2.4
        young = max(fbm3(x * 5.0 + 9.0, y * 5.0, z * 5.0, 5, seed + 4) - 0.5, 0.0) * 2.0
        # Dust: ridged noise concentrated in the mid-plane (the "Great Rift").
        ridge = 1.0 - abs(2.0 * fbm3(x * 9.0 + 1.3, y * 9.0, z * 9.0 - 4.0, 6, seed + 5) - 1.0)
        lane = math.exp(-(bb / (0.03 + 0.03 * fbm3(x * 4.0, y * 4.0, z * 4.0 + 2.0, 3, seed + 6))) ** 2)
        tau = lane * (0.5 + 4.0 * max(ridge - 0.45, 0.0) ** 1.2)
        tau += 0.6 * math.exp(-(bb / 0.012) ** 2)
        neb = max(fbm3(x * 16.0, y * 16.0 - 3.0, z * 16.0, 5, seed + 8) - 0.64, 0.0) * 9.0
        neb *= math.exp(-(bb / 0.05) ** 2)
        for c in range(3):
            col = (c_disk[c] * disk * clouds * (1.0 - 0.6 * young) + c_young[c] * disk * clouds * young
                   + c_bulge[c] * bulge * (0.55 + 0.6 * clouds) + c_disk[c] * halo)
            redden = (1.25, 1.0, 0.75)[c]  # dust dims blue light most
            col *= math.exp(-tau / redden)
            col += neb * (0.95, 0.22, 0.30)[c] * math.exp(-0.5 * tau)  # H-alpha pink
            out[i, c] = col


@njit
def _splat_stars(cube, sdirs, scol, sigma):
    s = cube.shape[1]
    norm = 1.0 / (2.0 * math.pi * sigma * sigma)
    rad = int(math.ceil(sigma * 3.5))
    for k in range(sdirs.shape[0]):
        face, a, b = _cube_coords(sdirs[k, 0], sdirs[k, 1], sdirs[k, 2])
        fu = (a + 1) * 0.5 * s - 0.5
        fv = (b + 1) * 0.5 * s - 0.5
        cu, cv = int(round(fu)), int(round(fv))
        for dv in range(-rad, rad + 1):
            for du in range(-rad, rad + 1):
                u, v = cu + du, cv + dv
                if u < 0 or v < 0 or u >= s or v >= s:
                    continue
                w = norm * math.exp(-((u - fu) ** 2 + (v - fv) ** 2) / (2 * sigma * sigma))
                for c in range(3):
                    cube[face, v, u, c] += scol[k, c] * w


def make_galaxy(size, seed, galactic_north, galactic_centre, n_stars=200000,
                diffuse=0.012, star_flux=0.35, mag_range=(-1.5, 12.5)):
    """Cube map of a realistic night sky (linear radiance, scene frame)."""
    rng = np.random.default_rng(seed)
    gn = normalize(galactic_north)
    gc = normalize(np.asarray(galactic_centre, float) - gn * (np.dot(galactic_centre, gn)))
    gs = np.cross(gn, gc)
    c_disk = blackbody_colour(5400.0)
    c_bulge = blackbody_colour(4300.0)
    c_young = blackbody_colour(11000.0)
    cube = np.zeros((6, size, size, 3))
    for f in range(6):
        d = cube_face_dirs(size, f).reshape(-1, 3)
        out = np.zeros((d.shape[0], 3))
        _galaxy_kernel(d, gn, gc, gs, seed, c_disk, c_bulge, c_young, out)
        cube[f] = out.reshape(size, size, 3) * diffuse

    # Star counts grow ~10^(0.33 m) per magnitude; faint stars hug the galactic plane.
    m_lo, m_hi = mag_range
    a = 0.33
    n_try = int(n_stars * 2.2)
    u = rng.uniform(size=n_try)
    mag = np.log10(10 ** (a * m_lo) + u * (10 ** (a * m_hi) - 10 ** (a * m_lo))) / a
    dirs = normalize(rng.standard_normal((n_try, 3)))
    lat = np.abs(dirs @ gn)
    keep_p = np.where(mag < 5.5, 1.0, 0.2 + 0.8 * np.exp(-lat / 0.18))
    keep = rng.uniform(size=n_try) < keep_p
    dirs, mag = dirs[keep][:n_stars], mag[keep][:n_stars]
    n = len(mag)
    classes = np.array([3300, 4500, 5600, 6600, 8500, 15000, 28000], float)
    probs = np.array([0.24, 0.30, 0.16, 0.12, 0.10, 0.06, 0.02])
    temp = rng.choice(classes, n, p=probs) * rng.uniform(0.9, 1.1, n)
    flux = 10 ** (-0.4 * mag) * star_flux
    col = blackbody_colour(temp) * flux[:, None]
    _splat_stars(cube, dirs, col, 0.75 * size / 1024)
    return cube


# ---------------------------------------------------------------------------
# The ray tracer
# ---------------------------------------------------------------------------

P_RIN, P_ROUT, P_STEPK, P_DTMAX, P_RESC, P_MAXSTEP, P_TMAX, P_TAU, P_TWIST, P_EMIS, P_TURB = range(11)
F_PEAK = (36 / 49) ** 0.75 * (1 / 7) ** 0.25  # peak of the Novikov-Thorne profile (r = 49/36 r_in)


@njit(inline="always")
def _noise2(tex, u, v):
    h, w = tex.shape
    fu = (u - math.floor(u)) * w
    fv = min(max(v, 0.0), 1.0) * (h - 1.001)
    iu, iv = int(fu) % w, int(fv)
    du, dv = fu - math.floor(fu), fv - iv
    iu1 = (iu + 1) % w
    return ((tex[iv, iu] * (1 - du) + tex[iv, iu1] * du) * (1 - dv)
            + (tex[iv + 1, iu] * (1 - du) + tex[iv + 1, iu1] * du) * dv)


@njit(inline="always")
def _accel(x, y, z, h2):
    r2 = x * x + y * y + z * z
    f = -1.5 * h2 / (r2 * r2 * math.sqrt(r2))
    return f * x, f * y, f * z


@njit(parallel=True, fastmath=True)
def trace(dirs, obs, nrm, e1, e2, prm, lut, lut_lo, lut_hi, noise, bg, use_bg, out):
    """Trace each direction from `obs`.

    out[:, 0:3] disk light, out[:, 3:6] lensed background light,
    out[:, 6] how much of the pixel is the black shadow.
    """
    r_in, r_out = prm[P_RIN], prm[P_ROUT]
    step_k, dt_max, r_esc = prm[P_STEPK], prm[P_DTMAX], prm[P_RESC]
    max_steps = int(prm[P_MAXSTEP])
    lr_in, lr_out = math.log(r_in), math.log(r_out)
    nx, ny, nz = nrm[0], nrm[1], nrm[2]
    r0 = math.sqrt(obs[0] ** 2 + obs[1] ** 2 + obs[2] ** 2)
    for i in prange(dirs.shape[0]):
        x, y, z = obs[0], obs[1], obs[2]
        vx, vy, vz = dirs[i, 0], dirs[i, 1], dirs[i, 2]
        lx, ly, lz = y * vz - z * vy, z * vx - x * vz, x * vy - y * vx
        h2 = lx * lx + ly * ly + lz * lz
        h = math.sqrt(h2)
        lam = 0.0  # photon angular momentum about the disk axis (E = 1)
        if h > 1e-12:
            b = h / math.sqrt(max(1.0 - h2 / (r0 * r0 * r0), 1e-6))
            lam = -(lx * nx + ly * ny + lz * nz) / h * b
        trans = 1.0
        er, eg, eb = 0.0, 0.0, 0.0
        shadow = 0.0
        escaped = False
        for _ in range(max_steps):
            r = math.sqrt(x * x + y * y + z * z)
            dt = min(step_k * r * (0.6 + 0.4 * min(r / 3.0, 1.0)), dt_max)
            a1x, a1y, a1z = _accel(x, y, z, h2)
            a2x, a2y, a2z = _accel(x + 0.5 * dt * vx, y + 0.5 * dt * vy, z + 0.5 * dt * vz, h2)
            b2x, b2y, b2z = vx + 0.5 * dt * a1x, vy + 0.5 * dt * a1y, vz + 0.5 * dt * a1z
            a3x, a3y, a3z = _accel(x + 0.5 * dt * b2x, y + 0.5 * dt * b2y, z + 0.5 * dt * b2z, h2)
            b3x, b3y, b3z = vx + 0.5 * dt * a2x, vy + 0.5 * dt * a2y, vz + 0.5 * dt * a2z
            b4x, b4y, b4z = vx + dt * a3x, vy + dt * a3y, vz + dt * a3z
            a4x, a4y, a4z = _accel(x + dt * b3x, y + dt * b3y, z + dt * b3z, h2)
            qx = x + dt / 6 * (vx + 2 * b2x + 2 * b3x + b4x)
            qy = y + dt / 6 * (vy + 2 * b2y + 2 * b3y + b4y)
            qz = z + dt / 6 * (vz + 2 * b2z + 2 * b3z + b4z)
            vx += dt / 6 * (a1x + 2 * a2x + 2 * a3x + a4x)
            vy += dt / 6 * (a1y + 2 * a2y + 2 * a3y + a4y)
            vz += dt / 6 * (a1z + 2 * a2z + 2 * a3z + a4z)
            rq = math.sqrt(qx * qx + qy * qy + qz * qz)

            s0 = x * nx + y * ny + z * nz
            s1 = qx * nx + qy * ny + qz * nz
            if s0 * s1 < 0.0:
                f = s0 / (s0 - s1)
                px, py, pz = x + f * (qx - x), y + f * (qy - y), z + f * (qz - z)
                rp = math.sqrt(px * px + py * py + pz * pz)
                if rp > r_in * 0.95 and rp < r_out:
                    phi = math.atan2(px * e2[0] + py * e2[1] + pz * e2[2],
                                     px * e1[0] + py * e1[1] + pz * e1[2])
                    lr = math.log(rp)
                    v = (lr - lr_in) / (lr_out - lr_in)
                    u = phi / (2 * math.pi)
                    n1 = _noise2(noise, u + prm[P_TWIST] * lr, v)
                    n2 = _noise2(noise, 2.0 * u - 1.7 * prm[P_TWIST] * lr + 0.37, v * 2.3 + 0.21)
                    xr = rp / r_in
                    ft = 0.0
                    if xr > 1.0:
                        ft = xr ** -0.75 * (1.0 - xr ** -0.5) ** 0.25 / F_PEAK
                    ft = max(ft, 0.18 * min(max((rp - r_in * 0.95) / (r_in * 0.05), 0.0), 1.0))
                    temp = prm[P_TMAX] * ft * (1.0 + prm[P_TURB] * (n2 - 0.5))
                    edge_in = min(max((rp - r_in * 0.95) / (r_in * 0.08), 0.0), 1.0)
                    t_out = min(max((r_out - rp) / (r_out * 0.4), 0.0), 1.0)
                    edge_out = t_out * t_out * (3 - 2 * t_out)
                    tau = prm[P_TAU] * (0.25 + 1.5 * n1) * edge_out ** 1.5 * edge_in
                    alpha = 1.0 - math.exp(-tau)
                    if alpha > 1e-4:
                        om = math.sqrt(0.5 / (rp * rp * rp))
                        g = math.sqrt(max(1.0 - 1.5 / rp, 1e-4)) / max(1.0 - om * lam, 1e-3)
                        vl = math.sqrt(vx * vx + vy * vy + vz * vz)
                        mu = abs(vx * nx + vy * ny + vz * nz) / vl
                        limb = (1.0 + 2.06 * mu) / 2.03
                        br, bgr, bbl = _bb(lut, lut_lo, lut_hi, g * temp)
                        w = trans * alpha * prm[P_EMIS] * (0.55 + 0.9 * n1 ** 1.5) * limb
                        er += w * br
                        eg += w * bgr
                        eb += w * bbl
                        trans *= 1.0 - alpha

            x, y, z = qx, qy, qz
            if rq < 1.0:
                shadow = trans
                trans = 0.0
                break
            if trans < 0.002:
                break
            if rq > r_esc and (x * vx + y * vy + z * vz) > 0:
                escaped = True
                break
        out[i, 0] = er
        out[i, 1] = eg
        out[i, 2] = eb
        if escaped and use_bg:
            vl = math.sqrt(vx * vx + vy * vy + vz * vz)
            s = _sample_cube(bg, vx / vl, vy / vl, vz / vl)
            out[i, 3] = trans * s[0]
            out[i, 4] = trans * s[1]
            out[i, 5] = trans * s[2]
        else:
            out[i, 3] = 0.0
            out[i, 4] = 0.0
            out[i, 5] = 0.0
        if not escaped and shadow == 0.0 and trans > 0.002:
            shadow = trans  # orbited the photon sphere until the step budget ran out
        out[i, 6] = shadow


class BlackHoleScene:
    """A black hole seen from `distance`, its disk tilted `inclination` degrees
    towards the camera and rolled `roll` degrees on screen."""

    def __init__(self, distance=22.0, inclination=10.0, roll=-14.0, r_in=3.0, r_out=13.0,
                 background=None, seed=7, t_max=22000.0, opacity=5.0, emission=1.0,
                 turbulence=0.14, twist=0.55, step_k=0.03, max_steps=3000):
        self.obs = np.array([0.0, 0.0, -distance])
        i = math.radians(inclination)
        n = rot(roll, (0, 0, 1)) @ np.array([0.0, math.cos(i), -math.sin(i)])
        self.nrm = normalize(n)
        self.e1 = normalize(np.cross(self.nrm, [0.0, 0.0, 1.0]))
        self.e2 = np.cross(self.nrm, self.e1)
        prm = np.zeros(11)
        prm[P_RIN], prm[P_ROUT] = r_in, r_out
        prm[P_STEPK], prm[P_DTMAX] = step_k, 4.0
        prm[P_RESC] = max(4 * distance, 120.0)
        prm[P_MAXSTEP] = max_steps
        prm[P_TMAX], prm[P_TAU], prm[P_TWIST] = t_max, opacity, twist
        prm[P_EMIS], prm[P_TURB] = emission, turbulence
        self.prm = prm
        self.noise = periodic_noise(512, 2048, seed)
        self.bg = background if background is not None else np.zeros((6, 2, 2, 3))
        self.use_bg = background is not None

    def render(self, dirs, batch=1 << 20):
        """dirs: (..., 3) unit vectors in scene space (camera looks along +z).

        Returns (..., 7): disk RGB, background RGB, shadow coverage."""
        shape = dirs.shape[:-1]
        flat = np.ascontiguousarray(dirs.reshape(-1, 3), dtype=np.float64)
        out = np.zeros((flat.shape[0], 7))
        for s in range(0, flat.shape[0], batch):
            trace(flat[s:s + batch], self.obs, self.nrm, self.e1, self.e2, self.prm,
                  BB_LUT, BB_LO, BB_HI, self.noise, self.bg, self.use_bg, out[s:s + batch])
        return out.reshape(*shape, 7)


# ---------------------------------------------------------------------------
# Optics: glare (bloom) and tone mapping
# ---------------------------------------------------------------------------

GLARE = ((1.2, 0.030), (4.0, 0.018), (14.0, 0.010), (42.0, 0.007))


def glare(img, comps=GLARE, scale=1.0):
    """Lens/eye glare: convolve linear HDR with a sum of Gaussians (sigma in px)."""
    h, w = img.shape[:2]
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    f2 = fy * fy + fx * fx
    kern = sum(wt * np.exp(-2 * math.pi ** 2 * (s * scale) ** 2 * f2) for s, wt in comps)
    total = sum(wt for _, wt in comps)
    spec = np.fft.rfft2(img, axes=(0, 1)) * kern[..., None]
    return img * (1 - total) + np.fft.irfft2(spec, s=(h, w), axes=(0, 1))


def srgb_encode(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def quantize(srgb, dither_seed=None):
    v = srgb * 255.0
    if dither_seed is not None:
        v = v + np.random.default_rng(dither_seed).uniform(-0.5, 0.5, v.shape)
    return np.clip(np.round(v), 0, 255).astype(np.uint8)


def _shoulder(rgb):
    """Film-like highlight roll-off: over-exposed colours bleach towards white."""
    m = rgb.max(-1, keepdims=True)
    over = np.clip(m - 1.0, 0, None)
    base = rgb / np.maximum(m, 1.0)
    k = 1.0 - np.exp(-over * 1.5)
    return base + (1.0 - base) * k


def tonemap_astro(rgb, soft=0.02, white=6.0, dither_seed=None):
    """Asinh stretch (the standard for astrophotography) on luminance."""
    lum = np.maximum(rgb @ LUMA, 1e-9)
    stretched = np.arcsinh(lum / soft) / np.arcsinh(white / soft)
    out = _shoulder(rgb * (stretched / lum)[..., None])
    return quantize(srgb_encode(out), dither_seed)


def tonemap_film(rgb, exposure=1.0, dither_seed=None):
    """Simple filmic curve for daylight scenes."""
    x = 1.0 - np.exp(-np.maximum(rgb, 0) * exposure)
    return quantize(srgb_encode(x), dither_seed)
