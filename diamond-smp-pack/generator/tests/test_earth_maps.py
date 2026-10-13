"""Tests for the Earth's surface and cloud maps (earth_surface.py, earth_clouds.py)."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import earth_clouds as ec  # noqa: E402
import earth_surface as es  # noqa: E402
import natural_earth as ne  # noqa: E402

W = 1024


@pytest.fixture(scope="module")
def surf():
    return es.surface_maps(W)


@pytest.fixture(scope="module")
def clouds(surf):
    return ec.cloud_map(W, 1972, land=surf["land"])


def at(m, lat, lon):
    return ne.sample(m, lat, lon)


def box(m, lat0, lat1, lon0, lon1):
    lat, lon = ne.grid(m.shape[1])
    return m[(lat >= lat0) & (lat <= lat1)][:, (lon >= lon0) & (lon <= lon1)]


def test_shapes_and_ranges(surf, clouds):
    for k in ("land", "water", "ice", "relief"):
        assert surf[k].shape == (W // 2, W) and surf[k].dtype == np.float32, k
        assert surf[k].min() >= 0 and surf[k].max() <= 1, k
    assert surf["albedo"].shape == (W // 2, W, 3) and 0 <= surf["albedo"].min() and surf["albedo"].max() <= 1
    assert clouds.shape == (W // 2, W) and clouds.dtype == np.float32
    assert clouds.min() >= 0 and clouds.max() <= 1


def test_land_fraction_is_earths(surf):
    lat, _ = ne.grid(W)
    wgt = np.cos(np.radians(lat))[:, None]
    frac = float((surf["land"] * wgt).sum() / (wgt.sum() * W))
    assert 0.26 < frac < 0.31


def test_famous_places_look_right(surf):
    a = surf["albedo"]
    sahara = box(a, 20, 26, 0, 20).reshape(-1, 3).mean(0)
    amazon = box(a, -8, -2, -68, -58).reshape(-1, 3).mean(0)
    pacific = box(a, -10, 10, -160, -130).reshape(-1, 3).mean(0)
    antarctica = box(a, -85, -75, -180, 180).reshape(-1, 3).mean(0)
    assert sahara[0] > sahara[2] and sahara.mean() > 0.15, "the Sahara is bright sand"
    assert amazon[1] > amazon[0] and amazon[1] > amazon[2] and amazon.mean() < 0.08, "the Amazon is dark green"
    assert pacific[2] > pacific[0] and pacific.mean() < 0.03, "the open ocean is dark blue"
    assert antarctica.mean() > 0.6, "Antarctica is white ice"
    assert box(surf["ice"], -85, -75, -180, 180).mean() > 0.9
    assert box(surf["ice"], 70, 76, -45, -35).mean() > 0.8, "the Greenland ice sheet"
    # shallow turquoise Bahamas banks are much lighter than the open Atlantic next to them
    bahamas = box(a, 22.5, 24.5, -78, -76).reshape(-1, 3).mean(0)
    atlantic = box(a, 25, 28, -70, -66).reshape(-1, 3).mean(0)
    assert bahamas[1] > 1.5 * atlantic[1]


def test_orientation_east_is_east(surf):
    land = surf["land"]
    assert at(land, 9.0, 40.0) > 0.9 and at(land, 2.0, -5.0) < 0.1, "Ethiopia east of the Gulf of Guinea"
    assert at(land, 0.0, -20.0) < 0.05, "the Gulf of Guinea / Atlantic is west of Africa"
    assert at(land, 36.0, 138.0) > 0.9 and at(land, 36.0, 132.0) < 0.5, "Japan, east of the Sea of Japan"
    assert at(land, -25.0, 135.0) > 0.9 and at(land, 25.0, -40.0) < 0.05


def test_maps_are_seamless_across_the_date_line(surf, clouds):
    for m in (surf["albedo"], clouds):
        jump = np.abs(m[:, 0].astype(float) - m[:, -1].astype(float)).mean()
        typical = np.abs(m[:, 1:].astype(float) - m[:, :-1].astype(float)).mean()
        assert jump < 3 * typical + 1e-3


def test_clouds_follow_the_climate(surf, clouds):
    sahara = box(clouds, 18, 28, -5, 25).mean()
    southern_ocean = box(clouds, -60, -45, -180, 180).mean()
    lat, _ = ne.grid(W)
    wgt = np.cos(np.radians(lat))[:, None]
    mean = float((clouds * wgt).sum() / (wgt.sum() * W))
    assert sahara < 0.15, "the subtropical deserts are clear"
    assert southern_ocean > 2 * sahara, "the storm track is cloudy"
    assert 0.25 < mean < 0.7


def test_clouds_are_deterministic(surf):
    a = ec._render(512, 7, surf["land"][::2, ::2].copy())[0]
    b = ec._render(512, 7, surf["land"][::2, ::2].copy())[0]
    assert np.array_equal(a, b)
