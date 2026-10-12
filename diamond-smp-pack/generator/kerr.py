"""Physically exact Kerr (spinning) black hole renderer for the Diamond SMP skies.

Drop-in, more realistic replacement for ``blackhole.BlackHoleScene``.

Units: G = c = M = 1 (lengths in units of the hole's mass M; the Schwarzschild
radius is 2). Boyer-Lindquist (BL) coordinates (t, r, theta, phi), spin a = J/M.

Light rays
----------
Every pixel is traced backwards from the camera along an exact null geodesic of
the Kerr metric, using the Hamiltonian / Carter-constant formulation (James,
von Tunzelmann, Franklin & Thorne 2015, CQG 32 065001, appendix A). For a photon
with p_t = -1 the conserved quantities are b = p_phi and the Carter constant

    q = p_theta^2 + cos^2(theta) (b^2 / sin^2(theta) - a^2),

and the super-Hamiltonian (times Sigma, i.e. in Mino time d lambda = d tau / Sigma) is

    H~ = 1/2 [ Delta p_r^2 + p_theta^2 - R(r)/Delta - Theta(theta) ] = 0
    R(r)         = P^2 - Delta ((b - a)^2 + q),   P = r^2 + a^2 - a b
    Theta(theta) = q + a^2 cos^2(theta) - b^2 cot^2(theta)
    Delta = r^2 - 2 r + a^2,  Sigma = r^2 + a^2 cos^2(theta).

The radial pair (r, p_r) is replaced by the canonical pair u = 1/r,
w = du/dlambda = -Delta p_r / r^2 (the Kerr analogue of Binet's u = 1/r). Then

    w^2 = S(u) = u^4 R(1/u) = 1 + c2 u^2 + 2 K u^3 + (p_b^2 - a^2 K) u^4,
    K = (b - a)^2 + q,  p_b = a^2 - a b,  c2 = 2 p_b - K,

and the five integrated variables obey

    du/dl     = w                  dw/dl       = S'(u)/2 = c2 u + 3 K u^2 + 2 (p_b^2 - a^2 K) u^3
    dtheta/dl = p_theta            dp_theta/dl = Theta'(theta)/2
                                               = cos(theta) (b^2 / sin^3(theta) - a^2 sin(theta))
    dphi/dl   = -(a (1 + p_b u^2) / (1 - 2 u + a^2 u^2) - a + b / sin^2(theta))
                (= -dphi/dl of the forward photon: the ray is traced backwards).

Every right-hand side is a polynomial in u (or a regular function of it): no
pole at r = infinity, where r(lambda) itself would blow up in finite Mino time,
and no 1/Delta in the radial equation at the horizon. The far field therefore
costs only a few steps, and an escaping ray is integrated exactly to infinity
(u = 0). Both halves of the constraint, w^2 - S(u) and p_theta^2 - Theta, are
exact invariants of this flow; the solver monitors H = H~/Sigma (E = 1).
The integrator is an adaptive Dormand-Prince 5(4) Runge-Kutta scheme with an
embedded error estimate (FSAL). The local error control automatically shrinks
the step close to the horizon and in the photon region; theta errors are
absolute, phi errors are weighted by sin(theta) (a physical angle) so rays that
graze the spin axis are cheap, and b = 0 rays pass straight through the poles
(theta simply continues past 0 or pi, which is the same point as (-theta, phi+pi)).
Equatorial crossings and the escape point are located on the cubic Hermite
interpolant of each accepted step.

Camera
------
A ZAMO (FIDO) camera at r = distance, theta_o = 90 - inclination, phi = 0. Scene
axes map to its orthonormal frame as forward = -e_r, up = -e_theta,
right = +e_phi, i.e. n_r = -dz, n_theta = -dy, n_phi = -dx for an un-rolled
scene direction d (scene +z looks at the hole, +y is up, screen-right is -x).
The camera energy, b and q follow James et al. eqs. A9-A11. ``roll`` rotates
the picture about the view axis exactly like BlackHoleScene.

Termination: inside 1.01 r_+ -> shadow; u = 1/r reaches 0 -> escaped. At
infinity the ray moves radially, so its direction is exactly the radial unit
vector at the asymptotic (theta, phi); the background cube map is sampled in
that direction (rotated into the rolled scene frame).

Accretion disk
--------------
A thin, equatorial, prograde Novikov-Thorne disk from the ISCO to r_out:

* effective temperature T ~ F^(1/4) from the Page-Thorne flux
  F(r) = -(Mdot / 4 pi r) Omega' / (E - Omega L)^2 * int_isco^r (E - Omega L) L' dr
  computed numerically from the Kerr circular-orbit E(r), L(r), Omega(r);
* redshift g = E_camera / (u^t (1 - Omega b)), Omega = 1 / (r^1.5 + a)
  (gravitational redshift + relativistic Doppler + frame dragging + the
  camera's own ZAMO frame); the observed colour is the blackbody at g T, which
  carries the g^4 bolometric (g^3 specific intensity) boost;
* limb darkening (1 + 2.06 mu) / 2.03 with mu the emission angle to the disk
  normal measured in the gas rest frame, mu = sqrt(q) / (r u^t (1 - Omega b));
* the turbulence / opacity model of blackhole.trace (orbital streaks wound by
  differential rotation, temperature fluctuations, partial transparency), so
  every crossing of the equatorial plane adds light and the higher-order
  lensed images of the disk (photon rings) appear by themselves.
"""

