"""Tests for the coloured lighting (lighting.py): the core-shader overlays and the OptiFine files."""

import io
import json
import os
import shutil
import sys
import zipfile

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import light_boost  # noqa: E402
import lighting as L  # noqa: E402


def have_vanilla():
    return all((L.HERE / ".cache" / f"lightmap_{tag}.fsh").exists() for _, tag, *_ in L.VARIANTS)


def warmth(c):
    return c[..., 0] / np.maximum(c[..., 2], 1e-6)


def test_torches_are_warmer_and_moonlight_bluer_than_vanilla():
    for scene in ("day", "night"):
        v, c = L.lightmap(scene, False, boost=False), L.lightmap(scene, True, boost=False)
        # torch-lit, no sky: amber
        assert np.all(warmth(c[0, 6:13]) > warmth(v[0, 6:13])), scene
    v, c = L.lightmap("night", False, boost=False), L.lightmap("night", True, boost=False)
    # moonlit, no torch: blue rather than vanilla's purple (less red, more green, same blue)
    assert c[15, 0, 0] < v[15, 0, 0] and c[15, 0, 1] > v[15, 0, 1] and c[15, 0, 2] >= v[15, 0, 2] - 0.02
    # golden hour: at dusk the sky light turns warm (vanilla's is already turning blue)
    dusk = np.array(L.SCENES["dusk"]["sky_color"])
    assert warmth(L.sky_light(dusk)) > 1.05 > warmth(dusk)
    assert abs(L.sky_light(dusk) @ L.LUMA - dusk @ L.LUMA) < 0.05
    assert warmth(L.sky_light(np.ones(3))) == pytest.approx(1.0)


def test_nether_red_end_violet():
    n, e = L.lightmap("nether", True, boost=False)[0, 0], L.lightmap("end", True, boost=False)[0, 0]
    assert n[0] > n[1] > n[2], "a red-orange haze in the Nether"
    assert e[2] > e[1] and e[0] > e[1], "a violet haze in the End"


def test_brightness_stays_close_to_vanilla():
    for scene in L.SCENES:
        v, c = L.lightmap(scene, False, boost=False), L.lightmap(scene, True, boost=False)
        lv, lc = (v @ L.LUMA).mean(), (c @ L.LUMA).mean()
        assert abs(lc - lv) < 0.06, (scene, lv, lc)


@pytest.mark.skipif(not have_vanilla(), reason="vanilla lightmap shaders not cached")
def test_overlays_patch_every_version_and_keep_the_boost():
    files = L.overlay_files()
    assert sorted(files) == sorted(f"{d}/{L.SHADER}" for d, *_ in L.VARIANTS)
    for src in files.values():
        for call in ("dsl_torch(block_brightness)", "dsl_sky_light(lightmapInfo.SkyLightColor)"):
            assert src.count(call) == 1, call
        assert src.count("dsl_haze(") == 2, "defined once, used once"
        assert "Diamond SMP light boost" in src
        assert src.index("Diamond SMP light boost") < src.index("fragColor = vec4(color, 1.0);")
    spans = [(tuple(e["min_format"]), tuple(e["max_format"])) for e in L.overlay_entries()]
    assert spans == [(tuple(lo), tuple(hi)) for _, _, lo, hi in light_boost.VARIANTS]


@pytest.mark.skipif(not have_vanilla() or shutil.which("glslangValidator") is None,
                    reason="needs glslangValidator and the cached vanilla shaders")
def test_overlays_compile():
    assert L.validate(verbose=False)


def test_unexpected_vanilla_layout_is_refused():
    with pytest.raises(ValueError):
        L.colored("void main() { fragColor = vec4(color, 1.0); }", "ambient_factor")


def test_optifine_lightmaps():
    files = L.optifine_lightmaps()
    names = {n.rsplit("/", 1)[1] for n in files}
    assert names == {"world0.png", "world0_rain.png", "world0_thunder.png", "world-1.png", "world1.png"}
    for name, data in files.items():
        assert name.startswith("assets/minecraft/optifine/lightmap/")
        img = np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(float) / 255
        assert img.shape == (64, L.PALETTE_WIDTH, 3), "64 tall: sky, torch, and both again for night vision"
        sky, torch = img[:16], img[16:32]
        assert np.all(np.diff(sky.mean(-1), axis=0) >= -1e-6), "brighter with more sky light"
        assert np.all(np.diff(torch.mean(-1), axis=0) >= -1e-6), "brighter with more torch light"
        assert np.all(warmth(torch[4:11]) > 1.3), "torches are warm (the brightest rows go warm white)"
        assert img[32:].mean() > img[:32].mean(), "night vision brightens"
    world0 = np.asarray(Image.open(io.BytesIO(files["assets/minecraft/optifine/lightmap/world0.png"])))
    night, noon = world0[15, 0].astype(float), world0[15, -2].astype(float)
    assert noon.mean() > 3 * night.mean() and night[2] > night[0], "dark blue nights, bright days"


def test_optifine_properties():
    files = L.optifine_files()
    em = files["assets/minecraft/optifine/emissive.properties"].decode()
    assert "suffix.emissive=_e" in em
    nat = files["assets/minecraft/optifine/natural.properties"].decode()
    for line in nat.splitlines():
        if line and not line.startswith("#"):
            key, val = (x.strip() for x in line.split("="))
            assert val in {"4", "2", "F", "4F", "2F"} and key.replace("_", "").isalnum(), line
    bg = files["assets/minecraft/optifine/bettergrass.properties"].decode()
    assert "grass=true" in bg and "texture.grass=block/grass_block_top" in bg


@pytest.mark.skipif(not have_vanilla(), reason="vanilla lightmap shaders not cached")
def test_addon_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "ROOT", tmp_path)
    out = L.build_addon()
    with zipfile.ZipFile(out) as z:
        meta = json.loads(z.read("pack.mcmeta"))
        names = set(z.namelist())
    assert meta["pack"]["min_format"] == L.MIN_FORMAT and meta["pack"]["max_format"] == L.MAX_FORMAT
    assert [e["directory"] for e in meta["overlays"]["entries"]] == [v[0] for v in L.VARIANTS]
    assert {f"{d}/{L.SHADER}" for d, *_ in L.VARIANTS} <= names
