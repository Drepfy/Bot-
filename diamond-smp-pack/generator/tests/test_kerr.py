"""Tests for kerr.py: the exact Kerr (spinning) black hole renderer.

Run from the generator folder:  python3 -m pytest -q -s tests/test_kerr.py
(-s prints the measured numbers: shadow errors, constraint drift, rays/s.)

Units: G = c = M = 1 (the Schwarzschild radius is 2).
"""

import math
import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blackhole as bh  # noqa: E402
import kerr  # noqa: E402

D = 44.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def camera_dirs(w, h, half_tan_x):
    """The build's pinhole camera (build_pack.camera_dirs): looks along +z, screen-right is -x."""
    xs = ((np.arange(w) + 0.5) / w * 2 - 1) * half_tan_x
    ys = ((np.arange(h) + 0.5) / h * 2 - 1) * half_tan_x * h / w
    a, b = np.meshgrid(xs, ys)
    return bh.normalize(np.stack([-a, -b, np.ones_like(a)], -1))


def tangent_dirs(x, y):
    """Scene directions through the point (x, y) of the tangent plane z = 1."""
    x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
    return bh.normalize(np.stack([x, y, np.ones_like(x)], -1))


def captured(scene, d):
    """True where the ray falls into the hole (status 2) or orbits until the budget ends (3)."""
    st = scene.trace_info(d)[1][..., 3]
    return (st == 2) | (st == 3)


def bisect_edge(scene, cx, cy, px, py, lo, hi, roll=0.0, iters=40):
    """t at which the ray through C + t (P - C) (tangent plane, un-rolled screen) leaves the shadow."""
    m = bh.rot(roll, (0, 0, 1))
    px, py = np.broadcast_arrays(np.asarray(px, float), np.asarray(py, float))
    lo, hi = np.full(px.shape, lo), np.full(px.shape, hi)

    def cap(t):
        return captured(scene, tangent_dirs(cx + t * (px - cx), cy + t * (py - cy)) @ m.T)

    assert cap(lo).all(), "inner bracket is not inside the shadow"
    assert not cap(hi).any(), "outer bracket is not outside the shadow"
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        c = cap(mid)
        lo, hi = np.where(c, mid, lo), np.where(c, hi, mid)
    return 0.5 * (lo + hi)


def angle_between(u, v):
    return np.arccos(np.clip((bh.normalize(u) * bh.normalize(v)).sum(-1), -1.0, 1.0))


def bardeen_curve(a, theta_o, n=4001):
    """Analytic critical curve (Bardeen 1973): impact parameters (alpha, beta) of the rays
    asymptotic to the spherical photon orbits r in [r_ph+, r_ph-]; beta >= 0 half."""
    r_pro = 2.0 * (1.0 + math.cos(2.0 / 3.0 * math.acos(-a)))
    r_ret = 2.0 * (1.0 + math.cos(2.0 / 3.0 * math.acos(a)))
    r = np.linspace(r_pro, r_ret, n)
    xi = (r * r * (3.0 - r) - a * a * (r + 1.0)) / (a * (r - 1.0))
    eta = r ** 3 * (4.0 * a * a - r * (r - 3.0) ** 2) / (a * a * (r - 1.0) ** 2)
    beta2 = eta + a * a * math.cos(theta_o) ** 2 - xi ** 2 / math.tan(theta_o) ** 2
    ok = beta2 >= 0.0
    return -xi[ok] / math.sin(theta_o), np.sqrt(beta2[ok])


def bardeen_to_tangent(alpha, beta, dist, lapse=True):
    """Impact parameters -> un-rolled screen tangent coordinates (alpha -> screen-right = -x,
    beta -> up = +y). sin(angle) = rho / D, times the static observer's sqrt(1 - 2M/D)
    aberration factor if `lapse` (exact for Schwarzschild)."""
    rho = np.hypot(alpha, beta)
    s = rho / dist * (math.sqrt(1.0 - 2.0 / dist) if lapse else 1.0)
    t = np.tan(np.arcsin(s)) if lapse else np.tan(rho / dist)
    return -t * alpha / rho, t * beta / rho


@pytest.fixture(scope="module")
def schw():
    return kerr.KerrScene(spin=0.0, distance=D, inclination=10.0, roll=-14.0, opacity=0.0)


@pytest.fixture(scope="module")
def kerr09():
    return kerr.KerrScene(spin=0.9, distance=D, inclination=10.0, roll=0.0, opacity=0.0)