import math

import numpy as np
from numba import njit, prange

import blackhole as bh

# fastmath without 'nnan'/'ninf', so the NaN/inf guards of the step control keep working.
FM = {"nsz", "arcp", "contract", "afn", "reassoc"}

# ---------------------------------------------------------------------------
# Kerr geometry helpers (python / numpy)
# ---------------------------------------------------------------------------


def horizon_radius(a):
    """Outer event horizon r_+ = 1 + sqrt(1 - a^2)."""
    return 1.0 + math.sqrt(max(1.0 - a * a, 0.0))


def isco_radius(a):
    """ISCO of an orbit in the +phi sense (prograde for a > 0, retrograde for a < 0)."""
    z1 = 1.0 + (1.0 - a * a) ** (1.0 / 3.0) * ((1.0 + a) ** (1.0 / 3.0) + (1.0 - a) ** (1.0 / 3.0))
    z2 = math.sqrt(3.0 * a * a + z1 * z1)
    return 3.0 + z2 - math.copysign(1.0, a) * math.sqrt(max((3.0 - z1) * (3.0 + z1 + 2.0 * z2), 0.0)) \
        if a != 0.0 else 6.0


def photon_orbit_radii(a):
    """Radii of the equatorial circular photon orbits (prograde, retrograde) for a >= 0."""
    a = abs(a)
    return (2.0 * (1.0 + math.cos(2.0 / 3.0 * math.acos(-a))),
            2.0 * (1.0 + math.cos(2.0 / 3.0 * math.acos(a))))


def circular_orbit(r, a):
    """Specific energy E, angular momentum L, angular velocity Omega and u^t of
    circular equatorial geodesics moving in +phi (Bardeen, Press & Teukolsky 1972)."""
    r = np.asarray(r, dtype=np.float64)
    sr = np.sqrt(r)
    r32 = r * sr
    den = r ** 0.75 * np.sqrt(r32 - 3.0 * sr + 2.0 * a)
    e = (r32 - 2.0 * sr + a) / den
    l = (r * r - 2.0 * a * sr + a * a) / den
    om = 1.0 / (r32 + a)
    ut = (r32 + a) / den
    return e, l, om, ut


def page_thorne_flux(r, a, n=200001):
    """Page-Thorne (Novikov-Thorne) flux F(r) * 4 pi / Mdot for r >= r_isco (numerical).

    F = -(1 / r) Omega' / (E - Omega L)^2 * int_isco^r (E - Omega L) L' dr.
    """
    r = np.asarray(r, dtype=np.float64)
    r_in = isco_radius(a)
    r_hi = max(float(np.max(r)), r_in) * 1.0001 + 1e-9
    # fine grid, denser near the ISCO (uniform in sqrt(r - r_in))
    s = np.linspace(0.0, math.sqrt(r_hi - r_in), n)
    rg = r_in + s * s
    e, l, om, _ = circular_orbit(rg, a)
    h = 1e-6 * rg
    dl = (circular_orbit(rg + h, a)[1] - circular_orbit(rg - h, a)[1]) / (2.0 * h)
    dom = -1.5 * np.sqrt(rg) / (rg ** 1.5 + a) ** 2
    integrand = (e - om * l) * dl
    integral = np.concatenate([[0.0], np.cumsum(0.5 * (integrand[1:] + integrand[:-1]) * np.diff(rg))])
    flux = -dom / (e - om * l) ** 2 * integral / rg
    return np.interp(np.clip(r, r_in, None), rg, flux) * (r >= r_in)


def temperature_table(a, r_max, n=4096):
    """T(r) / T_peak on a uniform grid in ln r from the ISCO to r_max (and the grid bounds)."""
    r_in = isco_radius(a)
    r_hi = max(r_max, 30.0 * r_in)
    lo, hi = math.log(r_in), math.log(r_hi)
    rr = np.exp(np.linspace(lo, hi, n))
    f = page_thorne_flux(rr, a)
    t = np.maximum(f, 0.0) ** 0.25
    return np.ascontiguousarray(t / t.max()), lo, hi


def photon_orbit_constants(r, a):
    """(xi, eta) = (b, q) of the spherical photon orbit at radius r (Bardeen 1973)."""
    r = np.asarray(r, dtype=np.float64)
    xi = (r * r * (3.0 - r) - a * a * (r + 1.0)) / (a * (r - 1.0))
    eta = r ** 3 * (4.0 * a * a - r * (r - 3.0) ** 2) / (a * a * (r - 1.0) ** 2)
    return xi, eta


def zamo_frame(r, theta, a):
    """Lapse alpha, frame-dragging omega, cylindrical radius varpi, rho, sqrt(Delta)."""
    s, c = math.sin(theta), math.cos(theta)
    sig = r * r + a * a * c * c
    dlt = r * r - 2.0 * r + a * a
    big_a = (r * r + a * a) ** 2 - a * a * dlt * s * s
    return (math.sqrt(sig * dlt / big_a), 2.0 * a * r / big_a, math.sqrt(big_a / sig) * s,
            math.sqrt(sig), math.sqrt(dlt))


