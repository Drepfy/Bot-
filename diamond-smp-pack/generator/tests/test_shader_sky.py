"""Tests for the Shader Sky add-on (shader_sky.py) and its WebGL harness (shader_preview.py)."""

import json
import math
import os
import shutil
import subprocess
import sys
import zipfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blackhole as bh  # noqa: E402
import real_sky  # noqa: E402
import shader_sky as ss  # noqa: E402


# --- the lens table --------------------------------------------------------


def test_shadow_edge_is_where_rays_start_getting_caught():
    th = ss.shadow_angle()
    assert math.degrees(th) == pytest.approx(6.78, abs=0.01)
    inside, outside = ss.escape_angles(np.array([th * (1 - 1e-4), th * (1 + 1e-3)]))
    assert np.isnan(inside) and np.isfinite(outside)


def test_escape_angles_converge():
    theta = np.radians([7.0, 9.0, 15.0, 34.0, 90.0, 150.0])
    a = ss.escape_angles(theta, k=0.002)
    b = ss.escape_angles(theta, k=0.001)
    assert np.max(np.abs(a - b)) < 1e-6


def test_weak_bending_far_from_the_hole():
    # The ray model is the exact photon orbit; far from the hole the bending must approach
    # the weak-field result for a camera at finite distance, (1/b)(1 - s0 (2 s0^2 + 3 b^2) / (2 r0^3)).
    for deg in (60.0, 90.0, 120.0):
        th = math.radians(deg)
        b = ss.DISTANCE * math.sin(th)
        s0 = -ss.DISTANCE * math.cos(th)
        weak = (1 / b) * (1 - s0 * (2 * s0 ** 2 + 3 * b ** 2) / (2 * ss.DISTANCE ** 3))
        bend = th - ss.escape_angles(th)
        assert bend == pytest.approx(weak, rel=0.12), deg
    assert ss.escape_angles(math.pi) == pytest.approx(math.pi, abs=1e-9)


def test_lens_table_is_monotonic_and_smooth():
    th_sh, x0, x1, psi, dpsi = ss.lens_table()
    assert np.all(np.diff(psi) > 0), "each far-sky angle must appear once per winding"
    assert psi[0] < -2 * math.pi, "rays near the edge wrap round the hole more than once"
    assert psi[-1] == pytest.approx(math.pi, abs=1e-6)
    # d psi / dx agrees with the table's own slope
    x = np.linspace(x0, x1, len(psi))
    slope = np.gradient(psi, x)
    assert np.allclose(dpsi[2:-2], slope[2:-2], rtol=0.03, atol=0.02)
    # near the edge the photon ring is a log spiral: d psi / dx -> 1
    assert dpsi[0] == pytest.approx(1.0, abs=0.01)


def test_einstein_ring_is_where_the_galactic_centre_lands():
    th_sh, x0, x1, psi, _ = ss.lens_table()
    x_ring = np.interp(0.0, psi, np.linspace(x0, x1, len(psi)))
    ring = th_sh * (1 + math.exp(x_ring))
    # weak-field Einstein radius for a source at infinity: sqrt(2 r_s / D); strong field adds a bit
    assert 1.0 < ring / math.sqrt(2.0 / ss.DISTANCE) < 1.25, math.degrees(ring)
    gc_angle = math.degrees(math.acos(np.dot(bh.normalize(real_sky.GALACTIC_CENTRE_WORLD), ss.BH_DIR)))
    assert gc_angle < 0.1, "Sgr A* sits in front of the galactic centre, so the bulge rings it"


# --- the star tables -------------------------------------------------------


def test_cube_faces_round_trip():
    rng = np.random.default_rng(3)
    d = bh.normalize(rng.standard_normal((5000, 3)))
    f, u, v = ss._cube_face(d)
    assert np.abs(ss.face_dir(f, u, v) - d).max() < 1e-12
    assert np.all(np.abs(u) <= 1) and np.all(np.abs(v) <= 1)


@pytest.mark.parametrize("quality", sorted(ss.QUALITY))
def test_every_star_is_listed_in_every_cell_near_it(quality):
    start, entries = ss.star_tables(ss.QUALITY[quality]["mag_limit"])
    assert start[0] == 0 and start[-1] == len(entries) and np.all(np.diff(start) >= 0)
    dirs = bh.normalize(entries[:, :3])
    temp = (np.linalg.norm(entries[:, :3], axis=1) - 1) * 1e5
    assert temp.min() >= 1999 and temp.max() <= 40001
    stars = {tuple(np.round(d, 9)) for d in dirs}
    # random points within the margin of random stars: their cell must list that star
    rng = np.random.default_rng(5)
    picks = rng.choice(len(dirs), 400)
    margin = math.radians(ss.CELL_MARGIN_DEG) * 0.98
    for k in picks:
        d = dirs[k]
        t = bh.normalize(np.cross(d, rng.standard_normal(3)))
        p = math.cos(margin * rng.uniform()) * d + math.sin(margin * rng.uniform()) * t
        p = bh.normalize(p)
        c = int(ss.cube_cell(p, ss.CELLS))
        listed = dirs[start[c]:start[c + 1]]
        assert np.any(np.abs(listed - d).max(axis=1) < 1e-9), (k, c)
    catalogue = real_sky.catalog_stars(ss.QUALITY[quality]["mag_limit"])[0]
    assert stars == {tuple(np.round(d, 9)) for d in catalogue}, "every catalogue star is in the table"


