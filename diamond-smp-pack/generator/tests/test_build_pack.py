"""Tests for the painted Overworld sky of build_pack.py: the black hole only at night, the
northern lights, and the OptiFine fade times.

Run from the generator folder:  python3 -m pytest -q tests/test_build_pack.py
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atmosphere as atm  # noqa: E402
import blackhole as bh  # noqa: E402
import build_pack as bp  # noqa: E402
import real_sky as rs  # noqa: E402


@pytest.fixture(scope="module")
def aurora():
    return bp.Aurora()


@pytest.fixture(scope="module")
def allsky(aurora):
    """Aurora radiance on an (elevation, azimuth) grid covering the whole upper sky, as the
    night layer adds it: dimmed by the atmosphere's extinction."""
    el = np.linspace(0.05, 89.0, 445)
    az = np.linspace(-180.0, 180.0, 1441)
    e, a = np.meshgrid(el, az, indexing="ij")
    d = rs.horizontal_to_world(e, a)
    trn = atm.SkyModel([atm.sun_direction(45.0, 1)]).transmittance(d)
    rad = aurora.radiance(d)
    return e, a, rad * trn, rad


def display(rad):
    return bh.srgb_encode(bp.aces(rad))


def test_aurora_is_in_the_northern_sky(allsky):
    e, a, rad, _ = allsky
    seen = display(rad)[..., 1] > 2 / 255
    assert seen.any()
    assert np.abs(a[seen]).max() < 80.0          # only the northern half of the sky
    assert 120.0 < np.ptp(a[seen]) < 160.0       # ~140 degrees of azimuth
    assert e[seen].min() > 0.5                   # fades out above the horizon...
    assert e[seen].max() < 70.0                  # ...and stays out of the zenith
    # brightest low down: the bright green (top 1%) is 5-35 degrees up
    g = rad[..., 1]
    bright = g > np.percentile(g[seen], 99)
    assert 4.0 < np.median(e[bright]) < 35.0


def test_aurora_is_nothing_below_the_horizon(aurora):
    az = np.linspace(-90, 90, 181)
    for el in (-0.3, -5.0, -30.0):
        assert np.abs(aurora.radiance(rs.horizontal_to_world(np.full_like(az, el), az))).max() == 0.0


def test_aurora_colours_green_below_red_on_top(allsky):
    """The emitted colours (before the air reddens them near the horizon)."""
    e, _, _, rad = allsky
    lit = rad[..., 1] > 1e-4
    low = lit & (rad[..., 1] > np.percentile(rad[..., 1][lit], 90))
    mean_low = rad[low].mean(axis=0)
    assert mean_low[1] > 2.5 * mean_low[0] and mean_low[1] > 1.6 * mean_low[2]  # oxygen green
    # Going up a column through the main curtain, red/green rises: crimson tops.
    north = np.argmin(np.abs(allsky[1][0] - 0.0))
    col = rad[:, north]
    green = col[:, 1]
    top = np.where(green > 1e-5)[0].max()
    peak = np.argmax(green)
    ratio = lambda i: col[i, 0] / max(col[i, 1], 1e-9)  # noqa: E731
    assert ratio(top - 2) > 4 * ratio(peak)


def test_aurora_brightness_on_screen(allsky):
    _, _, rad, _ = allsky
    disp = display(rad)[..., 1]
    assert 0.33 < disp.max() < 0.5                # peak ~0.35-0.5 in the green
    seen = disp > 2 / 255
    assert np.median(disp[seen]) < 0.15           # most of it faint and translucent


def test_aurora_has_fine_rays(aurora):
    """Strands a few tenths of a degree wide across the curtains (along an arc of the sky)."""
    az = np.linspace(-20.0, 20.0, 4001)            # 0.01 degree steps
    contrast = []
    for el in range(8, 32, 2):
        g = aurora.radiance(rs.horizontal_to_world(np.full_like(az, float(el)), az))[:, 1]
        hp = g - np.convolve(g, np.ones(101) / 101, mode="same")   # keep structure < 1 degree
        contrast.append(np.std(hp[200:-200]) / max(np.mean(g[200:-200]), 1e-12))
    assert max(contrast) > 0.1 and np.median(contrast) > 0.03


def _alpha(minute, fades):
    """OptiFine layer brightness at a time of day (minutes after 00:00)."""
    def m(t):
        h, mm = t.split(":")
        return int(h) * 60 + int(mm)
    s, e, o = (m(t) for t in fades)
    dur = (e - s) % 1440
    so = (o - dur) % 1440
    t_in, t_full, t_out = (minute - s) % 1440, (so - s) % 1440, (o - s) % 1440
    if t_in < dur:
        return t_in / dur
    if t_in <= t_full:
        return 1.0
    if t_in < t_out:
        return 1.0 - (t_in - t_full) / dur
    return 0.0