def ray_constants(n_r, n_th, n_ph, r, theta, a):
    """b, q, camera energy E and Mino-time velocities (dr/dl, dtheta/dl) of the backwards
    ray leaving a ZAMO at (r, theta) along the unit direction (n_r, n_theta, n_phi).
    James et al. (2015) eqs. A9-A11 with p_t = -1."""
    al, om, vp, rho, sd = zamo_frame(r, theta, a)
    n_r, n_th, n_ph = (np.asarray(x, dtype=np.float64) for x in (n_r, n_th, n_ph))
    e = 1.0 / (al - om * vp * n_ph)
    b = -e * vp * n_ph
    vr = e * rho * sd * n_r
    vth = e * rho * n_th
    c, s = math.cos(theta), math.sin(theta)
    q = vth * vth + c * c * (b * b / (s * s) - a * a)
    return b, q, e, vr, vth


def shadow_edge_directions(a, distance, inclination, n=721):
    """Exact shadow boundary seen by the ZAMO camera at finite distance.

    The edge is made of rays asymptotic to spherical photon orbits: (b, q) =
    (xi(r_p), eta(r_p)). For each r_p we invert the camera map (A9-A11) to get the
    pixel direction. Returns unit directions (m, 3) in the UN-ROLLED scene frame,
    ordered around the curve (upper half, then lower half reversed)."""
    th_o = math.radians(90.0 - inclination)
    al, om, vp, rho, sd = zamo_frame(distance, th_o, a)
    lo, hi = photon_orbit_radii(a) if a != 0 else (3.0, 3.0)
    if a == 0.0:
        # Schwarzschild: b^2 + q = 27 for every edge ray
        psi = np.linspace(0, 2 * np.pi, n)
        l2 = 27.0
        b = math.sqrt(l2) * np.cos(psi)
        q = l2 - b * b
    else:
        rp = lo + (hi - lo) * 0.5 * (1 - np.cos(np.linspace(0, np.pi, n)))
        b, q = photon_orbit_constants(rp, a)
    c, s = math.cos(th_o), math.sin(th_o)
    th2 = q + a * a * c * c - b * b * c * c / (s * s)
    ok = th2 >= 0
    b, th2 = b[ok], th2[ok]
    e = (1.0 - om * b) / al
    n_ph = -b / (vp * e)
    n_th = np.sqrt(th2) / (rho * e)
    n_r = -np.sqrt(np.clip(1.0 - n_ph ** 2 - n_th ** 2, 0, None))
    up = np.stack([-n_ph, -n_th, -n_r], -1)            # n_theta > 0 -> below (scene dy < 0)
    dn = np.stack([-n_ph, n_th, -n_r], -1)[::-1]
    return np.concatenate([up, dn])


# ---------------------------------------------------------------------------
# The numba ray tracer
# ---------------------------------------------------------------------------

(P_A, P_ROBS, P_THO, P_RIN, P_ROUT, P_RSTOP, P_SPARE, P_TOL, P_MAXSTEP, P_TMAX, P_TAU,
 P_EMIS, P_TURB, P_TWIST, P_TLO, P_THI, P_ALPHA, P_OMEGA, P_VARPI, P_RHO, P_SQD) = range(21)
N_PRM = 21
N_DIAG = 11

# Dormand-Prince 5(4) tableau
A21 = 1.0 / 5.0
A31, A32 = 3.0 / 40.0, 9.0 / 40.0
A41, A42, A43 = 44.0 / 45.0, -56.0 / 15.0, 32.0 / 9.0
A51, A52, A53, A54 = 19372.0 / 6561.0, -25360.0 / 2187.0, 64448.0 / 6561.0, -212.0 / 729.0
A61, A62, A63, A64, A65 = 9017.0 / 3168.0, -355.0 / 33.0, 46732.0 / 5247.0, 49.0 / 176.0, -5103.0 / 18656.0
B1, B3, B4, B5, B6 = 35.0 / 384.0, 500.0 / 1113.0, 125.0 / 192.0, -2187.0 / 6784.0, 11.0 / 84.0
E1, E3, E4, E5, E6, E7 = (71.0 / 57600.0, -71.0 / 16695.0, 71.0 / 1920.0, -17253.0 / 339200.0,
                          22.0 / 525.0, -1.0 / 40.0)


@njit(inline="always", fastmath=FM)
def _rhs(y, a, a2, b, b2, p_b, c2, c1, c0):
    """Mino-time derivatives of (u = 1/r, theta, phi, w = du/dl, p_theta) for the backwards ray.

    w' = S'(u)/2 with S(u) = u^4 R(1/u) = 1 + c2 u^2 + (2/3) c1 u^3 + (1/2) c0 u^4."""
    u, th, w, vth = y[0], y[1], y[3], y[4]
    s = math.sin(th)
    c = math.cos(th)
    uu = u * u
    dph = a - a * (1.0 + p_b * uu) / (1.0 - 2.0 * u + a2 * uu)
    if b == 0.0:
        dvth = -a2 * s * c
    else:
        is2 = 1.0 / (s * s)
        dph -= b * is2
        dvth = c * (b2 * is2 / s - a2 * s)
    dw = u * (c2 + u * (c1 + u * c0))
    return (w, vth, dph, dw, dvth)