# ---------------------------------------------------------------------------
# Kerr geometry
# ---------------------------------------------------------------------------


def test_horizon_isco_and_photon_orbits():
    assert kerr.horizon_radius(0.0) == pytest.approx(2.0)
    assert kerr.horizon_radius(0.9) == pytest.approx(1.0 + math.sqrt(0.19))
    assert kerr.isco_radius(0.0) == pytest.approx(6.0, abs=1e-12)
    assert kerr.isco_radius(0.9) == pytest.approx(2.3209, abs=5e-5)
    assert kerr.isco_radius(0.9) == pytest.approx(2.320883043, abs=1e-8)
    assert kerr.isco_radius(-0.9) == pytest.approx(8.717352279, abs=1e-8)   # retrograde
    assert kerr.isco_radius(0.9999) < 1.2
    pro, ret = kerr.photon_orbit_radii(0.9)
    # circular photon orbits: E, L of circular orbits diverge where r^1.5 - 3 r^0.5 +- 2a = 0
    assert pro ** 1.5 - 3 * pro ** 0.5 + 1.8 == pytest.approx(0.0, abs=1e-12)
    assert ret ** 1.5 - 3 * ret ** 0.5 - 1.8 == pytest.approx(0.0, abs=1e-12)
    assert 1.5 < pro < 1.6 and 3.9 < ret < 3.92
    assert kerr.photon_orbit_radii(0.0) == pytest.approx((3.0, 3.0))


@pytest.mark.parametrize("a", [0.0, 0.5, 0.9, -0.7])
def test_isco_is_the_energy_minimum_of_circular_orbits(a):
    """The ISCO is where E(r) and L(r) of circular orbits are stationary (dE/dr = 0)."""
    r_isco = kerr.isco_radius(a)
    r = np.linspace(r_isco * 0.9, r_isco * 1.2, 200001)
    with np.errstate(invalid="ignore"):
        e, l, om, ut = kerr.circular_orbit(r, a)
    assert r[np.nanargmin(e)] == pytest.approx(r_isco, rel=2e-4)
    assert r[np.nanargmin(l)] == pytest.approx(r_isco, rel=2e-4)   # L(r) > 0 for +phi orbits
    rr = np.array([r_isco * 1.01, 10.0, 30.0])
    e, l, om, ut = kerr.circular_orbit(rr, a)
    # -u_t = E and u_phi = L with u^phi = Omega u^t (Kerr metric at the equator)
    g_tt = -(1.0 - 2.0 / rr)
    g_tp = -2.0 * a / rr
    g_pp = rr * rr + a * a + 2.0 * a * a / rr
    u_t = g_tt * ut + g_tp * om * ut
    u_p = g_tp * ut + g_pp * om * ut
    assert np.allclose(-u_t, e, rtol=1e-12)
    assert np.allclose(u_p, l, rtol=1e-12)
    # timelike normalisation g_mn u^m u^n = -1
    norm = g_tt * ut ** 2 + 2 * g_tp * ut * (om * ut) + g_pp * (om * ut) ** 2
    assert np.allclose(norm, -1.0, rtol=1e-12)


def page_thorne_closed_form(r, a):
    """Page & Thorne (1974) analytic flux, F * 4 pi / Mdot (independent reference)."""
    x = np.sqrt(r)
    x0 = math.sqrt(kerr.isco_radius(a))
    ac = math.acos(a)
    x1, x2, x3 = 2 * math.cos((ac - math.pi) / 3), 2 * math.cos((ac + math.pi) / 3), -2 * math.cos(ac / 3)
    br = (x - x0 - 1.5 * a * np.log(x / x0)
          - 3 * (x1 - a) ** 2 / (x1 * (x1 - x2) * (x1 - x3)) * np.log((x - x1) / (x0 - x1))
          - 3 * (x2 - a) ** 2 / (x2 * (x2 - x1) * (x2 - x3)) * np.log((x - x2) / (x0 - x2))
          - 3 * (x3 - a) ** 2 / (x3 * (x3 - x1) * (x3 - x2)) * np.log((x - x3) / (x0 - x3)))
    return 1.5 / (x * x * (x ** 3 - 3 * x + 2 * a)) * br / r


@pytest.mark.parametrize("a", [0.9, 0.5, 1e-4, -0.5])
def test_page_thorne_flux_matches_closed_form(a):
    r = np.geomspace(kerr.isco_radius(a) * 1.001, 60.0, 400)
    num = kerr.page_thorne_flux(r, a)
    ref = page_thorne_closed_form(r, a)
    dev = np.abs(num / ref - 1.0).max()
    print(f"\n  Page-Thorne a={a}: max rel deviation numerical vs closed form {dev:.2e}")
    assert dev < 1e-5
    assert kerr.page_thorne_flux(np.array([kerr.isco_radius(a) * 0.99]), a)[0] == 0.0


