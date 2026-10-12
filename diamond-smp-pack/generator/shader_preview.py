"""Preview the Shader Sky add-on by running its real shaders in WebGL (headless Chromium).

    python shader_preview.py          # writes previews/shader_sky*.png/.gif
    python shader_preview.py --check  # also checks star positions against the catalogue

The harness reproduces what vanilla Minecraft feeds those shaders: the sky disc mesh
(a fan at y = 16, radius 512), the 1500-quad star mesh drawn with an index buffer,
additive star blending with back-face culling, and the same matrices: view =
rotX(pitch) * rotY(yaw - 180), stars = view * rotY(-90) * rotX(sky angle). The
1.21.9-1.21.11 overlay sources are used, with the Minecraft includes swapped for
plain WebGL uniforms. Needs node with the `playwright` package and a Chromium.
"""

import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import blackhole as bh
import preview
import real_sky
import shader_sky as ss

HERE = Path(__file__).resolve().parent
PREVIEWS = HERE.parent / "previews"
OVERLAY = "shader_sky_1_21_9"
NEAR, FAR = 0.05, 1024.0

FOG_GLSL = """
uniform vec4 FogColor;
uniform float FogEnvironmentalStart;
uniform float FogEnvironmentalEnd;
uniform float FogRenderDistanceStart;
uniform float FogRenderDistanceEnd;
uniform float FogSkyEnd;
uniform float FogCloudsEnd;
"""
STUBS = {
    "dynamictransforms.glsl": "uniform mat4 ModelViewMat;\nuniform vec4 ColorModulator;\n",
    "projection.glsl": "uniform mat4 ProjMat;\n",
    "globals.glsl": "uniform float GameTime;\n",
}


def webgl_source(src, quality):
    """Turn a 1.21.x core shader into WebGL2 GLSL ES 3.00."""
    files = ss.overlay_files(quality)
    ours = {n: files[f"{OVERLAY}/{ss.SHADERS}/include/{n}"] for n in ("diamond_blackhole.glsl", "diamond_starfield.glsl")}
    vanilla_fog = (ss.VANILLA / "mc_1.21.11" / ss.SHADERS / "include" / "fog.glsl").read_text()
    fog_funcs = vanilla_fog[vanilla_fog.index("float linear_fog_value"):]
    ours["fog.glsl"] = FOG_GLSL + fog_funcs
    ours.update(STUBS)
    out = ss.resolve_includes(src, "1.21.11", ours)
    return out.replace("#version 330", "#version 300 es\nprecision highp float;\nprecision highp int;", 1)


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def mat4(m3):
    m = np.eye(4)
    m[:3, :3] = m3
    return m


def view_matrix(yaw, pitch):
    """Minecraft's camera: world -> view (the inverse of rotationYXZ(pi - yaw, -pitch, 0))."""
    return rot_x(math.radians(pitch)) @ rot_y(math.radians(yaw) - math.pi)


def star_matrix(yaw, pitch, sky_angle):
    return view_matrix(yaw, pitch) @ rot_y(-math.pi / 2) @ rot_x(math.radians(sky_angle))


def projection(fov_y, aspect):
    f = 1 / math.tan(math.radians(fov_y) / 2)
    return np.array([[f / aspect, 0, 0, 0], [0, f, 0, 0],
                     [0, 0, (FAR + NEAR) / (NEAR - FAR), 2 * FAR * NEAR / (NEAR - FAR)], [0, 0, -1, 0]])


def gl(m):
    return [float(x) for x in np.asarray(m).T.ravel()]     # column-major for uniformMatrix4fv


def star_mesh(n=1500, seed=10842):
    """Vanilla-like star quads (positions do not matter to Diamond SMP's shader)."""
    rng = np.random.default_rng(seed)
    pos = []
    for _ in range(n):
        d = bh.normalize(rng.standard_normal(3)) * 100
        t1 = bh.normalize(np.cross(d, [0.0, 1.0, 0.0] if abs(d[1]) < 90 else [1.0, 0.0, 0.0]))
        t2 = np.cross(bh.normalize(d), t1)
        s = rng.uniform(0.15, 0.25)
        for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pos.append(d + s * (a * t1 + b * t2))
    return [float(x) for x in np.array(pos).ravel()]