@njit(inline="always", fastmath=FM)
def _lc(y, h, c1, k1, c2, k2, c3, k3, c4, k4, c5, k5, c6, k6):
    return (y[0] + h * (c1 * k1[0] + c2 * k2[0] + c3 * k3[0] + c4 * k4[0] + c5 * k5[0] + c6 * k6[0]),
            y[1] + h * (c1 * k1[1] + c2 * k2[1] + c3 * k3[1] + c4 * k4[1] + c5 * k5[1] + c6 * k6[1]),
            y[2] + h * (c1 * k1[2] + c2 * k2[2] + c3 * k3[2] + c4 * k4[2] + c5 * k5[2] + c6 * k6[2]),
            y[3] + h * (c1 * k1[3] + c2 * k2[3] + c3 * k3[3] + c4 * k4[3] + c5 * k5[3] + c6 * k6[3]),
            y[4] + h * (c1 * k1[4] + c2 * k2[4] + c3 * k3[4] + c4 * k4[4] + c5 * k5[4] + c6 * k6[4]))


@njit(inline="always", fastmath=FM)
def _lc1(y, h, c1, k1):
    return (y[0] + h * c1 * k1[0], y[1] + h * c1 * k1[1], y[2] + h * c1 * k1[2],
            y[3] + h * c1 * k1[3], y[4] + h * c1 * k1[4])


@njit(inline="always", fastmath=FM)
def _lc2(y, h, c1, k1, c2, k2):
    return (y[0] + h * (c1 * k1[0] + c2 * k2[0]), y[1] + h * (c1 * k1[1] + c2 * k2[1]),
            y[2] + h * (c1 * k1[2] + c2 * k2[2]), y[3] + h * (c1 * k1[3] + c2 * k2[3]),
            y[4] + h * (c1 * k1[4] + c2 * k2[4]))


@njit(inline="always", fastmath=FM)
def _lc3(y, h, c1, k1, c2, k2, c3, k3):
    return (y[0] + h * (c1 * k1[0] + c2 * k2[0] + c3 * k3[0]),
            y[1] + h * (c1 * k1[1] + c2 * k2[1] + c3 * k3[1]),
            y[2] + h * (c1 * k1[2] + c2 * k2[2] + c3 * k3[2]),
            y[3] + h * (c1 * k1[3] + c2 * k2[3] + c3 * k3[3]),
            y[4] + h * (c1 * k1[4] + c2 * k2[4] + c3 * k3[4]))


@njit(inline="always", fastmath=FM)
def _lc4(y, h, c1, k1, c2, k2, c3, k3, c4, k4):
    return (y[0] + h * (c1 * k1[0] + c2 * k2[0] + c3 * k3[0] + c4 * k4[0]),
            y[1] + h * (c1 * k1[1] + c2 * k2[1] + c3 * k3[1] + c4 * k4[1]),
            y[2] + h * (c1 * k1[2] + c2 * k2[2] + c3 * k3[2] + c4 * k4[2]),
            y[3] + h * (c1 * k1[3] + c2 * k2[3] + c3 * k3[3] + c4 * k4[3]),
            y[4] + h * (c1 * k1[4] + c2 * k2[4] + c3 * k3[4] + c4 * k4[4]))


@njit(inline="always", fastmath=FM)
def _lc5(y, h, c1, k1, c2, k2, c3, k3, c4, k4, c5, k5):
    return (y[0] + h * (c1 * k1[0] + c2 * k2[0] + c3 * k3[0] + c4 * k4[0] + c5 * k5[0]),
            y[1] + h * (c1 * k1[1] + c2 * k2[1] + c3 * k3[1] + c4 * k4[1] + c5 * k5[1]),
            y[2] + h * (c1 * k1[2] + c2 * k2[2] + c3 * k3[2] + c4 * k4[2] + c5 * k5[2]),
            y[3] + h * (c1 * k1[3] + c2 * k2[3] + c3 * k3[3] + c4 * k4[3] + c5 * k5[3]),
            y[4] + h * (c1 * k1[4] + c2 * k2[4] + c3 * k3[4] + c4 * k4[4] + c5 * k5[4]))


@njit(inline="always", fastmath=FM)
def _hermite(s, h, y0, d0, y1, d1):
    s2 = s * s
    s3 = s2 * s
    return ((2.0 * s3 - 3.0 * s2 + 1.0) * y0 + (s3 - 2.0 * s2 + s) * h * d0
            + (-2.0 * s3 + 3.0 * s2) * y1 + (s3 - s2) * h * d1)


@njit(inline="always", fastmath=FM)
def _hermite_d(s, h, y0, d0, y1, d1):
    s2 = s * s
    return ((6.0 * s2 - 6.0 * s) * y0 + (3.0 * s2 - 4.0 * s + 1.0) * h * d0
            + (-6.0 * s2 + 6.0 * s) * y1 + (3.0 * s2 - 2.0 * s) * h * d1)


