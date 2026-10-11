"""Schwarzschild black hole ray tracer used to paint the Diamond SMP skies.

Units: the Schwarzschild radius is 1. Light rays are traced backwards from the
observer with the classic "pseudo-Newtonian" form of the null geodesic,

    d2x/dl2 = -1.5 * h^2 * x / r^5,      h = |x cross v|

which reproduces the exact Schwarzschild photon orbits (lensing, photon ring,
the shadow). Every ray picks up light from a thin, turbulent, Doppler-beamed
accretion disk, a faint glowing haze around it, and finally the starfield.
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


# ---------------------------------------------------------------------------
# Cube map helpers (used for the background starfield)
# Face order: +x, -x, +y, -y, +z, -z  (OpenGL convention)
# ---------------------------------------------------------------------------


def cube_face_dirs(size, face):
    t = (np.arange(size) + 0.5) / size * 2 - 1
    a, b = np.meshgrid(t, t)  # a across (u), b down (v)
    one = np.ones_like(a)
    if face == 0:
        d = (one, -b, -a)
    elif face == 1:
        d = (-one, -b, a)
    elif face == 2:
        d = (a, one, b)
    elif face == 3:
        d = (a, -one, -b)
    elif face == 4:
        d = (a, -b, one)
    else:
        d = (-a, -b, -one)
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
    fu = (a + 1) * 0.5 * s - 0.5
    fv = (b + 1) * 0.5 * s - 0.5
    fu = min(max(fu, 0.0), s - 1.001)
    fv = min(max(fv, 0.0), s - 1.001)
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
# Starfield background
# ---------------------------------------------------------------------------


@njit(parallel=True)
def _nebula_kernel(dirs, band_n, neb_a, neb_b, seed, out):
    n = dirs.shape[0]
    for i in prange(n):
        x, y, z = dirs[i, 0], dirs[i, 1], dirs[i, 2]
        lat = x * band_n[0] + y * band_n[1] + z * band_n[2]
        band = math.exp(-(lat / 0.22) ** 2)
        wide = math.exp(-(lat / 0.55) ** 2)
        n1 = fbm3(x * 2.2 + 11.0, y * 2.2, z * 2.2, 7, seed)
        n2 = fbm3(x * 3.7, y * 3.7 + 5.0, z * 3.7, 6, seed + 101)
        n3 = fbm3(x * 9.0, y * 9.0, z * 9.0 + 3.0, 5, seed + 333)
        cloud = max(n1 - 0.38, 0.0) * 2.4
        cloud = cloud * cloud * (0.35 + 0.65 * wide)
        dust = max(n3 - 0.45, 0.0) * 3.0  # dark lanes inside the galactic band
        glow = band * (0.5 + 0.8 * n2) * (1.0 - 0.75 * min(dust, 1.0))
        mix = min(max(n2 * 1.6 - 0.3, 0.0), 1.0)
        for c in range(3):
            col = neb_a[c] * (1 - mix) + neb_b[c] * mix
            out[i, c] = col * (cloud * 0.55 + glow * 0.35)


@njit
def _splat_stars(cube, sdirs, scol, ssize):
    s = cube.shape[1]
    for k in range(sdirs.shape[0]):
        face, a, b = _cube_coords(sdirs[k, 0], sdirs[k, 1], sdirs[k, 2])
        fu = (a + 1) * 0.5 * s - 0.5
        fv = (b + 1) * 0.5 * s - 0.5
        sig = ssize[k]
        rad = int(math.ceil(sig * 3.5))
        cu, cv = int(round(fu)), int(round(fv))
        for dv in range(-rad, rad + 1):
            for du in range(-rad, rad + 1):
                u, v = cu + du, cv + dv
                if u < 0 or v < 0 or u >= s or v >= s:
                    continue
                d2 = (u - fu) ** 2 + (v - fv) ** 2
                w = math.exp(-d2 / (2 * sig * sig))
                for c in range(3):
                    cube[face, v, u, c] += scol[k, c] * w


def star_colour(temp):
    """Rough blackbody tint for a star temperature in kelvin (linear RGB)."""
    t = np.clip(temp, 2500, 30000) / 100.0
    hot = np.maximum(t - 60, 1e-6)
    r = np.where(t <= 66, 1.0, np.clip(1.292936 * hot ** -0.1332, 0, 1))
    g = np.where(t <= 66, np.clip(0.390082 * np.log(t) - 0.631841, 0, 1),
                 np.clip(1.129891 * hot ** -0.0755, 0, 1))
    b = np.where(t >= 66, 1.0, np.clip(0.543207 * np.log(np.maximum(t - 10, 1e-6)) - 1.196254, 0, 1))
    rgb = np.stack([r, g, b], -1) ** 2.2  # to linear
    return rgb / rgb.max(axis=-1, keepdims=True)


def make_starfield(size, seed, neb_a, neb_b, band_normal, n_stars=90000, star_gain=1.0):
    rng = np.random.default_rng(seed)
    cube = np.zeros((6, size, size, 3), dtype=np.float64)
    band_n = normalize(band_normal)
    for f in range(6):
        d = cube_face_dirs(size, f).reshape(-1, 3)
        out = np.zeros((d.shape[0], 3))
        _nebula_kernel(d, band_n, np.asarray(neb_a, float), np.asarray(neb_b, float), seed, out)
        cube[f] = out.reshape(size, size, 3)

    # Uniform stars plus a dense population hugging the galactic band.
    n_band = n_stars
    d1 = normalize(rng.standard_normal((n_stars, 3)))
    d2 = normalize(rng.standard_normal((n_band, 3)))
    lat = d2 @ band_n
    d2 = normalize(d2 - np.outer(lat * (1 - rng.uniform(0.0, 0.25, n_band)), band_n))
    dirs = np.concatenate([d1, d2])
    n = dirs.shape[0]
    mag = rng.pareto(1.7, n) + 1.0  # few bright, many faint
    bright = np.clip(0.015 * mag ** 1.6, 0, 6.0) * star_gain
    temp = rng.choice([3200, 4500, 5800, 7500, 10000, 15000, 25000], n,
                      p=[0.12, 0.16, 0.2, 0.18, 0.16, 0.1, 0.08])
    col = star_colour(temp + rng.normal(0, 400, n)) * bright[:, None]
    sizes = np.clip(0.55 + 0.18 * np.log1p(bright * 4), 0.55, 1.6) * size / 1024
    _splat_stars(cube, dirs, col, sizes)
    return cube


# ---------------------------------------------------------------------------
# The ray tracer
# ---------------------------------------------------------------------------

# Indices into the parameter vector handed to the kernel.
P_RIN, P_ROUT, P_STEPK, P_DTMAX, P_RESC, P_MAXSTEP, P_DISKI, P_DISKA, P_TWIST, \
    P_HAZE, P_RING, P_DOPP, P_TEMP, P_TMAXIN, P_HAZET = range(15)


@njit(inline="always")
def _palette(pal, t):
    k = pal.shape[0]
    x = min(max(t, 0.0), 1.0) * (k - 1)
    i = min(int(x), k - 2)
    f = x - i
    return (pal[i, 0] * (1 - f) + pal[i + 1, 0] * f,
            pal[i, 1] * (1 - f) + pal[i + 1, 1] * f,
            pal[i, 2] * (1 - f) + pal[i + 1, 2] * f)


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


@njit(inline="always")
def _doppler(px, py, pz, r, nx, ny, nz, kx, ky, kz):
    """Redshift factor g for disk gas orbiting the normal n, seen along k."""
    wx, wy, wz = ny * pz - nz * py, nz * px - nx * pz, nx * py - ny * px
    wl = math.sqrt(wx * wx + wy * wy + wz * wz) + 1e-12
    beta = math.sqrt(0.5 / max(r - 1.0, 0.5))
    beta = min(beta, 0.9)
    cos_t = (wx * kx + wy * ky + wz * kz) / wl
    gam = 1.0 / math.sqrt(1 - beta * beta)
    return math.sqrt(max(1 - 1.0 / r, 0.0)) / (gam * (1 - beta * cos_t))


@njit(parallel=True, fastmath=True)
def trace(dirs, obs, nrm, e1, e2, prm, pal, noise, bg, use_bg, out):
    """Trace each direction in `dirs` from `obs`; writes RGB + shadow coverage."""
    r_in, r_out = prm[P_RIN], prm[P_ROUT]
    step_k, dt_max, r_esc = prm[P_STEPK], prm[P_DTMAX], prm[P_RESC]
    max_steps = int(prm[P_MAXSTEP])
    lr_in, lr_out = math.log(r_in), math.log(r_out)
    nx, ny, nz = nrm[0], nrm[1], nrm[2]
    for i in prange(dirs.shape[0]):
        x, y, z = obs[0], obs[1], obs[2]
        vx, vy, vz = dirs[i, 0], dirs[i, 1], dirs[i, 2]
        cx, cy, cz = y * vz - z * vy, z * vx - x * vz, x * vy - y * vx
        h2 = cx * cx + cy * cy + cz * cz
        trans = 1.0
        cr, cg, cb = 0.0, 0.0, 0.0
        shadow = 0.0
        for _ in range(max_steps):
            r = math.sqrt(x * x + y * y + z * z)
            dt = min(step_k * r * (0.6 + 0.4 * min(r / 3.0, 1.0)), dt_max)
            # RK4
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

            vl = math.sqrt(vx * vx + vy * vy + vz * vz)
            kx, ky, kz = -vx / vl, -vy / vl, -vz / vl  # photon heading to the camera
            rq = math.sqrt(qx * qx + qy * qy + qz * qz)

            # --- volumetric haze around the disk and the photon sphere ---
            hgt = qx * nx + qy * ny + qz * nz
            if prm[P_HAZE] > 0 and rq > 1.0 and rq < r_out * 1.6:
                thick = 0.10 * rq + 0.15
                rr = rq / r_in
                prof = rr ** -2.0 * (1 - 1 / math.sqrt(max(rr, 1.0))) * 4.0 + 0.04 * math.exp(-rq / r_out)
                haze = prm[P_HAZE] * prof * math.exp(-(hgt / thick) ** 2)
                if haze > 1e-5:
                    g = _doppler(qx, qy, qz, max(rq, 1.01), nx, ny, nz, kx, ky, kz)
                    pr, pg, pb = _palette(pal, prm[P_HAZET] * g)
                    w = trans * haze * dt * g ** 2
                    cr += w * pr
                    cg += w * pg
                    cb += w * pb

            # --- thin disk crossing ---
            s0 = x * nx + y * ny + z * nz
            s1 = hgt
            if s0 * s1 < 0.0:
                f = s0 / (s0 - s1)
                px, py, pz = x + f * (qx - x), y + f * (qy - y), z + f * (qz - z)
                rp = math.sqrt(px * px + py * py + pz * pz)
                if rp > r_in * 0.92 and rp < r_out:
                    phi = math.atan2(px * e2[0] + py * e2[1] + pz * e2[2],
                                     px * e1[0] + py * e1[1] + pz * e1[2])
                    lr = math.log(rp)
                    v = (lr - lr_in) / (lr_out - lr_in)
                    u = phi / (2 * math.pi)
                    n1 = _noise2(noise, u + prm[P_TWIST] * lr, v)
                    n2 = _noise2(noise, 2.0 * u - 1.7 * prm[P_TWIST] * lr + 0.37, v * 2.3 + 0.21)
                    turb = 0.25 + 1.25 * n1 ** 1.6 * (0.55 + 0.9 * n2)
                    xr = rp / r_in
                    prof = (1.0 - 1.0 / math.sqrt(max(xr, 1.0))) * xr ** -2.2 * 9.5 + 0.03
                    edge_in = min(max((rp - r_in * 0.92) / (r_in * 0.12), 0.0), 1.0)
                    t_out = min(max((r_out - rp) / (r_out * 0.45), 0.0), 1.0)
                    edge_out = t_out * t_out * (3 - 2 * t_out)
                    dens = prof * turb * edge_in * edge_out
                    alpha = 1.0 - math.exp(-prm[P_DISKA] * dens * (0.6 + 0.4 * edge_out))
                    g = _doppler(px, py, pz, rp, nx, ny, nz, kx, ky, kz)
                    temp = prm[P_TEMP] * (prof ** 0.28) * (0.75 + 0.45 * n2) * g
                    temp = min(temp, prm[P_TMAXIN] + 0.4)
                    pr, pg, pb = _palette(pal, temp)
                    inten = prm[P_DISKI] * (0.25 + dens) * g ** prm[P_DOPP]
                    w = trans * alpha * inten
                    cr += w * pr
                    cg += w * pg
                    cb += w * pb
                    trans *= 1.0 - alpha

            x, y, z = qx, qy, qz
            if rq < 1.0:
                shadow = trans
                trans = 0.0
                break
            if trans < 0.003:
                break
            if rq > r_esc and (x * vx + y * vy + z * vz) > 0:
                break
        else:
            shadow = trans  # spiralled forever around the photon sphere
            trans = 0.0
        if trans > 0.0 and prm[P_RING] > 0:
            # Photon ring: light skimming the photon sphere (impact parameter
            # just above the critical 3*sqrt(3)/2) piles up into a thin halo.
            db = math.sqrt(h2) - 2.598
            if db > 0.0:
                ring = prm[P_RING] * (math.exp(-db / 0.05) + 0.2 * math.exp(-db / 0.4))
                pr, pg, pb = _palette(pal, 0.74)
                cr += trans * ring * pr
                cg += trans * ring * pg
                cb += trans * ring * pb
        if trans > 0.0 and use_bg:
            vl = math.sqrt(vx * vx + vy * vy + vz * vz)
            s = _sample_cube(bg, vx / vl, vy / vl, vz / vl)
            cr += trans * s[0]
            cg += trans * s[1]
            cb += trans * s[2]
        out[i, 0] = cr
        out[i, 1] = cg
        out[i, 2] = cb
        out[i, 3] = shadow


class BlackHoleScene:
    """A black hole seen from `distance`, with its disk tilted `inclination`
    degrees towards the camera and rolled `roll` degrees on screen."""

    def __init__(self, palette, distance=26.0, inclination=8.0, roll=-12.0,
                 r_in=3.0, r_out=13.0, background=None, seed=7, **kw):
        self.obs = np.array([0.0, 0.0, -distance])
        i = math.radians(inclination)
        n = np.array([0.0, math.cos(i), -math.sin(i)])
        n = rot(roll, (0, 0, 1)) @ n
        self.nrm = normalize(n)
        e1 = np.cross(self.nrm, [0.0, 0.0, 1.0])
        if np.linalg.norm(e1) < 1e-6:
            e1 = np.cross(self.nrm, [1.0, 0.0, 0.0])
        self.e1 = normalize(e1)
        self.e2 = np.cross(self.nrm, self.e1)
        prm = np.zeros(15)
        prm[P_RIN], prm[P_ROUT] = r_in, r_out
        prm[P_STEPK] = kw.get("step_k", 0.035)
        prm[P_DTMAX] = kw.get("dt_max", 4.0)
        prm[P_RESC] = kw.get("r_esc", max(4 * distance, 120.0))
        prm[P_MAXSTEP] = kw.get("max_steps", 3000)
        prm[P_DISKI] = kw.get("disk_intensity", 1.6)
        prm[P_DISKA] = kw.get("disk_opacity", 2.2)
        prm[P_TWIST] = kw.get("twist", 0.55)
        prm[P_HAZE] = kw.get("haze", 0.05)
        prm[P_RING] = kw.get("ring", 0.35)
        prm[P_DOPP] = kw.get("doppler_power", 3.0)
        prm[P_TEMP] = kw.get("temperature", 0.92)
        prm[P_TMAXIN] = kw.get("temp_max", 1.0)
        prm[P_HAZET] = kw.get("haze_temp", 0.55)
        self.prm = prm
        self.pal = np.ascontiguousarray(palette, dtype=np.float64)
        self.noise = periodic_noise(512, 2048, seed)
        self.bg = background if background is not None else np.zeros((6, 2, 2, 3))
        self.use_bg = background is not None

    def render(self, dirs, batch=1 << 20):
        """dirs: (..., 3) unit vectors in scene space (camera looks along +z)."""
        shape = dirs.shape[:-1]
        flat = np.ascontiguousarray(dirs.reshape(-1, 3), dtype=np.float64)
        out = np.zeros((flat.shape[0], 4))
        for s in range(0, flat.shape[0], batch):
            trace(flat[s:s + batch], self.obs, self.nrm, self.e1, self.e2, self.prm,
                  self.pal, self.noise, self.bg, self.use_bg, out[s:s + batch])
        return out.reshape(*shape, 4)


def world_to_scene(target_dir, up=(0.0, 1.0, 0.0)):
    """Rotation that maps world directions so that `target_dir` becomes +z."""
    f = normalize(target_dir)
    r = normalize(np.cross(f, up))
    u = np.cross(r, f)
    # scene basis: forward (0,0,1), up (0,1,0), right = f x u = (-1,0,0)
    return np.stack([-r, u, f])  # rows: scene x, y, z expressed in world coords


def tonemap(rgb, exposure=1.0, dither_seed=None):
    """Filmic-ish tonemap from linear HDR to 8-bit sRGB."""
    x = 1.0 - np.exp(-np.maximum(rgb, 0) * exposure)
    srgb = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    srgb = srgb * 255.0
    if dither_seed is not None:
        srgb += np.random.default_rng(dither_seed).uniform(-0.5, 0.5, srgb.shape)
    return np.clip(np.round(srgb), 0, 255).astype(np.uint8)