PAGE = """<!doctype html><html><body style="margin:0;background:#000"><canvas id="c"></canvas><script>
const S = __SOURCES__;
const STAR_POS = new Float32Array(__STARS__);
const canvas = document.getElementById('c');
const gl = canvas.getContext('webgl2', {preserveDrawingBuffer: true, antialias: false, alpha: false});
function shader(type, src, name) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(name + ': ' + gl.getShaderInfoLog(s));
  return s;
}
function program(vs, fs, name) {
  const p = gl.createProgram();
  gl.attachShader(p, shader(gl.VERTEX_SHADER, vs, name + '.vsh'));
  gl.attachShader(p, shader(gl.FRAGMENT_SHADER, fs, name + '.fsh'));
  gl.bindAttribLocation(p, 0, 'Position'); gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(name + ' link: ' + gl.getProgramInfoLog(p));
  return p;
}
let progs = null, discVao, starVao;
function setup() {
  progs = {sky: program(S.sky_vsh, S.sky_fsh, 'sky'), stars: program(S.stars_vsh, S.stars_fsh, 'stars')};
  // vanilla sky disc: centre (0, 16, 0) and a ring of radius 512, as a triangle fan
  const disc = [0, 16, 0];
  for (let i = -180; i <= 180; i += 45) disc.push(512 * Math.cos(i * Math.PI / 180), 16, 512 * Math.sin(i * Math.PI / 180));
  discVao = gl.createVertexArray(); gl.bindVertexArray(discVao);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(disc), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
  starVao = gl.createVertexArray(); gl.bindVertexArray(starVao);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ARRAY_BUFFER, STAR_POS, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
  const quads = STAR_POS.length / 12, idx = new Uint16Array(quads * 6);   // vanilla QUADS index order
  for (let q = 0; q < quads; q++) idx.set([4*q, 4*q+1, 4*q+2, 4*q+2, 4*q+3, 4*q], 6*q);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
  starVao.count = idx.length;
}
function uniforms(p, u) {
  for (const [k, v] of Object.entries(u)) {
    const loc = gl.getUniformLocation(p, k); if (loc === null) continue;
    if (v.length === 16) gl.uniformMatrix4fv(loc, false, v);
    else if (v.length === 4) gl.uniform4fv(loc, v);
    else if (v.length === 3) gl.uniform3fv(loc, v);
    else gl.uniform1f(loc, v[0]);
  }
}
window.renderFrame = (f) => {
  if (!progs) setup();
  canvas.width = f.w; canvas.height = f.h; gl.viewport(0, 0, f.w, f.h);
  gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.disable(gl.CULL_FACE);
  gl.clearColor(f.fog[0], f.fog[1], f.fog[2], 1); gl.clear(gl.COLOR_BUFFER_BIT);
  const common = {ProjMat: f.proj, GameTime: [f.time], FogColor: f.fog, FogSkyEnd: [f.skyEnd],
                  FogEnvironmentalStart: [0], FogEnvironmentalEnd: [f.skyEnd], FogRenderDistanceStart: [f.skyEnd],
                  FogRenderDistanceEnd: [f.skyEnd], FogCloudsEnd: [f.skyEnd]};
  if (f.sky) {
    gl.useProgram(progs.sky);
    uniforms(progs.sky, Object.assign({ModelViewMat: f.view, ColorModulator: f.skyColor}, common));
    gl.bindVertexArray(discVao); gl.drawArrays(gl.TRIANGLE_FAN, 0, 10);
  }
  if (f.stars && f.starB > 0) {
    gl.useProgram(progs.stars);
    uniforms(progs.stars, Object.assign({ModelViewMat: f.starView, ColorModulator: [f.starB, f.starB, f.starB, f.starB]}, common));
    gl.enable(gl.BLEND); gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE, gl.ONE, gl.ZERO);
    gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK); gl.frontFace(f.frontFace === 'cw' ? gl.CW : gl.CCW);
    if (f.noCull) gl.disable(gl.CULL_FACE);
    gl.bindVertexArray(starVao); gl.drawElements(gl.TRIANGLES, starVao.count, gl.UNSIGNED_SHORT, 0);
  }
  gl.finish();
  return canvas.toDataURL('image/png');
};
window.ready = true;
</script></body></html>
"""