def test_temperature_table_peak_and_shape():
    for a in (0.0, 0.9):
        t, lo, hi = kerr.temperature_table(a, 26.0)
        assert t.max() == pytest.approx(1.0)
        assert lo == pytest.approx(math.log(kerr.isco_radius(a)))
        rr = np.exp(np.linspace(lo, hi, len(t)))
        f = kerr.page_thorne_flux(rr, a)
        assert np.allclose(t, (f / f.max()) ** 0.25, atol=1e-12)
    # The relativistic Page-Thorne flux peaks further out than the Newtonian-style profile
    # r^-3 (1 - sqrt(r_in/r)) of BlackHoleScene (49/36 r_isco = 8.17 M at spin 0):
    # 9.551 M at spin 0 and 3.435 M at spin 0.9 (closed-form values).
    for a, r_peak in ((0.0, 9.55096), (0.9, 3.435)):
        t, lo, hi = kerr.temperature_table(a, 26.0)
        rr = np.exp(np.linspace(lo, hi, len(t)))
        assert rr[np.argmax(t)] == pytest.approx(r_peak, rel=2e-3)
    # far from the hole T falls off like r^-3/4
    t, lo, hi = kerr.temperature_table(0.0, 2000.0)
    rr = np.exp(np.linspace(lo, hi, len(t)))
    slope = np.gradient(np.log(t[-50:]), np.log(rr[-50:]))
    assert slope[-1] == pytest.approx(-0.75, abs=0.02)


# ---------------------------------------------------------------------------
# Camera mapping and orientation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a", [0.0, 0.9])
def test_camera_constants_satisfy_null_condition(a):
    """b, q and the initial momenta from James et al. A9-A11 make p a null covector."""
    rng = np.random.default_rng(1)
    n = bh.normalize(rng.standard_normal((2000, 3)))
    r, th = D, math.radians(80.0)
    b, q, e, vr, vth = kerr.ray_constants(n[:, 0], n[:, 1], n[:, 2], r, th, a)
    s, c = math.sin(th), math.cos(th)
    dl = r * r - 2 * r + a * a
    big_r = (r * r + a * a - a * b) ** 2 - dl * ((b - a) ** 2 + q)
    big_th = q + a * a * c * c - b * b * c * c / (s * s)
    h = 0.5 * ((vr ** 2 - big_r) / dl + vth ** 2 - big_th) / (r * r + a * a * c * c)
    assert np.abs(h).max() < 1e-9 * (1 + np.abs(big_r / dl).max())
    if a == 0.0:  # static camera: total impact parameter^2 = D^2 sin^2(psi) / (1 - 2/D)
        sin2 = 1.0 - n[:, 0] ** 2
        assert np.allclose(b * b + q, r * r * sin2 / (1 - 2 / r), rtol=1e-10, atol=1e-9)


@pytest.mark.parametrize("spin", [0.0, 0.9])
def test_far_rays_escape_along_their_launch_direction(spin):
    """Rays aimed away from the hole leave in (almost) the launch direction, bent slightly
    towards the hole (weak-field 2M/D tan(psi/2)); a mirrored camera would fail this."""
    sc = kerr.KerrScene(spin=spin, distance=D, roll=-14.0, opacity=0.0)
    psi = np.radians(np.array([0.0, 10, 30, 60, 90, 120, 150]))   # angle from the outward radial
    phis = np.radians(np.array([0.0, 45, 90, 135, 200, 300]))
    P, F = np.meshgrid(psi, phis)
    d = np.stack([np.sin(P) * np.cos(F), np.sin(P) * np.sin(F), -np.cos(P)], -1)
    out, g = sc.trace_info(d)
    assert (g[..., 3] == 1).all()
    esc = g[..., :3]
    defl = angle_between(esc, d)
    pred = 2.0 / D * np.tan(P / 2)
    print(f"\n  spin {spin}: deflection / weak-field prediction = "
          f"{np.array2string((defl / np.maximum(pred, 1e-30))[0, 1:], precision=3)}, radial ray {defl[:, 0].max():.1e}")
    assert (defl < 1.25 * pred + 1e-3).all()
    assert (defl[:, 1:] > 0.8 * pred[:, 1:]).all()
    assert (esc[..., 2] - d[..., 2] > -1e-12).all()   # bent towards the hole (+z)
    # explicit screen directions: right (-x), left (+x), up (+y), down (-y), backwards (-z)
    m = bh.rot(-14.0, (0, 0, 1))
    probes = np.array([[-1.0, 0, 0], [1.0, 0, 0], [0, 1.0, 0], [0, -1.0, 0], [0, 0, -1.0]]) @ m.T
    e = sc.trace_info(probes)[1][:, :3]
    assert ((e * probes).sum(-1) > 0.99).all()


