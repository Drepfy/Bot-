"""Tests for real_sky.py: the real (BSC5) night sky placed around Sgr A*.

Run from the generator folder:  python3 -m pytest -q tests/test_real_sky.py
"""

import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blackhole as bh  # noqa: E402
import real_sky as rs  # noqa: E402


def alt_az(name):
    v = rs.named_star(name)
    assert v is not None, name
    alt, az = rs.horizontal(v)
    return float(alt), float(az)


def az_between(az, lo, hi):
    return lo <= az % 360.0 <= hi


# ---------------------------------------------------------------------------
# Observer and frames
# ---------------------------------------------------------------------------


def test_observer_constants():
    assert rs.LATITUDE_DEG == pytest.approx(36.99219, abs=1e-9)
    assert rs.LST_DEG == pytest.approx(266.41683, abs=1e-9)


def test_sgr_a_is_where_the_pack_draws_the_hole():
    target = bh.mc_direction(0, -24)
    assert rs.angle_deg(rs.SGR_A_WORLD, target) < 0.05
    alt, az = rs.horizontal(rs.SGR_A_WORLD)
    assert alt == pytest.approx(24.0, abs=1e-6)
    assert az == pytest.approx(180.0, abs=1e-6)
    # ...and therefore lands dead centre of the renderer's camera
    s = bh.world_to_scene(target) @ rs.SGR_A_WORLD
    assert s[2] == pytest.approx(1.0, abs=1e-9)