RUNNER = """
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [page_path, frames_path] = process.argv.slice(2);
  const browser = await chromium.launch({args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
  const page = await browser.newPage();
  page.on('console', m => console.log('page:', m.text()));
  await page.goto('file://' + page_path);
  await page.waitForFunction(() => window.ready === true);
  const frames = JSON.parse(fs.readFileSync(frames_path, 'utf8'));
  for (const f of frames) {
    const t0 = Date.now();
    const url = await page.evaluate(f => window.renderFrame(f), f);
    fs.writeFileSync(f.out, Buffer.from(url.split(',')[1], 'base64'));
    console.log(`${f.out} ${f.w}x${f.h} ${Date.now() - t0} ms`);
  }
  await browser.close();
})().catch(e => { console.error(e.message || e); process.exit(1); });
"""


def frame(yaw, pitch, w=960, h=540, fov=70.0, sky=(0.47, 0.65, 1.0), fog=(0.75, 0.85, 1.0, 1.0),
          star_b=0.0, sky_angle=180.0, time=0.37, sky_end=192.0, stars=True, sky_pass=True, **extra):
    """One render: camera yaw/pitch (Minecraft's convention), vanilla sky/fog colours, vanilla's
    star brightness (0..0.5) and sky angle (degrees, 0 = noon), and GameTime."""
    f = dict(w=w, h=h, view=gl(mat4(view_matrix(yaw, pitch))),
             starView=gl(mat4(star_matrix(yaw, pitch, sky_angle))), proj=gl(projection(fov, w / h)),
             skyColor=[*sky, 1.0], fog=list(fog), starB=star_b, time=time, skyEnd=sky_end, stars=stars,
             sky=sky_pass)
    f.update(extra)
    return f


def check_es(sources):
    """Compile the WebGL sources with glslang first: its messages are clearer than the browser's."""
    exe = shutil.which("glslangValidator")
    if exe is None:
        return
    tmp = HERE / ".cache" / "shader_check"
    tmp.mkdir(parents=True, exist_ok=True)
    for name, src in sources.items():
        path = tmp / f"webgl_{name}.{'vert' if name.endswith('vsh') else 'frag'}"
        path.write_text(src)
        res = subprocess.run([exe, str(path)], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"WebGL {name} does not compile:\n{res.stdout[-3000:]}")


def render(frames, quality="high"):
    """Render frame dicts (see frame()) with the real shaders; returns the images as arrays."""
    files = ss.overlay_files(quality)
    sources = {f"{p}_{s}": webgl_source(files[f"{OVERLAY}/{ss.SHADERS}/core/{p}.{s}"], quality)
               for p in ("sky", "stars") for s in ("vsh", "fsh")}
    check_es(sources)
    work = Path(tempfile.mkdtemp(prefix="shader_preview_", dir=HERE / ".cache"))
    page = work / "page.html"
    page.write_text(PAGE.replace("__SOURCES__", json.dumps(sources)).replace("__STARS__", json.dumps(star_mesh())))
    frames = [dict(f, out=str(work / f"frame_{i:03d}.png")) for i, f in enumerate(frames)]
    (work / "frames.json").write_text(json.dumps(frames))
    (work / "run.js").write_text(RUNNER)
    res = subprocess.run(["node", str(work / "run.js"), str(page), str(work / "frames.json")],
                         capture_output=True, text=True, timeout=3600)
    if res.returncode != 0:
        raise RuntimeError(res.stdout[-2000:] + res.stderr[-4000:])
    if "-v" in sys.argv:
        print(res.stdout)
    imgs = [np.array(Image.open(f["out"]).convert("RGB")) for f in frames]
    shutil.rmtree(work, ignore_errors=True)
    return imgs


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