def test_weak_field_deflection_with_frame_dragging():
    """Equatorial rays from a very distant camera: the total bending matches the Kerr
    weak-field series 4/b + 15 pi/4 b^-2 -+ 4a b^-2 + 128/3 b^-3 -+ 10 pi a b^-3 + 4 a^2 b^-3
    (upper sign prograde), so prograde rays are bent less (frame dragging)."""
    dist = 1e6
    for a in (0.0, 0.9):
        sc = kerr.KerrScene(spin=a, distance=dist, inclination=0.0, roll=0.0, opacity=0.0)
        for b_imp in (100.0, 200.0, 400.0):
            psi = b_imp / dist
            d = np.array([[math.sin(psi), 0, math.cos(psi)], [-math.sin(psi), 0, math.cos(psi)]])
            _, g = sc.trace_info(d)
            assert (g[:, 3] == 1).all()
            defl = angle_between(g[:, :3], d)
            b = g[:, 8]
            assert b[0] > 0 > b[1]       # screen-left (+x) rays co-rotate with the hole
            bb, s = np.abs(b), np.sign(b)
            pred = (4 / bb + 15 * math.pi / 4 / bb ** 2 - 4 * s * a / bb ** 2
                    + 128 / 3 / bb ** 3 - 10 * math.pi * s * a / bb ** 3 + 4 * a * a / bb ** 3)
            print(f"\n  a={a} b=+-{b_imp:.0f}: deflection {defl[0]:.9f} / {defl[1]:.9f}, "
                  f"series {pred[0]:.9f} / {pred[1]:.9f}")
            assert np.abs(defl - pred).max() < 1e-5
            if a > 0:
                asym = defl[1] - defl[0]
                asym_pred = 8 * a / b_imp ** 2 + 20 * math.pi * a / b_imp ** 3
                assert asym == pytest.approx(asym_pred, rel=0.03)


def test_roll_rotates_the_picture():
    """Rolled scene seen through rot(roll) @ d == un-rolled scene seen through d."""
    d = camera_dirs(96, 96, math.tan(math.radians(30)))
    m = bh.rot(-14.0, (0, 0, 1))
    a = kerr.KerrScene(spin=0.9, roll=-14.0).render(d @ m.T)
    b = kerr.KerrScene(spin=0.9, roll=0.0).render(d)
    la, lb = a[..., :3] @ bh.LUMA, b[..., :3] @ bh.LUMA
    bad = np.abs(la - lb) > 1e-6 * (1 + lb)
    assert bad.mean() < 2e-3
    assert np.abs(a[..., 6] - b[..., 6]).mean() < 1e-3
    # disk normal (spin axis) in the scene frame, exactly like BlackHoleScene.nrm
    for roll in (0.0, -14.0, 22.0):
        k = kerr.KerrScene(spin=0.9, inclination=17.0, roll=roll)
        s = bh.BlackHoleScene(inclination=17.0, roll=roll)
        assert np.allclose(k.nrm, s.nrm, atol=1e-12)


def test_polar_rays_are_continuous():
    """Rays through (or very near) the spin axis: b -> 0 is smooth, no stalls or jumps."""
    for spin in (0.9, 0.0):
        sc = kerr.KerrScene(spin=spin, roll=0.0, opacity=0.0)
        for dy in (0.2, 0.35, -0.3):
            dx = np.array([-1e-4, -1e-6, -1e-9, 0.0, 1e-9, 1e-6, 1e-4])
            _, g = sc.trace_info(tangent_dirs(dx, np.full_like(dx, dy)))
            assert (g[:, 3] == 1).all(), (spin, dy, g[:, 3])
            assert g[:, 4].max() < 400
            e = g[:, :3]
            jump = angle_between(e[1:], e[:-1])
            assert jump[1:-1].max() < 1e-5, (spin, dy, jump)
            assert jump.max() < 2e-3


# ---------------------------------------------------------------------------
# Shadows
# ---------------------------------------------------------------------------