# --- recovering the camera from vanilla's star matrix ----------------------


def _star_matrix(yaw, pitch, sky_angle):
    import shader_preview as sp
    return sp.star_matrix(yaw, pitch, sky_angle), sp.view_matrix(yaw, pitch)


def _world_ray(mv, view_ray):
    """numpy copy of dsf_world_ray() (without the projection part)."""
    z_axis = bh.normalize(mv[:, 0])
    up = np.array([0.0, -z_axis[2], z_axis[1]])
    n = np.linalg.norm(up)
    trust = float(np.clip((n - 5e-5) / (2e-4 - 5e-5), 0, 1))
    up = up / n if n > 1e-7 else np.array([0.0, 1.0, 0.0])
    if up[1] < -1e-4 or (up[1] <= 1e-4 and up[2] > 0):
        up = -up
    view = np.stack([np.cross(up, z_axis), up, z_axis], axis=1)
    return view.T @ view_ray, trust


def test_camera_is_recovered_from_the_star_matrix():
    rng = np.random.default_rng(11)
    for _ in range(500):
        yaw, pitch, angle = rng.uniform(-180, 180), rng.uniform(-90, 90), rng.uniform(0, 360)
        mv, view = _star_matrix(yaw, pitch, angle)
        mv32 = mv.astype(np.float32).astype(np.float64)        # the game works in float
        ray = bh.normalize(rng.standard_normal(3))
        got, trust = _world_ray(mv32, ray)
        if trust < 1:
            continue
        assert np.abs(got - view.T @ ray).max() < 2e-3, (yaw, pitch, angle)


def test_looking_straight_up_works_and_facing_due_west_fades_out():
    for yaw in (0.0, 37.0, -120.0):
        mv, view = _star_matrix(yaw, -90.0, 200.0)
        got, trust = _world_ray(mv.astype(np.float32).astype(np.float64), np.array([0.0, 0.0, -1.0]))
        assert trust == 1 and np.allclose(got, [0, 1, 0], atol=1e-3), yaw   # straight up is up
    for yaw in (90.0, -90.0):
        mv, _ = _star_matrix(yaw, -30.0, 120.0)
        assert _world_ray(mv.astype(np.float32).astype(np.float64), np.array([0.0, 0.0, -1.0]))[1] == 0


# --- the shaders and the zips ----------------------------------------------


def test_overlays_cover_each_shader_layout_once():
    entries = ss.overlay_entries()
    spans = [(tuple(e["min_format"]), tuple(e["max_format"])) for e in entries]
    assert spans == sorted(spans)
    assert all(lo <= hi for lo, hi in spans)
    assert all(a[1] < b[0] for a, b in zip(spans, spans[1:]))
    assert spans[0][0] == tuple(ss.MIN_FORMAT) and spans[-1][1] == tuple(ss.MAX_FORMAT)


def test_each_overlay_uses_its_versions_conventions():
    files = ss.overlay_files("high")
    for d, _, _, _, style in ss.VARIANTS:
        vsh = files[f"{d}/{ss.SHADERS}/core/stars.vsh"]
        fsh = files[f"{d}/{ss.SHADERS}/core/sky.fsh"]
        if style == "include":
            assert "gl_VertexIndex" in vsh and "#include <minecraft:" in fsh and "layout(location = 2)" in fsh
        else:
            assert "gl_VertexID" in vsh and "#moj_import <minecraft:" in fsh and "layout(" not in fsh
        assert "#version 330" in vsh


@pytest.mark.skipif(shutil.which("glslangValidator") is None, reason="glslangValidator not installed")
@pytest.mark.parametrize("quality", sorted(ss.QUALITY))
def test_shaders_compile_against_every_vanilla_version(quality):
    if not (ss.VANILLA / "mc_1.21.11").exists():
        pytest.skip("vanilla shaders not cached")
    assert ss.validate(quality, verbose=False)


def test_addon_zips(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "ROOT", tmp_path)
    for quality in ss.QUALITY:
        out = ss.build_addon(quality)
        with zipfile.ZipFile(out) as z:
            meta = json.loads(z.read("pack.mcmeta"))
            names = set(z.namelist())
        assert meta["pack"]["min_format"] == ss.MIN_FORMAT and meta["pack"]["max_format"] == ss.MAX_FORMAT
        assert [e["directory"] for e in meta["overlays"]["entries"]] == [v[0] for v in ss.VARIANTS]
        for d, *_ in ss.VARIANTS:
            for f in ("core/sky.vsh", "core/sky.fsh", "core/stars.vsh", "core/stars.fsh",
                      "include/diamond_blackhole.glsl", "include/diamond_starfield.glsl"):
                assert f"{d}/{ss.SHADERS}/{f}" in names
        assert out.stat().st_size < 400_000


def _have_browser():
    if shutil.which("node") is None:
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _have_browser(), reason="needs node + playwright + chromium")
def test_webgl_render_puts_real_stars_in_place():
    import shader_preview as sp
    assert sp.check("high") < 0.6