# Vanilla-like sky / fog colours (plains biome) for a few times of day.
DAY = dict(sky=(0.47, 0.65, 1.0), fog=(0.73, 0.83, 1.0, 1.0), star_b=0.0, sky_angle=0.0)
SUNSET = dict(sky=(0.30, 0.38, 0.62), fog=(0.85, 0.55, 0.42, 1.0), star_b=0.06, sky_angle=78.0)
NIGHT = dict(sky=(0.0, 0.0, 0.0), fog=(0.025, 0.03, 0.06, 1.0), star_b=0.5, sky_angle=180.0)
RAIN_DAY = dict(sky=(0.40, 0.45, 0.535), fog=(0.42, 0.45, 0.52, 1.0), star_b=0.0, sky_angle=0.0)


def ground(img, yaw, pitch, fov, night):
    """Blocky hills in front of the sky, like preview.py."""
    dirs = preview.player_view(yaw, pitch, img.shape[1], img.shape[0], fov)
    return preview.add_ground(img.astype(float), dirs, (12, 14, 18) if night else (62, 92, 52))


def stills(quality="high"):
    w, h = 960, 540
    shots = [
        ("Day: the hole hangs in the blue sky", 0, -22, 70.0, DAY, ()),
        ("Sunset: the first stars come out", 0, -22, 70.0, SUNSET, ()),
        ("Night: real stars + Milky Way, bent into a ring", 0, -22, 70.0, NIGHT, ()),
        ("Night, north-west: the real Big Dipper", 135, -30, 80.0, NIGHT,
         ("Polaris", "Kochab", "Dubhe", "Merak", "Phecda", "Megrez", "Alioth", "Mizar", "Alkaid", "Arcturus",
          "Capella")),
    ]
    frames = [frame(yaw, pitch, w, h, fov=fov, **cfg) for _, yaw, pitch, fov, cfg, _ in shots]
    imgs = render(frames, quality)
    panels = []
    for (text, yaw, pitch, fov, cfg, names), img in zip(shots, imgs):
        img = ground(img, yaw, pitch, fov, cfg["star_b"] > 0.2)
        im = Image.fromarray(preview.label(img, text).astype(np.uint8))
        draw = ImageDraw.Draw(im)
        for name in names:
            pos = preview.project(image_direction(real_sky.named_star(name)), yaw, pitch, w, h, fov)
            if pos is not None:
                draw.text((pos[0] + 7, pos[1] - 8), name, fill=(170, 200, 255), font=preview.font(13))
        panels.append(np.array(im))
    top = np.concatenate(panels[:2], axis=1)
    bottom = np.concatenate(panels[2:], axis=1)
    out = np.concatenate([top, bottom], axis=0).astype(np.uint8)
    path = PREVIEWS / ("shader_sky.png" if quality == "high" else f"shader_sky_{quality}.png")
    Image.fromarray(out).save(path, optimize=True)
    print(f"wrote {path.relative_to(HERE.parent)}")
    return imgs


def animation(n=32, quality="high"):
    """One full animation cycle of the disk (8 s in game) at night, close up."""
    w, h, fov = 520, 320, 42.0
    yaw, pitch = 0.0, -24.0
    cycle = 1.0 / ss.TIME_SCALE
    t0 = 0.4
    frames = [frame(yaw, pitch, w, h, fov=fov, time=t0 + cycle * i / n, **NIGHT) for i in range(n)]
    imgs = render(frames, quality)
    pil = [Image.fromarray(i.astype(np.uint8)).quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=0)
           for i in imgs]
    path = PREVIEWS / "shader_sky_night.gif"
    pil[0].save(path, save_all=True, append_images=pil[1:], duration=int(8000 / n), loop=0, optimize=True)
    print(f"wrote {path.relative_to(HERE.parent)} ({path.stat().st_size / 1e6:.1f} MB)")
    return imgs


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def image_direction(star_dir):
    """Where a far-away star appears on the sky after lensing (primary image)."""
    th_sh, x0, x1, psi_t, _ = ss.lens_table()
    h = ss.BH_DIR
    c = float(np.clip(np.dot(star_dir, h), -1, 1))
    beta = math.acos(c)                          # the star's true angle from the hole
    # psi(theta) rises monotonically from the shadow edge to pi: invert on a fine grid
    xs = np.linspace(x0, x1, 20000)
    psi = np.interp(xs, np.linspace(x0, x1, len(psi_t)), psi_t)
    x = np.interp(beta, psi, xs)
    theta = th_sh * (1 + math.exp(x))
    e = bh.normalize(star_dir - c * h)
    return math.cos(theta) * h + math.sin(theta) * e


