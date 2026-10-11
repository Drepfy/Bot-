"""Physically based sky (Nishita single scattering: Rayleigh + Mie + ozone).

Gives the daylight / twilight sky radiance for any sun position, and the
transmittance used to dim and redden the black hole and stars near the horizon.
World axes are Minecraft's: x = east, y = up, z = south. The Minecraft sun
rises due east and sets due west, passing straight overhead.
"""

import math

import numpy as np
from numba import njit, prange

R_EARTH = 6360e3
R_ATMO = 6420e3
H_RAYLEIGH = 8000.0
H_MIE = 1200.0
BETA_R = np.array([5.8e-6, 13.5e-6, 33.1e-6])  # red, green, blue (per metre)
BETA_M = 21e-6
BETA_O3 = np.array([0.650e-6, 1.881e-6, 0.085e-6])  # ozone absorption: keeps twilight blue
OBSERVER_H = 200.0


@njit(inline="always")
def _exit_dist(py, dx, dy, dz, radius):
    # ray from (0, py, 0) along d; distance to leave a sphere of `radius`
    b = py * dy
    c = py * py - radius * radius
    return -b + math.sqrt(max(b * b - c, 0.0))


@njit(inline="always")
def _hits_ground(py, dy):
    b = py * dy
    c = py * py - R_EARTH * R_EARTH
    return b < 0.0 and b * b - c > 0.0


@njit(inline="always")
def _ozone(h):
    # ozone layer: tent profile peaking at 25 km
    return max(0.0, 1.0 - abs(h - 25000.0) / 15000.0)


@njit
def _optical_depth_to_space(px, py, pz, dx, dy, dz, n):
    # returns (rayleigh, mie, ozone) column densities from p along d to the top
    b = px * dx + py * dy + pz * dz
    c = px * px + py * py + pz * pz - R_ATMO * R_ATMO
    t_end = -b + math.sqrt(max(b * b - c, 0.0))
    ds = t_end / n
    dr = 0.0
    dm = 0.0
    do = 0.0
    for i in range(n):
        t = (i + 0.5) * ds
        qx, qy, qz = px + t * dx, py + t * dy, pz + t * dz
        h = math.sqrt(qx * qx + qy * qy + qz * qz) - R_EARTH
        if h < 0.0:
            return 1e12, 1e12, 1e12
        dr += math.exp(-h / H_RAYLEIGH) * ds
        dm += math.exp(-h / H_MIE) * ds
        do += _ozone(h) * ds
    return dr, dm, do