def test_black_hole_only_comes_out_at_night():
    layers = {name: fades for name, _, fades, _ in bp.OVERWORLD_LAYERS}
    order = [name for name, *_ in bp.OVERWORLD_LAYERS]
    for minute in range(0, 1440, 5):
        a = {n: _alpha(minute, f) for n, f in layers.items()}
        # Clear weather: the night layer (the hole) never shows while the day layer is up.
        if a["day"] > 0:
            assert a["night"] == 0.0, minute
        # Seen through the layers drawn above it.
        seen = a["night"]
        for n in order[order.index("night") + 1:4]:
            seen *= 1 - a[n]
        if 7 * 60 <= minute <= 18 * 60:
            assert seen == 0.0, minute
        if minute >= 20 * 60 or minute <= 4 * 60:
            assert seen == 1.0, minute
        # Rain: the night glow starts only once the day layer starts to fade.
        if a["overcast_day"] == 1.0:
            assert a["overcast_night"] == 0.0, minute
    # Sunset (18:47) and sunrise (05:13): the hole is only just appearing / disappearing.
    for minute in (18 * 60 + 47, 5 * 60 + 13):
        a = {n: _alpha(minute, f) for n, f in layers.items()}
        seen = a["night"] * (1 - a["sunrise"]) * (1 - a["day"]) * (1 - a["sunset"])
        assert 0.05 < seen < 0.3


def test_layer_descriptions():
    text = {name: comment for name, comment, *_ in bp.OVERWORLD_LAYERS}
    assert "northern lights" in text["night"] and "black hole" in text["night"]
    assert "black hole" in text["overcast_night"]
    for name in ("sunrise", "sunset", "overcast_day"):
        assert "black hole" not in text[name]
    props = bp.layer_props("day", text["day"], ("06:15", "07:30", "18:00"), "clear")
    assert props.startswith("# Diamond SMP - Day:") and "startFadeIn=06:15" in props


def test_daytime_layers_have_no_black_hole():
    """Tiny render of all layers: by day the sky is smooth, by night the hole is there."""
    galaxy = bh.make_galaxy(64, 3, n_stars=2000, star_flux=4.5, diffuse=0.0065,
                            **rs.make_galaxy_kwargs(bh.world_to_scene(bp.OVERWORLD_DIR)))
    face, pad = 48, 6
    imgs = bp.overworld_layers(face, 1, pad, galaxy, log_prefix="    ")
    assert set(imgs) == {"night", "sunrise", "day", "sunset", "overcast_day", "overcast_night"}
    # pixel of the hole (due south, 24 degrees up) in the OptiFine 3x2 layout
    best = None
    for tile in range(6):
        d = bp.optifine_tile_dirs(tile, face)
        cos = d @ bp.OVERWORLD_DIR
        k = np.unravel_index(np.argmax(cos), cos.shape)
        if best is None or cos[k] > best[0]:
            best = (cos[k], tile, k)
    _, tile, (y, x) = best
    r, c = divmod(tile, 3)
    y, x = r * face + y, c * face + x
    win = (slice(y - 6, y + 7), slice(x - 6, x + 7))
    night = imgs["night"][win].astype(float)
    assert night.max() - night.min() > 60          # the disk and its shadow
    for name in ("day", "sunrise", "sunset"):
        patch = imgs[name][win].astype(float)
        lap = np.abs(patch[2:, 1:-1] + patch[:-2, 1:-1] + patch[1:-1, 2:] + patch[1:-1, :-2] - 4 * patch[1:-1, 1:-1])
        assert lap.max() <= 6, name                # just the smooth sky gradient
    # Rain by day: a plain overcast, the same towards the hole (south) as away from it (north);
    # rain by night: the hole's glow makes the south brighter. 3x2 layout: tile 2 = S, 4 = N.
    def tile_mean(img, t):
        n = img.shape[0] // 2
        r, c = divmod(t, 3)
        return img[r * n:(r + 1) * n, c * n:(c + 1) * n].astype(float).mean()
    assert abs(tile_mean(imgs["overcast_day"], 2) - tile_mean(imgs["overcast_day"], 4)) < 0.5
    assert tile_mean(imgs["overcast_night"], 2) > tile_mean(imgs["overcast_night"], 4) + 1