def check(quality="high"):
    """Bright stars must land where the catalogue (plus lensing) says; they must not move when
    only the time of day (the vanilla star matrix) changes; the layer must draw exactly once
    whatever the face culling; and facing exactly west (where the star matrix cannot tell the
    pitch) must fade the stars out instead of drawing them wrongly."""
    w, h, fov = 960, 540, 70.0
    tests = [(180, -38, 180.0), (0, -22, 180.0), (90.3, -40, 150.0), (-60, -90, 200.0), (25, -60, 240.0),
             (-89.9, -30, 170.0)]
    night = dict(sky_pass=False, sky=(0, 0, 0), fog=(0, 0, 0, 1), star_b=0.5, time=0.0)
    frames = []
    for yaw, pitch, angle in tests:
        frames.append(frame(yaw, pitch, w, h, fov=fov, sky_angle=angle, **night))
        frames.append(frame(yaw, pitch, w, h, fov=fov, sky_angle=angle + 97.0, **night))
    frames.append(frame(0, -22, w, h, fov=fov, noCull=True, **night))
    frames.append(frame(0, -22, w, h, fov=fov, frontFace="cw", **night))
    frames.append(frame(90, -40, w, h, fov=fov, sky_angle=150.0, **night))
    imgs = render(frames, quality)
    dirs, _, _ = real_sky.catalog_stars(2.6)
    errors = []
    for k, (yaw, pitch, angle) in enumerate(tests):
        a, b = imgs[2 * k].astype(float), imgs[2 * k + 1].astype(float)
        moved = np.abs(a - b).max()
        assert moved <= 2, f"stars moved when only the time of day changed ({yaw}, {pitch}): {moved}"
        lum = a.mean(-1)
        for d in dirs:
            seen = image_direction(d)
            if seen[1] < 0.12:          # low stars are dimmed by the air (and may be bent below the horizon)
                continue
            p = preview.project(seen, yaw, pitch, w, h, fov)
            if p is None or not (8 < p[0] < w - 8 and 8 < p[1] < h - 8):
                continue
            x, y = p[0] - 0.5, p[1] - 0.5
            ix, iy = int(round(x)), int(round(y))
            win = lum[iy - 1:iy + 2, ix - 1:ix + 2] - lum[iy - 3:iy + 4, ix - 3:ix + 4].min()   # minus the sky glow
            if win.sum() <= 0:
                errors.append(99.0)
                continue
            yy, xx = np.mgrid[-1:2, -1:2]
            errors.append(math.hypot(ix + (win * xx).sum() / win.sum() - x, iy + (win * yy).sum() / win.sum() - y))
    base = imgs[2].astype(float)
    for name, img in (("no culling", imgs[-3]), ("clockwise front faces", imgs[-2])):
        diff = np.abs(img.astype(float) - base).max()
        assert diff <= 2, f"{name}: the full-screen layer drew {diff} differently (should draw exactly once)"
    west = imgs[-1].max()
    assert west <= 2, f"facing exactly west the stars should fade out, max {west}"
    worst = max(errors)
    print(f"star check ({quality}): {len(errors)} bright stars within {worst:.2f} px of their catalogue + "
          f"lensing positions; fixed against the time of day; drawn exactly once with any culling; "
          f"faded out facing exactly west")
    assert len(errors) > 30 and worst < 0.6, (len(errors), worst)
    return worst


def main():
    PREVIEWS.mkdir(exist_ok=True)
    stills("high")
    animation()
    if "--check" in sys.argv:
        check()


if __name__ == "__main__":
    main()
