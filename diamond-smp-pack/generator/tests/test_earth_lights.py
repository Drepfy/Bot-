"""Tests for the night-side city lights map (earth_lights.py)."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import earth_lights as el  # noqa: E402
import natural_earth as ne  # noqa: E402

W = 1024


@pytest.fixture(scope="module")
def lights():
    return el.city_lights(W)


def region(m, lat0, lat1, lon0, lon1):
    lat, lon = ne.grid(m.shape[1])
    rows = (lat >= lat0) & (lat <= lat1)
    cols = (lon >= lon0) & (lon <= lon1)
    return m[rows][:, cols].max(-1)


def test_shape_range_and_mostly_dark(lights):
    assert lights.shape == (W // 2, W, 3) and lights.dtype == np.float32
    assert lights.min() >= 0 and 0.9 <= lights.max() <= 1.5
    assert (lights.max(-1) > 0.01).mean() < 0.05, "most of the planet is dark at night"


def test_famous_places(lights):
    def mean(*box):
        return float(region(lights, *box).mean())
    europe = mean(45, 55, -5, 15)
    usa_east = mean(33, 43, -90, -72)
    sahara = mean(18, 28, -5, 25)
    amazon = mean(-10, 0, -70, -55)
    pacific = mean(-20, 10, -170, -130)
    antarctica = mean(-85, -70, -180, 180)
    nile = mean(25, 29, 30.5, 33)                     # the river valley through the desert
    western_desert = mean(25, 29, 26, 29)
    assert europe > 5 * sahara and usa_east > 5 * sahara
    assert amazon < europe / 4 and pacific < 1e-3 and antarctica < 1e-4
    assert nile > 3 * western_desert
    korea_n = mean(39, 41, 125, 128.5)
    korea_s = mean(35, 37.5, 126.5, 129)
    assert korea_s > 4 * korea_n, "North Korea is dark next to South Korea"


def test_tokyo_is_among_the_brightest(lights):
    lat, lon = ne.grid(W)
    i = np.argmin(np.abs(lat - 35.69))
    j = np.argmin(np.abs(lon - 139.75))
    assert lights[i - 1:i + 2, j - 1:j + 2].max() > 0.8


def test_colour_is_warm(lights):
    lit = lights[lights.max(-1) > 0.05]
    assert np.all(lit[:, 0] >= lit[:, 2])
