"""Tests for the Earth-as-the-moon textures (earth.py)."""

import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import celestial as cel  # noqa: E402
import earth  # noqa: E402
import natural_earth as ne  # noqa: E402

SIZE = 256
ORDER = ["new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous",
         "full_moon", "waning_gibbous", "third_quarter", "waning_crescent"]


def synthetic_maps(width=256):
    """A tiny planet: green land west of the prime meridian, blue sea east of it, a white
    cloud band at 40-50 N and one bright city at (0N, 30E)."""
    lat, lon = ne.grid(width)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    land = (lo < 0).astype(float)
    albedo = np.where(land[..., None] > 0, [0.05, 0.12, 0.04], [0.01, 0.02, 0.06])
    clouds = ((la > 40) & (la < 50)).astype(float) * 0.9
    lights = np.zeros(la.shape + (3,))
    lights[np.unravel_index(np.argmin((la - 0) ** 2 + (lo - 30) ** 2), la.shape)] = [1.0, 0.75, 0.4]
    maps = dict(albedo=albedo, water=1 - land, relief=np.zeros_like(land), clouds=clouds, lights=lights)
    return {k: np.ascontiguousarray(v, dtype=np.float64) for k, v in maps.items()}


@pytest.fixture(scope="module")
def maps():
    return synthetic_maps()


@pytest.fixture(scope="module")
def phases(maps):
    return {n: earth.render_earth_phase(n, SIZE, 2, maps) for n in ORDER}


def light(rgba):
    return (rgba[..., :3].astype(float) * rgba[..., 3:].astype(float) / 255.0).max(-1)


def test_view_basis_puts_the_sub_observer_point_in_front_north_up_east_right():
    b = earth.view_basis(20.0, 75.0)
    lat, lon = earth._latlon(b, 0.0, 0.0, 1.0)
    assert lat == pytest.approx(20.0) and lon == pytest.approx(75.0)
    lat_up, lon_up = earth._latlon(b, 0.0, math.sin(0.1), math.cos(0.1))
    assert lat_up > 20.0 and lon_up == pytest.approx(75.0, abs=1e-6)      # up is north
    lat_r, lon_r = earth._latlon(b, math.sin(0.1), 0.0, math.cos(0.1))
    assert lon_r > 75.0                                                   # right is east
    assert np.allclose(b @ b.T, np.eye(3))


def test_phase_order_brightness_and_lit_side(phases):
    total = [light(phases[n]).sum() for n in ORDER]
    assert total[4] == max(total), "full Earth is the brightest"
    assert total[0] < total[1] < total[2] < total[3] < total[4]
    assert total[4] > total[5] > total[6] > total[7] > total[0]

    def lit_side(name):
        lum = light(phases[name])
        half = SIZE // 2
        return np.sign(lum[:, half:].sum() - lum[:, :half].sum())
    for wax, wane in (("waxing_crescent", "waning_crescent"), ("first_quarter", "third_quarter"),
                      ("waxing_gibbous", "waning_gibbous")):
        assert lit_side(wax) > 0 > lit_side(wane), (wax, wane)     # waxing lit on the right like vanilla


def test_texture_edges_are_dark_and_corners_transparent(phases):
    for name, img in phases.items():
        lum = light(img)
        border = np.concatenate([lum[0], lum[-1], lum[:, 0], lum[:, -1]])
        assert border.max() <= 1.0, name
        assert img[0, 0, 3] == 0 and img[-1, -1, 3] == 0


def test_globe_size():
    radius_px = math.tan(math.radians(earth.EARTH_DIAMETER_DEG / 2)) / cel.MOON_HALF_TAN * SIZE / 2
    img = earth.render_earth(0.0, 0.0, 3.0, 1, SIZE, 2, synthetic_maps())
    lum = light(img)
    row = lum[SIZE // 2]
    lit = np.nonzero(row > 20)[0]
    assert abs((lit[-1] - lit[0] + 1) / 2 - radius_px) < 0.12 * radius_px


def test_new_earth_has_a_ring_and_city_lights(maps):
    # the only city is at (0N, 30E): look straight at it with the Sun behind the Earth
    img = earth.render_earth(0.0, 30.0, 180.0, 1, SIZE, 2, maps)
    lum = light(img)
    c = SIZE // 2
    assert lum[c - 3:c + 4, c - 3:c + 4].max() > 30, "the city shines on the night side"
    radius_px = math.tan(math.radians(earth.EARTH_DIAMETER_DEG / 2)) / cel.MOON_HALF_TAN * SIZE / 2
    yy, xx = np.mgrid[:SIZE, :SIZE]
    r = np.hypot(xx + 0.5 - c, yy + 0.5 - c)
    ring = lum[(r > radius_px) & (r < radius_px + 4)]
    inside = lum[(r < radius_px - 6) & (np.hypot(xx - c, yy - c) > 6)]
    assert ring.mean() > 15 and inside.mean() < 3, (ring.mean(), inside.mean())


def test_lights_only_on_the_night_side(maps):
    dark = dict(maps, lights=np.zeros_like(maps["lights"]))
    for alpha, expect_lights in ((3.0, False), (180.0, True)):
        a = earth.render_earth(0.0, 30.0, alpha, 1, SIZE, 2, maps).astype(float)
        b = earth.render_earth(0.0, 30.0, alpha, 1, SIZE, 2, dark).astype(float)
        diff = np.abs(light(a.astype(np.uint8)) - light(b.astype(np.uint8))).max()
        assert (diff > 20) == expect_lights, (alpha, diff)


def test_legacy_sheet(phases):
    sheet = cel.moon_phase_sheet(phases)
    s = sheet.shape[0] // 2
    assert sheet.shape == (2 * s, 4 * s, 4)
    legacy = ["full_moon", "waning_gibbous", "third_quarter", "waning_crescent",
              "new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous"]
    lit = [light(sheet[(k // 4) * s:(k // 4 + 1) * s, (k % 4) * s:(k % 4 + 1) * s]).sum() for k in range(8)]
    assert int(np.argmax(lit)) == legacy.index("full_moon")


def test_every_phase_has_a_view():
    assert set(earth.VIEWS) == set(cel.PHASES)
    for lat, lon in earth.VIEWS.values():
        assert -90 < lat < 90 and -180 <= lon <= 180