def test_spin0_shadow_radius(schw):
    chi = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    t = bisect_edge(schw, 0.0, 0.0, 0.2 * np.cos(chi), 0.2 * np.sin(chi), 0.3, 0.8)
    ang = np.arctan(0.2 * t)
    exact = math.asin(3 * math.sqrt(3) / D * math.sqrt(1 - 2 / D))
    err = np.abs(ang / exact - 1).max()
    print(f"\n  spin 0 shadow angular radius {math.degrees(ang.mean()):.5f} deg, exact "
          f"{math.degrees(exact):.5f} deg, max rel err {err:.2e}")
    assert err < 0.01
    assert err < 1e-5     # the integrator is in fact far more accurate than the 1% asked for


@pytest.mark.parametrize("incl,roll", [(10.0, 0.0), (10.0, -14.0), (60.0, 0.0)])
def test_spin09_shadow_matches_bardeen_curve(incl, roll):
    a = 0.9
    sc = kerr.KerrScene(spin=a, distance=D, inclination=incl, roll=roll, opacity=0.0)
    al, be = bardeen_curve(a, math.radians(90.0 - incl))
    xs, ys = bardeen_to_tangent(np.concatenate([al, al[::-1]]), np.concatenate([be, -be[::-1]]), D)
    cx, cy = xs.mean(), ys.mean()
    sel = np.linspace(0, len(xs) - 1, 64).astype(int)
    px, py = xs[sel], ys[sel]
    t = bisect_edge(sc, cx, cy, px, py, 0.85, 1.15, roll=roll)
    rad = np.hypot(px - cx, py - cy)
    err = np.abs(t - 1) * rad / rad.mean()
    # the same curve converted with plain alpha/D, beta/D angles (what "~2%" refers to)
    xs0, ys0 = bardeen_to_tangent(np.concatenate([al, al[::-1]]), np.concatenate([be, -be[::-1]]), D, lapse=False)
    t0 = bisect_edge(sc, cx, cy, xs0[sel], ys0[sel], 0.85, 1.15, roll=roll)
    rad0 = np.hypot(xs0[sel] - cx, ys0[sel] - cy)
    plain = (np.abs(t0 - 1) * rad0 / rad0.mean()).max()
    # exact finite-distance edge (inverse camera map of the photon-orbit constants)
    ex = kerr.shadow_edge_directions(a, D, incl, n=181)
    ex = ex[np.linspace(0, len(ex) - 1, 40).astype(int)]
    exx, exy = ex[:, 0] / ex[:, 2], ex[:, 1] / ex[:, 2]
    te = bisect_edge(sc, cx, cy, exx, exy, 0.9, 1.1, roll=roll)
    print(f"\n  spin 0.9 incl {incl} roll {roll}: edge vs Bardeen (lapse-corrected angles) max "
          f"{err.max() * 100:.3f}% mean {err.mean() * 100:.3f}%; plain alpha/D conversion differs by "
          f"{plain * 100:.2f}%; vs exact finite-distance edge max {np.abs(te - 1).max():.1e}")
    assert err.max() < 0.01
    assert plain < 0.03
    assert np.abs(te - 1).max() < 1e-5


def test_spin09_shadow_is_shifted_and_flattened_on_the_approaching_side(kerr09):
    """Screen-left (+x) is where the disk gas and the prograde photons come towards us."""
    t = bisect_edge(kerr09, 0.0, 0.0, np.array([0.3, -0.3]), np.array([0.0, 0.0]), 0.05, 0.95)
    x_left, x_right = 0.3 * t[0], -0.3 * t[1]
    top = 0.3 * bisect_edge(kerr09, -0.04, 0.0, np.array([-0.04]), np.array([0.3]), 0.05, 0.95)[0]
    x0 = 0.5 * (x_left + x_right)
    # horizontal edge positions at heights 0 and 0.6 * top on both sides
    h = np.array([0.0, 0.6 * top, -0.6 * top])
    lefts = np.array([x0 + 0.3 * bisect_edge(kerr09, x0, y, np.array([x0 + 0.3]), np.array([y]), 0.05, 0.95)[0]
                      for y in h])
    rights = np.array([x0 - 0.3 * bisect_edge(kerr09, x0, y, np.array([x0 - 0.3]), np.array([y]), 0.05, 0.95)[0]
                       for y in h])
    bulge_left = (lefts[0] - lefts[1:].mean()) / top
    bulge_right = (rights[1:].mean() - rights[0]) / top
    print(f"\n  spin 0.9 shadow: left edge {x_left:.4f}, right edge {x_right:.4f} (tangent units), "
          f"centre shift {x0:+.4f}; edge bulge over +-0.6 height: left {bulge_left:.3f} right {bulge_right:.3f}")
    assert x_left > 0 > x_right
    assert x_left < 0.6 * -x_right          # shadow displaced away from the approaching side
    # and flattened there: a circle gives 0.2 on both sides; analytic Bardeen curve (D = 44,
    # theta_o = 80 deg, lapse-corrected angles): left 0.1607, right 0.1950
    assert bulge_left < 0.85 * bulge_right
    assert bulge_left == pytest.approx(0.1607, abs=0.003)
    assert bulge_right == pytest.approx(0.1950, abs=0.003)