@njit(parallel=True)
def _sky_kernel(dirs, suns, sun_w, beta_r, beta_m, beta_o, mie_g, out_l, out_t):
    py0 = R_EARTH + OBSERVER_H
    n_view, n_light = 32, 8
    for i in prange(dirs.shape[0]):
        dx, dy, dz = dirs[i, 0], dirs[i, 1], dirs[i, 2]
        dy = max(dy, 0.002)  # below the horizon: reuse the horizon haze
        dl = math.sqrt(dx * dx + dy * dy + dz * dz)
        dx, dy, dz = dx / dl, dy / dl, dz / dl
        t_end = _exit_dist(py0, dx, dy, dz, R_ATMO)
        ds = t_end / n_view
        # transmittance of the whole view ray (for objects in space)
        tr_r, tr_m, tr_o = 0.0, 0.0, 0.0
        for k in range(n_view):
            h = math.sqrt(((k + 0.5) * ds * dx) ** 2 + (py0 + (k + 0.5) * ds * dy) ** 2
                          + ((k + 0.5) * ds * dz) ** 2) - R_EARTH
            tr_r += math.exp(-h / H_RAYLEIGH) * ds
            tr_m += math.exp(-h / H_MIE) * ds
            tr_o += _ozone(h) * ds
        for c in range(3):
            out_t[i, c] = math.exp(-(beta_r[c] * tr_r + beta_m * 1.11 * tr_m + beta_o[c] * tr_o))
        lr = np.zeros(3)
        for s in range(suns.shape[0]):
            sx, sy, sz = suns[s, 0], suns[s, 1], suns[s, 2]
            mu = dx * sx + dy * sy + dz * sz
            pr = 3.0 / (16.0 * math.pi) * (1.0 + mu * mu)
            g = mie_g
            pm = 3.0 / (8.0 * math.pi) * ((1 - g * g) * (1 + mu * mu)) / (
                (2 + g * g) * (1 + g * g - 2 * g * mu) ** 1.5)
            od_r, od_m, od_o = 0.0, 0.0, 0.0
            sum_r = np.zeros(3)
            sum_m = np.zeros(3)
            for k in range(n_view):
                t = (k + 0.5) * ds
                px, py, pz = t * dx, py0 + t * dy, t * dz
                h = math.sqrt(px * px + py * py + pz * pz) - R_EARTH
                hr = math.exp(-h / H_RAYLEIGH) * ds
                hm = math.exp(-h / H_MIE) * ds
                ho = _ozone(h) * ds
                od_r += hr * 0.5
                od_m += hm * 0.5
                od_o += ho * 0.5
                lr_, lm_, lo_ = _optical_depth_to_space(px, py, pz, sx, sy, sz, n_light)
                if lr_ < 1e11:
                    for c in range(3):
                        att = math.exp(-(beta_r[c] * (od_r + lr_) + beta_m * 1.11 * (od_m + lm_)
                                         + beta_o[c] * (od_o + lo_)))
                        sum_r[c] += hr * att
                        sum_m[c] += hm * att
                od_r += hr * 0.5
                od_m += hm * 0.5
                od_o += ho * 0.5
            for c in range(3):
                lr[c] += sun_w[s] * (sum_r[c] * beta_r[c] * pr + sum_m[c] * beta_m * pm)
        for c in range(3):
            out_l[i, c] = lr[c]


def sun_direction(elevation_deg, side):
    """side=+1 morning (east), -1 evening (west)."""
    e = math.radians(elevation_deg)
    return np.array([side * math.cos(e), math.sin(e), 0.0])


class SkyModel:
    """Tabulated sky radiance over (elevation, azimuth) for a set of suns."""

    def __init__(self, suns, weights=None, mie_g=0.76, haze=1.0, n_el=96, n_az=192):
        suns = np.asarray(suns, dtype=np.float64).reshape(-1, 3)
        w = np.ones(len(suns)) / len(suns) if weights is None else np.asarray(weights, float)
        self.el = np.linspace(0, 1, n_el) ** 2 * (math.pi / 2)  # dense near the horizon
        self.az = np.linspace(-math.pi, math.pi, n_az)
        e, a = np.meshgrid(self.el, self.az, indexing="ij")
        dirs = np.stack([np.cos(e) * np.sin(a), np.sin(e), np.cos(e) * np.cos(a)], -1).reshape(-1, 3)
        lum = np.zeros((dirs.shape[0], 3))
        trn = np.zeros((dirs.shape[0], 3))
        _sky_kernel(dirs, suns, w, BETA_R, BETA_M * haze, BETA_O3, mie_g, lum, trn)
        self.lum = lum.reshape(n_el, n_az, 3)
        self.trn = trn.reshape(n_el, n_az, 3)

    def _lookup(self, table, dirs):
        el = np.arcsin(np.clip(dirs[..., 1], 0.0, 1.0))
        az = np.arctan2(dirs[..., 0], dirs[..., 2])
        fe = np.sqrt(el / (math.pi / 2)) * (len(self.el) - 1)
        fa = (az + math.pi) / (2 * math.pi) * (len(self.az) - 1)
        ie = np.clip(fe.astype(int), 0, len(self.el) - 2)
        ia = np.clip(fa.astype(int), 0, len(self.az) - 2)
        te = (fe - ie)[..., None]
        ta = (fa - ia)[..., None]
        return ((table[ie, ia] * (1 - ta) + table[ie, ia + 1] * ta) * (1 - te)
                + (table[ie + 1, ia] * (1 - ta) + table[ie + 1, ia + 1] * ta) * te)

    def radiance(self, dirs):
        return self._lookup(self.lum, dirs)

    def transmittance(self, dirs):
        return self._lookup(self.trn, dirs)
