"""Tests for the extra night-sky objects (night_sky.py): planets, the comet, zodiacal light, airglow."""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blackhole as bh  # noqa: E402
import night_sky as ns  # noqa: E402
import real_sky  # noqa: E402
import shader_sky  # noqa: E402


def test_scales_match_the_shader_sky():
    assert ns.STAR_GAIN == shader_sky.STAR_GAIN and ns.MW_GAIN == shader_sky.MW_GAIN


def test_planets_lie_on_the_ecliptic_above_the_horizon_and_clear_of_the_hole():
    for name, alt, az, sep, peak in ns.check_layout():
        assert alt > 4, name
        assert sep > 35, f"{name} must not crowd the black hole"
    for name, d, _, _ in ns.planets():
        beta = math.degrees(math.asin(float(d @ ns.ECLIPTIC_POLE)))
        assert abs(beta) < 2.5, name
    venus = next(p for p in ns.planets() if p[0] == "Venus")
    assert venus[2] == max(p[2] for p in ns.point_sources()), "Venus is the brightest"
    alt, az = real_sky.horizontal(venus[1])
    assert 240 < az < 300, "the evening star is in the west"


def test_ecliptic_frame():
    # the ecliptic is tilted by the obliquity to the celestial equator
    pole = real_sky.equatorial_to_world(0.0, 90.0)
    tilt = math.degrees(math.acos(float(np.clip(bh.normalize(pole) @ ns.ECLIPTIC_POLE, -1, 1))))
    assert abs(tilt - ns.OBLIQUITY_DEG) < 0.01
    # the Sun is below the horizon (it is night) and on the ecliptic
    assert ns.SUN_DIR[1] < -0.3 and abs(float(ns.SUN_DIR @ ns.ECLIPTIC_POLE)) < 1e-9


def test_comet_tails_point_away_from_the_sun():
    h, t = ns.comet_frame()
    anti_sun = bh.normalize(np.cross(np.cross(h, -ns.SUN_DIR), h))     # away from the Sun, on the sky at h
    assert t @ anti_sun > 0.5
    # the tail glows along t and not on the other side of the head
    along = bh.normalize(h + math.tan(math.radians(6)) * t)
    behind = bh.normalize(h - math.tan(math.radians(6)) * t)
    assert ns.extended_radiance(along).sum() > 10 * ns.extended_radiance(behind).sum()


def test_airglow_is_brightest_low_down_and_nothing_below_the_horizon():
    def glow(alt):
        return ns._airglow(real_sky.horizontal_to_world(alt, 10.0))[1]
    assert glow(5) > glow(20) > glow(60) > glow(90) > 0
    assert np.all(ns.extended_radiance(real_sky.horizontal_to_world(-10.0, 300.0)) == 0)


def test_zodiacal_light_brightest_towards_the_sun():
    near = ns._zodiacal(bh.normalize(ns.ecliptic_to_world(ns.SUN_ECL_LON + 40, 0)))
    far = ns._zodiacal(bh.normalize(ns.ecliptic_to_world(ns.SUN_ECL_LON + 120, 0)))
    off = ns._zodiacal(bh.normalize(ns.ecliptic_to_world(ns.SUN_ECL_LON + 40, 40)))
    gegen = ns._zodiacal(bh.normalize(ns.ecliptic_to_world(ns.SUN_ECL_LON + 180, 0)))
    assert near[0] > far[0] > off[0] * 0.5 and near[0] > 3 * off[0]
    assert gegen[0] > ns._zodiacal(bh.normalize(ns.ecliptic_to_world(ns.SUN_ECL_LON + 150, 0)))[0]