# ---------------------------------------------------------------------------
# Integration accuracy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spin", [0.9, 0.0])
def test_hamiltonian_constraint_is_conserved(spin):
    sc = kerr.KerrScene(spin=spin)
    rng = np.random.default_rng(3)
    d = np.concatenate([camera_dirs(128, 128, math.tan(math.radians(35))).reshape(-1, 3),
                        bh.normalize(rng.standard_normal((8000, 3)))])
    _, g = sc.trace_info(d)
    st, hmax, cmax = g[:, 3], g[:, 5], g[:, 10]
    esc, cap = st == 1, st == 2
    print(f"\n  spin {spin}: max |H| escaped {hmax[esc].max():.2e} (median {np.median(hmax[esc]):.1e}), "
          f"captured {hmax[cap].max():.2e}; max |p_theta^2 - Theta| / scale {cmax.max():.2e}; "
          f"steps mean {g[:, 4].mean():.1f} max {g[:, 4].max():.0f}; status counts "
          f"{dict(zip(*np.unique(st, return_counts=True)))}")
    assert hmax[esc].max() < 1e-5
    assert hmax.max() < 1e-4
    assert cmax.max() < 1e-5
    assert (st != 3).mean() > 0.999


# ---------------------------------------------------------------------------
# Disk physics
# ---------------------------------------------------------------------------


def binet_hit_radius(psi, dist, theta_o, n=40000):
    """Schwarzschild: radius where a ray from a static camera on the axis, launched psi from
    the hole, meets the equatorial plane (u'' = 3u^2 - u, independent of kerr.py)."""
    b = dist * math.sin(psi) / math.sqrt(1 - 2 / dist)
    u, du = 1.0 / dist, math.sqrt(1 / b ** 2 - (1 - 2 / dist) / dist ** 2)
    phi_end = 0.5 * math.pi - theta_o
    h = phi_end / n

    def f(u, du):
        return du, 3 * u * u - u

    for _ in range(n):
        k1 = f(u, du)
        k2 = f(u + 0.5 * h * k1[0], du + 0.5 * h * k1[1])
        k3 = f(u + 0.5 * h * k2[0], du + 0.5 * h * k2[1])
        k4 = f(u + h * k3[0], du + h * k3[1])
        u += h / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
        du += h / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
    return 1.0 / u


@pytest.mark.parametrize("dist", [44.0, 1e5])
def test_face_on_redshift_spin0(dist):
    """Face-on disk, spin 0: g = sqrt(1 - 3/r) for an observer at infinity (transverse Doppler
    + gravitational redshift); the static camera at D adds its own 1/sqrt(1 - 2/D) blueshift."""
    sc = kerr.KerrScene(spin=0.0, distance=dist, inclination=90.0, roll=0.0, opacity=1.0)
    psi = np.linspace(7.5, 24.0, 12) / dist          # aim at r ~ 7 .. 24 M
    d = np.stack([np.zeros_like(psi), -np.sin(psi), np.cos(psi)], -1)
    _, g = sc.trace_info(d)
    r, gg = g[:, 6], g[:, 7]
    assert (r > kerr.isco_radius(0.0)).all() and (r < 26).all()
    assert np.abs(g[:, 8]).max() == 0.0                       # b = 0: purely transverse motion
    g_inf = gg * math.sqrt(1 - 2 / dist)
    err = np.abs(g_inf - np.sqrt(1 - 3 / r)).max()
    r_ref = np.array([binet_hit_radius(p, dist, sc.theta_o) for p in psi])
    rerr = np.abs(r / r_ref - 1).max()
    print(f"\n  D={dist:g}: r {r.min():.2f}..{r.max():.2f}, max |g sqrt(1-2/D) - sqrt(1-3/r)| = {err:.1e}, "
          f"hit radius vs independent Binet integration max rel err {rerr:.1e}")
    assert err < 1e-9
    assert rerr < 1e-5


