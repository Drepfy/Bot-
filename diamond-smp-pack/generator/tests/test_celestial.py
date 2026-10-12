"""Tests for the photorealistic sun and moon textures (celestial.py)."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import celestial as cel  # noqa: E402

SIZE = 256
ORDER = ["new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous",
         "full_moon", "waning_gibbous", "third_quarter", "waning_crescent"]


@pytest.fixture(scope="module")
def sun():
    return cel.make_sun(SIZE)


@pytest.fixture(scope="module")
def phases():
    return cel.make_moon_phases(SIZE)


def additive(rgba):
    return rgba[..., :3].astype(float) * rgba[..., 3:].astype(float) / 255.0


def test_sun_shape_and_dtype(sun):
    assert sun.shape == (SIZE, SIZE, 4) and sun.dtype == np.uint8


def test_sun_glare_fades_out_before_the_quad_edge(sun):
    light = additive(sun).max(-1)
    border = np.concatenate([light[0], light[-1], light[:, 0], light[:, -1]])
    assert border.max() <= 1.0, "quad edges would show in game"
    assert light[SIZE // 2, SIZE // 2] > 240, "the disc centre should be (nearly) white"


def test_sun_disc_is_small_like_a_real_sun(sun):
    light = additive(sun).max(-1)
    disc = (light > 240).sum()
    radius_px = np.sqrt(disc / np.pi)
    radius_deg = np.degrees(np.arctan(radius_px / (SIZE / 2) * cel.SUN_HALF_TAN))
    assert 0.6 < radius_deg < 2.5, radius_deg


def test_all_moon_phases_present(phases):
    assert set(phases) == set(ORDER)
    for img in phases.values():
        assert img.shape == (SIZE, SIZE, 4) and img.dtype == np.uint8


def test_lit_fraction_rises_to_full_and_falls_back(phases):
    lit = [additive(phases[n]).max(-1).sum() for n in ORDER]
    assert lit[0] == min(lit) and lit[4] == max(lit)
    assert lit[0] < lit[1] < lit[2] < lit[3] < lit[4]
    assert lit[4] > lit[5] > lit[6] > lit[7]


def test_waxing_and_waning_are_lit_on_opposite_sides(phases):
    def side(name):
        light = additive(phases[name]).max(-1)
        half = SIZE // 2
        return np.sign(light[:, half:].sum() - light[:, :half].sum())
    for wax, wane in (("waxing_crescent", "waning_crescent"), ("first_quarter", "third_quarter"),
                      ("waxing_gibbous", "waning_gibbous")):
        assert side(wax) == -side(wane) != 0


def test_corners_are_transparent(sun, phases):
    for img in [sun, *phases.values()]:
        assert img[0, 0, 3] == 0 and img[-1, -1, 3] == 0


def test_legacy_sheet_layout(phases):
    sheet = cel.moon_phase_sheet(phases)
    s = sheet.shape[0] // 2
    assert sheet.shape == (2 * s, 4 * s, 4)
    # Minecraft's legacy order: full, waning gibbous, third quarter, waning crescent,
    # new, waxing crescent, first quarter, waxing gibbous (row-major).
    legacy = ["full_moon", "waning_gibbous", "third_quarter", "waning_crescent",
              "new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous"]
    lit = [additive(sheet[(k // 4) * s:(k // 4 + 1) * s, (k % 4) * s:(k % 4 + 1) * s]).max(-1).sum()
           for k in range(8)]
    assert int(np.argmax(lit)) == legacy.index("full_moon")
    assert int(np.argmin(lit)) == legacy.index("new_moon")