@njit(inline="always", fastmath=FM)
def _hermite_root(target, h, y0, d0, y1, d1):
    """s in [0, 1] where the cubic Hermite interpolant crosses `target` (Newton from the chord)."""
    sc = (target - y0) / (y1 - y0)
    for _ in range(5):
        f = _hermite(sc, h, y0, d0, y1, d1) - target
        df = _hermite_d(sc, h, y0, d0, y1, d1)
        if df != 0.0:
            sc = min(max(sc - f / df, 0.0), 1.0)
    return sc


@njit(inline="always", fastmath=FM)
def _hamiltonian(y, a2, b2, q, kk, p_b):
    """H = H~ / Sigma = 1/2 g^{mu nu} p_mu p_nu for p_t = -1 (should stay 0)."""
    r = 1.0 / y[0]
    th, vr, vth = y[1], -y[3] * r * r, y[4]
    s = math.sin(th)
    c = math.cos(th)
    dl = r * r - 2.0 * r + a2
    p = r * r + p_b
    rr = p * p - dl * kk
    tt = q + a2 * c * c
    if b2 != 0.0:
        tt -= b2 * c * c / (s * s)
    sig = r * r + a2 * c * c
    return 0.5 * ((vr * vr - rr) / dl + vth * vth - tt) / sig