def test_face_on_redshift_kerr():
    """Face-on, spin 0.9: g = 1/u^t = sqrt(1 - 3/r + 2a r^-1.5) / (1 + a r^-1.5) at infinity."""
    a, dist = 0.9, 1e5
    sc = kerr.KerrScene(spin=a, distance=dist, inclination=90.0, roll=0.0, opacity=1.0)
    psi = np.linspace(4.0, 24.0, 12) / dist
    d = np.stack([np.zeros_like(psi), np.sin(psi), np.cos(psi)], -1)
    _, g = sc.trace_info(d)
    r, gg = g[:, 6], g[:, 7]
    assert (r > kerr.isco_radius(a)).all()
    al = sc.prm[kerr.P_ALPHA]
    ref = np.sqrt(1 - 3 / r + 2 * a * r ** -1.5) / (1 + a * r ** -1.5) / al
    assert np.allclose(gg, ref, rtol=1e-10)
    assert np.allclose(sc.redshift(r), ref, rtol=1e-10)


def test_approaching_side_is_brighter_and_bluer():
    """Doppler beaming: gas on screen-left (+x) comes towards the camera (as in BlackHoleScene)."""
    sc = kerr.KerrScene(spin=0.9, roll=0.0)
    d = camera_dirs(200, 120, math.tan(math.radians(40)))
    out, g = sc.trace_info(d)
    left, right = d[..., 0] > 0.05, d[..., 0] < -0.05
    hit = g[..., 6] > 0
    gl, gr = np.median(g[..., 7][left & hit]), np.median(g[..., 7][right & hit])
    lum = out[..., :3] @ bh.LUMA
    blue = out[..., 2] / np.maximum(out[..., 0], 1e-30)
    print(f"\n  median g left {gl:.3f} right {gr:.3f}; disk light left/right {lum[left].sum() / lum[right].sum():.2f}")
    assert gl > 1.1 * gr
    assert lum[left].sum() > 1.5 * lum[right].sum()
    assert np.median(blue[left & hit]) > np.median(blue[right & hit])


def test_render_matches_blackholescene_at_spin0():
    """256x256: same disk position/brightness pattern as the Schwarzschild tracer."""
    d = camera_dirs(256, 256, math.tan(math.radians(35)))
    k = kerr.KerrScene(spin=0.0, distance=D, inclination=10, roll=-14, r_out=26, t_max=26000,
                       opacity=2.2, seed=7).render(d)
    b = bh.BlackHoleScene(distance=D / 2, r_in=3, r_out=13, inclination=10, roll=-14, t_max=26000,
                          opacity=2.2, seed=7).render(d)
    lk, lb = k[..., :3] @ bh.LUMA, b[..., :3] @ bh.LUMA
    mk, mb = lk > 0, lb > 0
    iou = (mk & mb).sum() / (mk | mb).sum()

    def blocks(x):
        return x.reshape(16, 16, 16, 16).mean(axis=(1, 3))

    bk, bb = blocks(lk), blocks(lb)
    both = (bk > 0) & (bb > 0)
    corr = np.corrcoef(np.log(bk[both]), np.log(bb[both]))[0, 1]
    yy, xx = np.mgrid[0:256, 0:256]
    ck = np.array([(lk * xx).sum(), (lk * yy).sum()]) / lk.sum()
    cb = np.array([(lb * xx).sum(), (lb * yy).sum()]) / lb.sum()
    sk, sb = k[..., 6] > 0.5, b[..., 6] > 0.5
    sc_k = np.array([xx[sk].mean(), yy[sk].mean()])
    sc_b = np.array([xx[sb].mean(), yy[sb].mean()])
    ratio = lk.sum() / lb.sum()
    print(f"\n  vs BlackHoleScene: disk-mask IoU {iou:.4f}, 16x16-block log-luminance corr {corr:.4f}, "
          f"disk centroid offset {np.hypot(*(ck - cb)):.2f} px, shadow centroid offset "
          f"{np.hypot(*(sc_k - sc_b)):.2f} px, flux ratio {ratio:.3f}, shadow area ratio {sk.sum() / sb.sum():.3f}")
    assert iou > 0.9
    assert corr > 0.95
    assert np.hypot(*(ck - cb)) < 3.0
    assert np.hypot(*(sc_k - sc_b)) < 1.0
    assert 0.8 < ratio < 1.4
    # BlackHoleScene launches rays with h = D sin(psi) (no aberration of the static camera),
    # so its shadow is 1/sqrt(1 - 2/D) = 2.3% too large in radius; Kerr is exact.
    assert sk.sum() / sb.sum() == pytest.approx(1 - 2 / D, rel=0.04)