def test_rotation_is_proper_so_the_sky_is_not_mirrored():
    m = rs.EQUATORIAL_TO_WORLD
    assert np.allclose(m @ m.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(m) == pytest.approx(1.0, abs=1e-12)
    g = rs.GALACTIC_TO_WORLD
    assert np.allclose(g @ g.T, np.eye(3), atol=1e-9)
    assert np.linalg.det(g) == pytest.approx(1.0, abs=1e-9)


def test_cardinal_geometry():
    lat = math.radians(rs.LATITUDE_DEG)
    # the point with dec = latitude on the meridian is the zenith
    assert np.allclose(rs.equatorial_to_world(rs.LST_DEG, rs.LATITUDE_DEG), [0, 1, 0], atol=1e-12)
    # the celestial pole is due north (-z) at altitude = latitude
    assert np.allclose(rs.equatorial_to_world(123.0, 90.0), [0, math.sin(lat), -math.cos(lat)], atol=1e-12)
    # hour angle +6h on the equator = due west (-x); -6h = due east (+x)
    assert np.allclose(rs.equatorial_to_world(rs.LST_DEG - 90, 0.0), [-1, 0, 0], atol=1e-12)
    assert np.allclose(rs.equatorial_to_world(rs.LST_DEG + 90, 0.0), [1, 0, 0], atol=1e-12)


def test_vectorised_and_roundtrip():
    ra = np.array([[0.0, 90.0, 180.0], [266.4, 300.0, 359.9]])
    dec = np.array([[-80.0, 0.0, 45.0], [-29.0, 10.0, 89.0]])
    w = rs.equatorial_to_world(ra, dec)
    assert w.shape == (2, 3, 3)
    assert np.allclose(np.linalg.norm(w, axis=-1), 1.0)
    ra2, dec2 = rs.world_to_equatorial(w)
    assert np.allclose(dec2, dec, atol=1e-9)
    assert np.allclose((ra2 - ra + 180) % 360 - 180, 0, atol=1e-9)
    alt, az = rs.horizontal(w)
    assert np.allclose(rs.horizontal_to_world(alt, az), w, atol=1e-12)


# ---------------------------------------------------------------------------
# Real stars in the right places
# ---------------------------------------------------------------------------


def test_polaris_due_north_at_latitude():
    alt, az = alt_az("Polaris")
    assert abs(alt - rs.LATITUDE_DEG) < 1.0          # actual: 36.50
    assert min(az, 360 - az) < 1.0                   # actual: 0.69 (Polaris is 0.74 deg off the pole)
    v = rs.named_star("polaris")
    assert v[2] < 0 and abs(v[0]) < 0.02             # world -z is north


def test_vega_near_zenith():
    # At LST 17h45.7m Vega (RA 18h36.9m, Dec +38.78) is 51 minutes of hour angle east of the
    # meridian, so its altitude is 79.7 deg, not quite 80 (it transits at 88.2 deg 51 min later).
    alt, az = alt_az("Vega")
    assert alt > 79.5
    assert az_between(az, 0, 180)                    # still in the east, about to culminate


def test_antares_low_in_the_south_west():
    alt, az = alt_az("Antares")
    assert az_between(az, 180, 270)                  # actual: 198.7 (south-south-west)
    assert 15 <= alt <= 30                           # actual: 24.1
    assert rs.named_star("Antares")[0] < 0           # west is world -x


def test_summer_evening_landmarks():
    alt, az = alt_az("Arcturus")
    assert az_between(az, 240, 300) and 20 < alt < 60    # west
    alt, az = alt_az("Deneb")
    assert az_between(az, 20, 80) and alt > 45            # high in the north-east
    alt, az = alt_az("Altair")
    assert az_between(az, 100, 160) and 35 < alt < 65     # south-east
    for star in ("Dubhe", "Merak", "Alkaid", "Mizar"):    # Big Dipper in the north-west
        alt, az = alt_az(star)
        assert az_between(az, 290, 340) and 15 < alt < 60, star
    for star in ("Schedar", "Caph", "Ruchbah", "Navi"):   # Cassiopeia low in the north-east
        alt, az = alt_az(star)
        assert az_between(az, 15, 60) and 5 < alt < 35, star
    alt, az = alt_az("Kochab")                            # Little Dipper above Polaris, a bit west
    assert alt > rs.LATITUDE_DEG and az_between(az, 330, 360)


def test_scorpius_west_and_teapot_east_of_the_hole():
    w2s = bh.world_to_scene(rs.SGR_A_WORLD)
    # screen-right is scene -x in the renderer: west (Scorpius) is right, east (teapot) left.
    for star in ("Antares", "Shaula", "Lesath", "Sargas"):
        v = rs.named_star(star)
        assert v[0] < 0 and (w2s @ v)[0] < 0, star
    for star in ("Kaus Australis", "Nunki", "Ascella", "Kaus Borealis"):
        v = rs.named_star(star)
        assert v[0] > 0 and (w2s @ v)[0] > 0, star
    # the spout (Alnasl) is the part of the teapot closest to the black hole
    sep = {s: rs.angle_deg(rs.named_star(s), rs.SGR_A_WORLD) for s in
           ("Alnasl", "Kaus Media", "Kaus Australis", "Kaus Borealis", "Nunki", "Ascella")}
    assert min(sep, key=sep.get) == "Alnasl"
    # the stinger is lower than Antares (the tail curls down to the horizon)
    assert alt_az("Shaula")[0] < alt_az("Antares")[0]
    assert alt_az("Sargas")[0] < alt_az("Shaula")[0]


def test_pointers_point_at_polaris():
    merak, dubhe, polaris = (rs.named_star(s) for s in ("Merak", "Dubhe", "Polaris"))
    n1 = np.cross(merak, dubhe)
    off = math.degrees(math.asin(abs(np.dot(bh.normalize(n1), polaris))))
    assert off < 3.0


# ---------------------------------------------------------------------------
# Galactic frame
# ---------------------------------------------------------------------------


def test_galactic_frame():
    assert rs.angle_deg(rs.GALACTIC_CENTRE_WORLD, rs.SGR_A_WORLD) < 0.2     # actual 0.072
    assert abs(rs.angle_deg(rs.GALACTIC_NORTH_WORLD, rs.GALACTIC_CENTRE_WORLD) - 90) < 0.01
    for v in (rs.SGR_A_WORLD, rs.GALACTIC_NORTH_WORLD, rs.GALACTIC_CENTRE_WORLD):
        assert np.linalg.norm(v) == pytest.approx(1.0, abs=1e-12)
    l, b = rs.world_to_galactic(rs.SGR_A_WORLD)
    assert l == pytest.approx(359.944, abs=0.01) and b == pytest.approx(-0.046, abs=0.01)
    # l = 90, b = 0 lies in Cygnus at RA 21h12m01s, Dec +48d19m47s
    assert rs.angle_deg(rs.galactic_to_world(90, 0), rs.equatorial_to_world(318.0042, 48.3297)) < 0.01
    l, b = rs.world_to_galactic(rs.named_star("Deneb"))
    assert l == pytest.approx(84.28, abs=0.05) and b == pytest.approx(2.0, abs=0.05)


def test_make_galaxy_kwargs_scene_frame():
    w2s = bh.world_to_scene(bh.mc_direction(0, -24))
    kw = rs.make_galaxy_kwargs(w2s)
    assert set(kw) == {"galactic_north", "galactic_centre", "extra_stars", "mag_range"}
    assert np.dot(kw["galactic_centre"], [0, 0, 1]) > math.cos(math.radians(0.2))
    dirs, vmag, temp = kw["extra_stars"]
    assert dirs.shape == (len(vmag), 3) and temp.shape == vmag.shape
    assert np.allclose(np.linalg.norm(dirs, axis=1), 1.0)
    assert kw["mag_range"][0] == pytest.approx(6.6)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def test_catalogue_counts_and_magnitudes():
    assert len(rs.load_catalog()) >= 9090
    dirs, vmag, temp = rs.catalog_stars(6.6)
    assert 8500 <= len(vmag) <= 9100                     # actual 8777
    assert dirs.shape == (len(vmag), 3) and temp.shape == vmag.shape
    assert np.allclose(np.linalg.norm(dirs, axis=1), 1.0)
    assert vmag.min() == pytest.approx(-1.46)            # Sirius
    assert vmag.max() <= 6.6
    assert 18 <= (vmag < 1.5).sum() <= 26                # the "first magnitude" stars (actual 22)
    counts = np.histogram(vmag, bins=np.arange(-1.0, 7.0))[0]   # [-1,0) ... [5,6)
    assert np.all(np.diff(counts) > 0)
    assert 2.0 < counts[-1] / counts[-2] < 4.5           # ~10^0.5 per magnitude
    # full sphere: stars below the horizon are kept
    below = (dirs[:, 1] < 0).mean()
    assert 0.3 < below < 0.6
    assert len(rs.catalog_stars(3.0)[1]) < len(rs.catalog_stars(5.0)[1]) < len(vmag)


def test_temperatures():
    assert float(rs.bv_to_temperature(0.65)) == pytest.approx(5780, abs=30)   # the Sun
    _, _, temp = rs.catalog_stars(6.6)
    assert np.all(np.isfinite(temp)) and temp.min() >= 1000 and temp.max() <= 60000
    assert rs.star_info("Antares")["temp_K"] < 4000        # red supergiant
    assert rs.star_info("Betelgeuse")["temp_K"] < 4000
    assert rs.star_info("Rigel")["temp_K"] > 10000          # blue
    assert rs.star_info("Spica")["temp_K"] > 15000
    assert 9000 <= rs.star_info("Vega")["temp_K"] <= 11000


def test_parsers():
    assert rs.parse_ra("00h 05m 09.9s") == pytest.approx(15 * (5 / 60 + 9.9 / 3600))
    assert rs.parse_ra("17:45:40.04") == pytest.approx(266.41683, abs=1e-4)
    assert rs.parse_dec("+45° 13′ 45″") == pytest.approx(45 + 13 / 60 + 45 / 3600)
    assert rs.parse_dec("-00° 30′ 11″") == pytest.approx(-(30 / 60 + 11 / 3600))
    assert rs.parse_dec("−29 00 28.1") == pytest.approx(-29.00781, abs=1e-4)
    assert rs.parse_dec(-12.5) == -12.5


def test_named_star_lookups():
    for name in rs.PROPER_NAMES:
        assert rs.named_star(name) is not None, name
    vega = rs.named_star("Vega")
    for alias in ("vega", "VEGA", "alpha Lyr", "Alp Lyr", "HR 7001", "3Alp Lyr"):
        assert np.allclose(rs.named_star(alias), vega), alias
    assert rs.star_info("Polaris")["hr"] == 424
    assert rs.star_info("Antares")["hr"] == 6134
    assert rs.star_info("Sirius")["vmag"] == pytest.approx(-1.46)
    assert rs.star_info("kentaurus")["hr"] == 5459        # substring of 'Rigil Kentaurus'
    assert rs.star_info("Acrux")["hr"] == 4730            # brighter component of alpha Cru
    assert rs.named_star("Not A Star") is None
    assert rs.named_star("") is None


def test_asterisms_resolve():
    lines = rs.asterism_lines()
    for name, strokes in rs.ASTERISMS.items():
        assert [len(p) for p in lines[name]] == [len(s) for s in strokes], name


def test_catalogue_own_names():
    # names that only the catalogue's 'Star names' remarks know about
    assert rs.star_info("Wega")["hr"] == 7001
    assert rs.star_info("lodestar")["hr"] == 424
    assert rs.star_info("Cor Scorpii")["hr"] == 6134
    assert rs.star_info("Achird")["hr"] == 219                # 'Achird, according to Becvar'
    assert rs.star_info("Baten Kaitos")["hr"] == 539
    assert "Vega" in rs.star_info("Vega")["names"]
    # remarks that are not names do not leak into the alias table
    cat = rs.load_catalog()
    junk = [a for al in cat.aliases for a in al if any(ch.isdigit() for ch in a) or "Becvar" in a]
    assert junk == []


def test_iau_names_agree_with_the_catalogue():
    """The hand-written IAU table must pick the same star as the catalogue's own name
    remarks wherever both know the name. Known, intended differences where the IAU (2016-18)
    settled an old ambiguity differently: 'Toliman' is alpha Cen B for the IAU (the BSC gives it
    to the system), 'Atria' is alpha TrA (the BSC also lists it for alpha Tri) and 'Markeb' is
    kappa Vel (the BSC gives it to HR 2948 in Puppis)."""
    cat = rs.load_catalog()
    checked = 0
    for proper in rs.PROPER_NAMES:
        hits = cat._alias_keys.get(rs._squash(proper), [])
        if not hits or proper in ("Toliman", "Atria", "Markeb"):
            continue
        assert rs.find_star(proper) in hits, proper
        checked += 1
    assert checked >= 100                                    # actual 128


def test_galactic_frame_matches_catalogue_glon_glat():
    """Independent check of the parser *and* the galactic frame: BSC5 lists every star's
    galactic coordinates (computed by the catalogue makers)."""
    import json
    with open(rs.CATALOG_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    ra, dec, gl, gb = [], [], [], []
    for rec in data:
        if rec.get("GLON") and rec.get("GLAT"):
            ra.append(rs.parse_ra(rec["RA"]))
            dec.append(rs.parse_dec(rec["Dec"]))
            gl.append(float(rec["GLON"]))
            gb.append(float(rec["GLAT"]))
    err = rs.angle_deg(rs.equatorial_to_world(ra, dec), rs.galactic_to_world(gl, gb))
    assert len(err) > 9000
    assert np.median(err) < 0.01                              # actual 0.0039 deg
    assert np.percentile(err, 99) < 0.03                      # actual 0.0105 deg


def test_record_parsing_is_robust():
    recs = [
        {"HR": "1", "RA": "00h 05m 09.9s", "Dec": "+45° 13′ 45″", "Vmag": "6.70", "B-V": "+0.07", "K": "9750"},
        {"HR": "2", "RA": "12h 00m 00s", "Dec": "-10° 00′ 00″", "Vmag": "3.0", "B-V": "+0.65"},   # no K
        {"HR": "3", "RA": "06h 00m 00s", "Dec": "+00° 30′ 00″", "Vmag": "4.0"},                   # no colour
        {"HR": "4", "RA": "18h 00m 00s", "Dec": "−20 30 00", "Vmag": " 2.5 ", "K": "", "B-V": "junk",
         "Name": "Alp Foo", "Common": "Testar"},
        {"HR": "5", "RA": "garbage", "Dec": "+10° 00′ 00″", "Vmag": "1.0"},                       # skipped
        {"HR": "6", "RA": "01h 00m 00s", "Dec": "+10° 00′ 00″"},                                   # no Vmag
        {"HR": "7", "RA": "02h 00m 00s", "Dec": "+20° 00′ 00″", "Vmag": "5.0",
         "Notes": "[{'Category': 'Star names', 'Remark': 'FOOBAR; Bazstar, according to Becvar.'}]"},
        "not a record",
    ]
    cat = rs.Catalog(recs)
    assert list(cat.hr) == [1, 2, 3, 4, 7]
    assert cat.temp[0] == 9750.0
    assert cat.temp[1] == pytest.approx(float(rs.bv_to_temperature(0.65)))
    assert cat.temp[2] == rs.DEFAULT_TEMP_K and cat.temp[3] == rs.DEFAULT_TEMP_K
    assert cat.dec[3] == pytest.approx(-20.5) and cat.ra[3] == pytest.approx(270.0)
    assert cat.by_alias("testar") == 3 and cat.by_designation("Alp Foo") == 3
    assert cat.aliases[4] == ("Foobar", "Bazstar")
    assert np.allclose(np.linalg.norm(cat.world, axis=1), 1.0)


def test_real_stars_land_in_the_galaxy_cube():
    """End to end: build the renderer's background cube with the real stars (scene frame of
    the overworld black hole) and check its brightest texels are the brightest real stars."""
    w2s = bh.world_to_scene(bh.mc_direction(0, -24))
    size = 1024                       # bh._splat_stars needs sigma = 0.75 * size / 1024 >~ 0.75 px
    cube = bh.make_galaxy(size, 5, n_stars=2000, **rs.make_galaxy_kwargs(w2s))
    lum = cube @ bh.LUMA
    order = np.argsort(lum.ravel())[::-1][:200]
    peaks = []
    for f, v, u in zip(*np.unravel_index(order, lum.shape)):
        d = bh.cube_face_dirs(size, f)[v, u] @ w2s      # scene -> world
        if all(rs.angle_deg(d, p) > 0.5 for p in peaks):
            peaks.append(d)
        if len(peaks) == 5:
            break
    expect = ["Sirius", "Canopus", "Rigil Kentaurus", "Arcturus", "Vega"]
    for p in peaks:
        assert min(rs.angle_deg(p, rs.named_star(s)) for s in expect) < 0.1


def test_allsky_preview_renders(tmp_path):
    out = rs.render_allsky_preview(str(tmp_path / "sky.png"), size=500, mag_limit=4.5)
    from PIL import Image
    img = np.asarray(Image.open(out).convert("RGB"), dtype=float)
    assert img.shape == (500, 500, 3) and img.max() > 200