@njit(parallel=True, fastmath=FM)
def trace_kerr(dirs, prm, unroll, mrot, ttab, lut, lut_lo, lut_hi, noise, bg, use_bg, out, diag, want_diag):
    """Trace each scene direction backwards from the camera through the Kerr spacetime.

    out[:, 0:3] disk light, out[:, 3:6] lensed background light, out[:, 6] shadow.
    diag (if want_diag): asymptotic direction (3), status (1 escaped, 2 captured,
    3 step budget, 4 opaque), steps, max |H|, first disk-hit r, its g, b, q,
    max |p_theta^2 - Theta| / (1 + sqrt(|q| + b^2))^2.
    """
    a = prm[P_A]
    a2 = a * a
    r_obs, th_o = prm[P_ROBS], prm[P_THO]
    r_in, r_out = prm[P_RIN], prm[P_ROUT]
    u_stop, tol = 1.0 / prm[P_RSTOP], prm[P_TOL]
    max_steps = int(prm[P_MAXSTEP])
    t_max, opac, emis, turb, twist = prm[P_TMAX], prm[P_TAU], prm[P_EMIS], prm[P_TURB], prm[P_TWIST]
    t_lo, t_hi = prm[P_TLO], prm[P_THI]
    alpha_c, omega_c, varpi_c, rho_c, sqd_c = prm[P_ALPHA], prm[P_OMEGA], prm[P_VARPI], prm[P_RHO], prm[P_SQD]
    nt = ttab.shape[0]
    lr_in, lr_out = math.log(r_in), math.log(r_out)
    ln2 = math.log(2.0)
    cth_o, sth_o = math.cos(th_o), math.sin(th_o)
    two_pi = 2.0 * math.pi
    half_pi = 0.5 * math.pi
    r_fringe = 0.95 * r_in
    u_disk_lo, u_disk_hi = 1.0 / r_out, 1.0 / r_fringe
    for i in prange(dirs.shape[0]):
        # ---- camera: scene direction -> ZAMO frame -> constants of motion ----
        dx = unroll[0, 0] * dirs[i, 0] + unroll[0, 1] * dirs[i, 1] + unroll[0, 2] * dirs[i, 2]
        dy = unroll[1, 0] * dirs[i, 0] + unroll[1, 1] * dirs[i, 1] + unroll[1, 2] * dirs[i, 2]
        dz = unroll[2, 0] * dirs[i, 0] + unroll[2, 1] * dirs[i, 1] + unroll[2, 2] * dirs[i, 2]
        dn = math.sqrt(dx * dx + dy * dy + dz * dz)
        # |b| < 1e-4 M: snap to the meridional plane (b = 0 rays pass straight through the
        # poles; the bounce of a tiny-b ray at theta_min ~ |b| / sqrt(q) is stiff, while the
        # change of the escape direction is only ~1e-5 rad)
        if abs(dx) * varpi_c < 1e-4 * dn:
            dx = 0.0
            dn = math.sqrt(dy * dy + dz * dz)
        n_r, n_th, n_ph = -dz / dn, -dy / dn, -dx / dn
        e_cam = 1.0 / (alpha_c - omega_c * varpi_c * n_ph)       # James et al. A11
        b = -e_cam * varpi_c * n_ph                               # p_phi (p_t = -1)
        if n_ph == 0.0:
            b = 0.0
        b2 = b * b
        vr0 = e_cam * rho_c * sqd_c * n_r                         # Delta p_r = dr/dlambda
        vth0 = e_cam * rho_c * n_th                               # p_theta
        q = vth0 * vth0 + cth_o * cth_o * (b2 / (sth_o * sth_o) - a2)   # Carter constant
        kk = (b - a) * (b - a) + q
        p_b = a2 - a * b
        c2 = 2.0 * p_b - kk
        c1 = 3.0 * kk
        c0 = 2.0 * (p_b * p_b - a2 * kk)
        lsc = 1.0 + math.sqrt(abs(q) + b2)
        sq_q = math.sqrt(max(q, 0.0))

        u0 = 1.0 / r_obs
        y = (u0, th_o, 0.0, -vr0 * u0 * u0, vth0)
        k1 = _rhs(y, a, a2, b, b2, p_b, c2, c1, c0)
        h = 0.05 / (abs(y[3]) / u0 + abs(vth0) + abs(k1[2] * sth_o) + 1e-12)
        trans = 1.0
        er, eg, eb = 0.0, 0.0, 0.0
        shadow = 0.0
        status = 3
        steps = 0
        h_max_err = 0.0
        c_max_err = 0.0
        hit_r, hit_g = 0.0, 0.0
        th_inf, ph_inf = 0.0, 0.0
        s_old = sth_o
        c_old = cth_o
        while steps < max_steps:
            steps += 1
            h = min(h, 0.5 / (abs(y[4]) + 1e-12))  # |dtheta| <= 0.5 rad per step
            k2 = _rhs(_lc1(y, h, A21, k1), a, a2, b, b2, p_b, c2, c1, c0)
            k3 = _rhs(_lc2(y, h, A31, k1, A32, k2), a, a2, b, b2, p_b, c2, c1, c0)
            k4 = _rhs(_lc3(y, h, A41, k1, A42, k2, A43, k3), a, a2, b, b2, p_b, c2, c1, c0)
            k5 = _rhs(_lc4(y, h, A51, k1, A52, k2, A53, k3, A54, k4), a, a2, b, b2, p_b, c2, c1, c0)
            k6 = _rhs(_lc5(y, h, A61, k1, A62, k2, A63, k3, A64, k4, A65, k5), a, a2, b, b2, p_b, c2, c1, c0)
            yn = _lc5(y, h, B1, k1, B3, k3, B4, k4, B5, k5, B6, k6)
            k7 = _rhs(yn, a, a2, b, b2, p_b, c2, c1, c0)
            s_new = math.sin(yn[1])
            c_new = math.cos(yn[1])
            e0 = h * (E1 * k1[0] + E3 * k3[0] + E4 * k4[0] + E5 * k5[0] + E6 * k6[0] + E7 * k7[0])
            e1 = h * (E1 * k1[1] + E3 * k3[1] + E4 * k4[1] + E5 * k5[1] + E6 * k6[1] + E7 * k7[1])
            e2 = h * (E1 * k1[2] + E3 * k3[2] + E4 * k4[2] + E5 * k5[2] + E6 * k6[2] + E7 * k7[2])
            e3 = h * (E1 * k1[3] + E3 * k3[3] + E4 * k4[3] + E5 * k5[3] + E6 * k6[3] + E7 * k7[3])
            e4 = h * (E1 * k1[4] + E3 * k3[4] + E4 * k4[4] + E5 * k5[4] + E6 * k6[4] + E7 * k7[4])
            err = max(max(abs(e0), abs(e1)), max(abs(e2) * min(abs(s_old), abs(s_new)),
                                                 max(abs(e3), abs(e4) / lsc))) / tol
            if not (err <= 1.0) or (b != 0.0 and s_old * s_new <= 0.0):
                if err > 1.0 and err < 1e30:
                    h *= max(0.2, 0.9 * err ** -0.25)
                else:
                    h *= 0.2
                if h < 1e-300:
                    break
                continue

            # ---- accepted step: crossings of the equatorial plane (the disk) ----
            if c_old * c_new < 0.0 and trans > 0.0:
                th0, th1 = y[1], yn[1]
                th_star = half_pi + math.pi * math.ceil((min(th0, th1) - half_pi) / math.pi)
                sc = _hermite_root(th_star, h, th0, k1[1], th1, k7[1])
                up = _hermite(sc, h, y[0], k1[0], yn[0], k7[0])
                if up > u_disk_lo and up < u_disk_hi:
                    rp = 1.0 / up
                    php = _hermite(sc, h, y[2], k1[2], yn[2], k7[2])
                    if math.sin(th_star) < 0.0:  # crossed via a pole: theta = -pi/2 is (pi/2, phi + pi)
                        php += math.pi
                    lr = math.log(rp)
                    lr_tex = lr - ln2  # texture in Schwarzschild radii, like BlackHoleScene
                    v = (lr - lr_in) / (lr_out - lr_in)
                    uu = (php + half_pi) / two_pi  # same azimuth origin as BlackHoleScene
                    n1 = bh._noise2(noise, uu + twist * lr_tex, v)
                    n2 = bh._noise2(noise, 2.0 * uu - 1.7 * twist * lr_tex + 0.37, v * 2.3 + 0.21)
                    ft = 0.0
                    if rp > r_in:
                        x = (lr - t_lo) / (t_hi - t_lo) * (nt - 1)
                        if x >= nt - 1:
                            ft = ttab[nt - 1]
                        else:
                            ix = int(x)
                            fx = x - ix
                            ft = ttab[ix] * (1.0 - fx) + ttab[ix + 1] * fx
                    ft = max(ft, 0.18 * min(max((rp - r_fringe) / (r_in * 0.05), 0.0), 1.0))
                    temp = t_max * ft * (1.0 + turb * (n2 - 0.5))
                    edge_in = min(max((rp - r_fringe) / (r_in * 0.08), 0.0), 1.0)
                    t_out = min(max((r_out - rp) / (r_out * 0.4), 0.0), 1.0)
                    edge_out = t_out * t_out * (3.0 - 2.0 * t_out)
                    tau = opac * (0.25 + 1.5 * n1) * edge_out ** 1.5 * edge_in
                    alpha = 1.0 - math.exp(-tau)
                    # Kerr circular-orbit kinematics (ISCO values inside the thin fringe)
                    rk = max(rp, r_in)
                    srk = math.sqrt(rk)
                    r32 = rk * srk
                    om = 1.0 / (r32 + a)
                    ut = (r32 + a) / (rk ** 0.75 * math.sqrt(r32 - 3.0 * srk + 2.0 * a))
                    e_gas = ut * (1.0 - om * b)  # photon energy in the gas frame (p_t = -1)
                    g = e_cam / e_gas
                    if hit_r == 0.0:
                        hit_r = rp
                        hit_g = g
                    if alpha > 1e-4:
                        mu = min(sq_q / (rp * e_gas), 1.0)
                        limb = (1.0 + 2.06 * mu) / 2.03
                        br, bgr, bbl = bh._bb(lut, lut_lo, lut_hi, g * temp)
                        w = trans * alpha * emis * (0.55 + 0.9 * n1 ** 1.5) * limb
                        er += w * br
                        eg += w * bgr
                        eb += w * bbl
                        trans *= 1.0 - alpha

            # ---- escape: u = 1/r reaches 0 (r = infinity) inside this step ----
            if yn[0] <= 0.0:
                sc = _hermite_root(0.0, h, y[0], k1[0], yn[0], k7[0])
                th_inf = _hermite(sc, h, y[1], k1[1], yn[1], k7[1])
                ph_inf = _hermite(sc, h, y[2], k1[2], yn[2], k7[2])
                status = 1
                break
            y = yn
            k1 = k7
            s_old = s_new
            c_old = c_new
            if y[0] > u_stop:
                status = 2
                break
            if want_diag:
                hh = abs(_hamiltonian(y, a2, b2, q, kk, p_b))
                if hh > h_max_err:
                    h_max_err = hh
                tt = q + a2 * c_new * c_new
                if b2 != 0.0:
                    tt -= b2 * c_new * c_new / (s_new * s_new)
                ce = abs(y[4] * y[4] - tt) / (lsc * lsc)
                if ce > c_max_err:
                    c_max_err = ce
            if trans < 0.002:
                status = 4
                break
            if not (y[0] == y[0]):
                break
            fac = 5.0
            if err > 1e-10:
                fac = min(5.0, max(0.2, 0.9 * err ** -0.2))
            h *= fac

        out[i, 0] = er
        out[i, 1] = eg
        out[i, 2] = eb
        out[i, 3] = 0.0
        out[i, 4] = 0.0
        out[i, 5] = 0.0
        ex, ey, ez = 0.0, 0.0, 0.0
        if status == 1:
            # the escaping ray's direction at infinity is the radial direction at (th_inf, ph_inf)
            st = math.sin(th_inf)
            vx, vy, vz = st * math.cos(ph_inf), st * math.sin(ph_inf), math.cos(th_inf)
            ex = mrot[0, 0] * vx + mrot[0, 1] * vy + mrot[0, 2] * vz
            ey = mrot[1, 0] * vx + mrot[1, 1] * vy + mrot[1, 2] * vz
            ez = mrot[2, 0] * vx + mrot[2, 1] * vy + mrot[2, 2] * vz
            if use_bg:
                sb = bh._sample_cube(bg, ex, ey, ez)
                out[i, 3] = trans * sb[0]
                out[i, 4] = trans * sb[1]
                out[i, 5] = trans * sb[2]
        elif status == 2:
            shadow = trans
        elif status == 3 and trans > 0.002:
            shadow = trans  # still orbiting the photon region when the step budget ran out
        out[i, 6] = shadow
        if want_diag:
            diag[i, 0] = ex
            diag[i, 1] = ey
            diag[i, 2] = ez
            diag[i, 3] = status
            diag[i, 4] = steps
            diag[i, 5] = h_max_err
            diag[i, 6] = hit_r
            diag[i, 7] = hit_g
            diag[i, 8] = b
            diag[i, 9] = q
            diag[i, 10] = c_max_err


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