def test_disk_texture_matches_blackholescene():
    """A hot spot painted into the shared noise texture lands on the same pixels in both
    tracers (same azimuth origin and sense, same logarithmic twist)."""
    yy, xx = np.mgrid[0:512, 0:2048]
    du = (xx / 2048 - 0.25 + 0.5) % 1 - 0.5
    tex = np.exp(-(du / 0.03) ** 2 - ((yy / 511 - 0.5) / 0.05) ** 2)
    d = camera_dirs(160, 160, math.tan(math.radians(35)))
    k = kerr.KerrScene(spin=0.0, inclination=30, roll=-14, r_out=26, t_max=26000, opacity=2.2)
    b = bh.BlackHoleScene(distance=D / 2, r_in=3, r_out=13, inclination=30, roll=-14, t_max=26000, opacity=2.2)
    k.noise, b.noise = tex, tex
    cents = []
    for o in (k.render(d), b.render(d)):
        lum = o[..., :3] @ bh.LUMA
        lum = np.where(lum > 0.5 * lum.max(), lum, 0)
        y, x = np.mgrid[0:160, 0:160]
        cents.append(np.array([(lum * x).sum(), (lum * y).sum()]) / lum.sum())
    print(f"\n  hot spot centroid kerr {cents[0].round(2)} BlackHoleScene {cents[1].round(2)}")
    assert np.hypot(*(cents[0] - cents[1])) < 1.5


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


def test_output_contract():
    d = camera_dirs(40, 30, math.tan(math.radians(40)))
    sc = kerr.KerrScene(spin=0.9)
    out = sc.render(d)
    assert out.shape == (30, 40, 7)
    assert np.isfinite(out).all() and (out >= 0).all()
    assert (out[..., 3:6] == 0).all()                       # no background given
    assert out[..., :3].max() > 0 and out[..., 6].max() > 0.5
    # small batches give identical results
    assert np.array_equal(sc.render(d, batch=97), out)
    # with a uniform unit background and no disk: every ray is either sky or shadow
    ones = np.ones((6, 4, 4, 3))
    rng = np.random.default_rng(5)
    dd = np.concatenate([d.reshape(-1, 3), bh.normalize(rng.standard_normal((3000, 3)))])
    o = kerr.KerrScene(spin=0.9, opacity=0.0, background=ones).render(dd)
    assert (o[:, :3] == 0).all()
    assert np.allclose(o[:, 3] + o[:, 6], 1.0, atol=1e-12)
    assert np.allclose(o[:, 3], o[:, 5])
    # with the disk: sky + disk transmittance accounting stays within [0, 1]
    o = kerr.KerrScene(spin=0.9, background=ones).render(dd)
    assert np.isfinite(o).all()
    assert (o[:, 3] + o[:, 6] <= 1.0 + 1e-12).all() and (o[:, 3:7] >= 0).all()


def test_whole_sphere_has_no_nans():
    rng = np.random.default_rng(11)
    d = bh.normalize(rng.standard_normal((40000, 3)))
    galaxy = bh.make_galaxy(64, 3, galactic_north=(0.35, 0.85, 0.4), galactic_centre=(0.2, -0.3, 1.0),
                            n_stars=2000)
    for spin in (0.0, 0.5, 0.9, 0.998, -0.9):
        for incl in (10.0, 90.0, -35.0):
            o = kerr.KerrScene(spin=spin, inclination=incl, background=galaxy).render(d)
            assert np.isfinite(o).all() and (o >= 0).all(), (spin, incl)


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def test_performance_512_camera():
    d = camera_dirs(512, 512, math.tan(math.radians(35)))
    rates = {}
    for spin in (0.9, 0.0):
        sc = kerr.KerrScene(spin=spin)
        sc.render(d[:4])        # make sure the kernel is compiled
        t = time.perf_counter()
        sc.render(d)
        rates[spin] = d.shape[0] * d.shape[1] / (time.perf_counter() - t)
    print(f"\n  512x512 camera (half-angle 35 deg): spin 0.9 {rates[0.9]:,.0f} rays/s, "
          f"spin 0 {rates[0.0]:,.0f} rays/s")
    # loose floor: other processes may share the CPU while the tests run
    assert min(rates.values()) > 25000
