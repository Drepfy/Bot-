"""Tests for personal merges (merge_packs.py): Sodium-safe shader cleanup and add-on overlays."""

import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_packs as mp  # noqa: E402

TERRAIN = """#version 330
#moj_import <minecraft:fog.glsl>
#moj_import <minecraft:config.glsl>
#moj_import <minecraft:code/wavy.glsl>
void main() {}
"""
KEPT_SHADER = """#version 330
#moj_import <minecraft:shared.glsl>
void main() {}
"""


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


@pytest.fixture()
def packs(tmp_path, monkeypatch):
    ours = {
        "pack.mcmeta": json.dumps({"pack": {"description": "Diamond SMP", "pack_format": 34,
                                            "supported_formats": [15, 999], "min_format": 15,
                                            "max_format": 999}}),
        "assets/minecraft/textures/environment/sun.png": b"sun",
        "assets/minecraft/optifine/sky/world0/night.png": b"painted",
    }
    make_zip(tmp_path / "Diamond-SMP-Black-Hole-Pack.zip", ours)
    theirs = {
        "pack.mcmeta": json.dumps({"pack": {"description": "Other", "min_format": 69, "max_format": [97, 1]},
                                   "overlays": {"entries": [{"directory": "ov", "min_format": 75, "max_format": 80}]}}),
        "assets/minecraft/shaders/core/terrain.vsh": TERRAIN,
        "assets/minecraft/shaders/terrain.vsh": TERRAIN,
        "ov/assets/minecraft/shaders/core/rendertype_cutout.fsh": TERRAIN,
        "assets/minecraft/shaders/include/config.glsl": "const float a = 1.0;",
        "assets/minecraft/shaders/include/config.glsl.rpo": "{}",
        "assets/minecraft/shaders/include/code/wavy.glsl": "float w() { return 0.0; }",
        "assets/minecraft/shaders/include/shared.glsl": "float s() { return 1.0; }",
        "assets/minecraft/shaders/core/rendertype_entity_glint.fsh": KEPT_SHADER,
        "assets/minecraft/textures/block/stone.png": b"stone",
        "assets/minecraft/textures/environment/sun.png": b"their sun",
        "assets/minecraft/textures/gui/button (copy).png": b"x",
        "assets/minecraft/textures/gui/Bad.png": b"x",
    }
    other = make_zip(tmp_path / "Other.zip", theirs)
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    monkeypatch.setattr(mp.light_boost, "overlay_files",
                        lambda: {"lb/assets/minecraft/shaders/core/lightmap.fsh": "void main() {}"})
    monkeypatch.setattr(mp.shader_sky, "overlay_files",
                        lambda quality="high": {"ss/assets/minecraft/shaders/core/sky.fsh": "void main() {}",
                                                "ss/assets/minecraft/optifine/sky/world0/night.png": b"\x89PNG blank"})
    return other, tmp_path


def read(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_terrain_shaders_and_their_includes_are_left_out(packs):
    other, tmp = packs
    out, report = mp.merge(other, out=tmp / "m.zip", verbose=False)
    files = read(out)
    for gone in ("assets/minecraft/shaders/core/terrain.vsh", "assets/minecraft/shaders/terrain.vsh",
                 "ov/assets/minecraft/shaders/core/rendertype_cutout.fsh",
                 "assets/minecraft/shaders/include/config.glsl", "assets/minecraft/shaders/include/config.glsl.rpo",
                 "assets/minecraft/shaders/include/code/wavy.glsl",
                 "assets/minecraft/textures/gui/button (copy).png", "assets/minecraft/textures/gui/Bad.png"):
        assert gone not in files, gone
        assert gone in report["cleaned"]
    for kept in ("assets/minecraft/shaders/include/shared.glsl",
                 "assets/minecraft/shaders/core/rendertype_entity_glint.fsh",
                 "assets/minecraft/textures/block/stone.png"):
        assert kept in files, kept
    assert files["assets/minecraft/textures/environment/sun.png"] == b"sun", "Diamond SMP wins conflicts"
    txt = files["DIAMOND_SMP_MERGE.txt"].decode()
    assert "terrain.vsh" in txt and "Sodium" in txt
    meta = json.loads(files["pack.mcmeta"])
    assert meta["pack"]["min_format"] == 69 and meta["pack"]["max_format"] == [97, 1]
    assert [e["directory"] for e in meta["overlays"]["entries"]] == ["ov"]


def test_keep_terrain_shaders(packs):
    other, tmp = packs
    out, report = mp.merge(other, out=tmp / "m.zip", keep_terrain_shaders=True, verbose=False)
    files = read(out)
    assert "assets/minecraft/shaders/core/terrain.vsh" in files
    assert "assets/minecraft/shaders/include/config.glsl" in files
    assert "assets/minecraft/textures/gui/Bad.png" not in files      # invalid names always go
    assert set(report["cleaned"]) == {"assets/minecraft/textures/gui/button (copy).png",
                                      "assets/minecraft/textures/gui/Bad.png"}


def test_add_ons_accept_text_and_binary_files(packs):
    other, tmp = packs
    out, _ = mp.merge(other, out=tmp / "m.zip", light_boost_on=True, sky_shader="high", verbose=False)
    files = read(out)
    assert files["lb/assets/minecraft/shaders/core/lightmap.fsh"] == b"void main() {}"
    assert files["ss/assets/minecraft/optifine/sky/world0/night.png"] == b"\x89PNG blank"
    assert files["assets/minecraft/optifine/sky/world0/night.png"] == b"painted"   # older versions keep it
    meta = json.loads(files["pack.mcmeta"])
    dirs = [e["directory"] for e in meta["overlays"]["entries"]]
    assert dirs[0] == "ov" and len(dirs) == 1 + len(mp.light_boost.overlay_entries()) + len(mp.shader_sky.overlay_entries())
    assert "only one sky" in files["DIAMOND_SMP_MERGE.txt"].decode()


def test_packs_without_terrain_shaders_are_untouched():
    files = {"assets/minecraft/shaders/include/x.glsl": b"", "assets/minecraft/shaders/core/sky.fsh": b""}
    assert mp.sodium_unsafe_shaders(files) == {}


def test_invalid_resource_paths():
    files = ["assets/minecraft/textures/a b.png", "assets/Minecraft/x.png", "assets/minecraft/ok_1-2.png",
             "ov/assets/minecraft/textures/(x).png", "README.md", "pack.png"]
    assert mp.invalid_resource_paths(files) == ["assets/Minecraft/x.png", "assets/minecraft/textures/a b.png",
                                                "ov/assets/minecraft/textures/(x).png"]