class KerrScene:
    """A Kerr black hole of spin `spin` (|a| < 1, units of M) seen from `distance` (in M),
    the camera sitting `inclination` degrees above the disk plane, the picture
    rolled `roll` degrees on screen (same conventions as BlackHoleScene).

    Disk: thin prograde Novikov-Thorne disk from the ISCO to `r_out` (in M), peak
    temperature `t_max` (K). `tol` is the per-step error tolerance of the
    Dormand-Prince integrator (absolute, in u = M/r and radians); the default 1e-7
    keeps escape directions within ~2e-5 rad of a 1e-11 reference.

    Replacing BlackHoleScene(distance=d, r_out=ro, ...) (lengths in Schwarzschild radii):
    use KerrScene(distance=2 d, r_out=2 ro, ...) and pass `opacity` explicitly
    (BlackHoleScene's default is 5.0, ours 2.2). Expected differences at spin 0: the
    shadow is 2.3 % smaller in radius (BlackHoleScene omits the aberration of the static
    camera, sqrt(1 - 2M/D)), the relativistic Page-Thorne temperature peaks at 9.55 M
    instead of 8.17 M, and the disk is ~10 % brighter (the camera's own blueshift at
    finite D and fluid-frame limb darkening)."""

    def __init__(self, spin=0.9, distance=44.0, inclination=10.0, roll=-14.0, r_out=26.0,
                 background=None, seed=7, t_max=26000.0, opacity=2.2, emission=1.0,
                 turbulence=0.14, twist=0.55, max_steps=6000, tol=1e-7):
        a = float(np.clip(spin, -0.9999, 0.9999))
        self.spin = a
        self.distance = float(distance)
        self.inclination = float(inclination)
        self.roll = float(roll)
        th_o = math.radians(90.0 - inclination)
        th_o = min(max(th_o, 1e-5), math.pi - 1e-5)  # a camera exactly on the axis is degenerate
        self.theta_o = th_o
        self.r_horizon = horizon_radius(a)
        self.r_isco = isco_radius(a)
        self.r_out = float(r_out)
        if self.distance <= 1.05 * self.r_horizon:
            raise ValueError("camera must be outside the horizon")
        self.ttab, t_lo, t_hi = temperature_table(a, max(self.r_out, self.r_isco) * 1.05)
        al, om, vp, rho, sd = zamo_frame(self.distance, th_o, a)

        prm = np.zeros(N_PRM)
        prm[P_A], prm[P_ROBS], prm[P_THO] = a, self.distance, th_o
        prm[P_RIN], prm[P_ROUT] = self.r_isco, self.r_out
        prm[P_RSTOP] = 1.01 * self.r_horizon
        prm[P_TOL], prm[P_MAXSTEP] = tol, max_steps
        prm[P_TMAX], prm[P_TAU], prm[P_EMIS] = t_max, opacity, emission
        prm[P_TURB], prm[P_TWIST] = turbulence, twist
        prm[P_TLO], prm[P_THI] = t_lo, t_hi
        prm[P_ALPHA], prm[P_OMEGA], prm[P_VARPI], prm[P_RHO], prm[P_SQD] = al, om, vp, rho, sd
        self.prm = prm

        # rolled scene -> un-rolled scene, and BL Cartesian -> rolled scene
        roll_m = bh.rot(roll, (0, 0, 1))
        self.unroll = np.ascontiguousarray(roll_m.T)
        c, s = math.cos(th_o), math.sin(th_o)
        bl_to_scene = np.array([[0.0, -1.0, 0.0],   # scene x = -e_phi(camera)
                                [-c, 0.0, s],       # scene y = -e_theta(camera)
                                [-s, 0.0, -c]])     # scene z = -e_r(camera)
        self.mrot = np.ascontiguousarray(roll_m @ bl_to_scene)
        # the spin axis (and disk normal) in the rolled scene frame, like BlackHoleScene.nrm
        self.nrm = self.mrot @ np.array([0.0, 0.0, 1.0])

        self.noise = bh.periodic_noise(512, 2048, seed)
        self.bg = background if background is not None else np.zeros((6, 2, 2, 3))
        self.use_bg = background is not None

    def _run(self, dirs, batch, want_diag):
        shape = dirs.shape[:-1]
        flat = np.ascontiguousarray(dirs.reshape(-1, 3), dtype=np.float64)
        out = np.zeros((flat.shape[0], 7))
        diag = np.zeros((flat.shape[0] if want_diag else 1, N_DIAG))
        for s in range(0, flat.shape[0], batch):
            d = diag[s:s + batch] if want_diag else diag
            trace_kerr(flat[s:s + batch], self.prm, self.unroll, self.mrot, self.ttab,
                       bh.BB_LUT, bh.BB_LO, bh.BB_HI, self.noise, self.bg, self.use_bg,
                       out[s:s + batch], d, want_diag)
        return out.reshape(*shape, 7), (diag.reshape(*shape, N_DIAG) if want_diag else None)

    def render(self, dirs, batch=1 << 20):
        """dirs: (..., 3) unit vectors in scene space (camera looks along +z).

        Returns (..., 7): disk RGB, background RGB, shadow coverage."""
        return self._run(dirs, batch, False)[0]

    def trace_info(self, dirs, batch=1 << 20):
        """Like render, plus per-ray diagnostics (..., 11): asymptotic escape direction
        (rolled scene frame, 3), status (1 escaped, 2 captured, 3 step budget, 4 opaque),
        steps taken, max |H| (Hamiltonian constraint, E = 1), r and g of the first
        disk crossing, b, q, max |p_theta^2 - Theta| / (1 + sqrt(|q| + b^2))^2."""
        return self._run(dirs, batch, True)

    def redshift(self, r, b=0.0, n_phi=0.0):
        """g = E_camera / E_gas for a photon with impact parameter b from a disk ring at r."""
        rk = np.maximum(np.asarray(r, dtype=np.float64), self.r_isco)
        _, _, om, ut = circular_orbit(rk, self.spin)
        p = self.prm
        e_cam = 1.0 / (p[P_ALPHA] - p[P_OMEGA] * p[P_VARPI] * n_phi)
        return e_cam / (ut * (1.0 - om * b))
