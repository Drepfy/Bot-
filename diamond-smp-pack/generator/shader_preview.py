"""Preview the Shader Sky add-on by running its real shaders in WebGL (headless Chromium).

    python shader_preview.py          # writes previews/shader_sky*.png/.gif
    python shader_preview.py --check  # also checks star positions, and day/night/aurora behaviour

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
import night_sky
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


# Looking north at night: the northern lights over the real stars around the pole.
NORTH = (170, -24, 80.0)
NORTH_TIME = 0.425
NORTH_STARS = ("Polaris", "Kochab", "Dubhe", "Merak", "Phecda", "Megrez", "Alioth", "Mizar", "Alkaid", "Schedar",
               "Caph")


def _station_shot():
    """The highest space-station pass of the day: (GameTime, its direction then)."""
    passes = [m for m in ss.satellite_schedule("high") if m["station"]]
    best = max(passes, key=lambda m: m["where"](0.5 * (m["rise"] + m["set"]))[1])
    t = best["rise"] + 0.42 * (best["set"] - best["rise"])
    return t, best["where"](t)


def stills(quality="high"):
    w, h = 960, 540
    t_iss, d_iss = _station_shot()
    alt_iss, az_iss = real_sky.horizontal(d_iss)
    near = {name: d for name, d, _, _ in night_sky.point_sources()}       # not bent by the hole
    near["space station"] = d_iss
    shots = [
        ("Day: vanilla's blue sky, no black hole", 0, -22, 70.0, DAY, (), {}),
        ("Sunset: the black hole fades in", 0, -22, 70.0, SUNSET, (), {}),
        ("Night: the black hole, real stars + Milky Way", 0, -22, 70.0, NIGHT, ("Jupiter",), {}),
        ("Night, north: northern lights + Big Dipper", *NORTH, NIGHT, NORTH_STARS, dict(time=NORTH_TIME)),
        ("Night, west: a great comet, Venus and Mars", 112, -16, 70.0, NIGHT, ("Venus", "Mars", "Comet"),
         dict(time=0.31)),
        ("Night: a space station gliding over", az_iss + 180.0 + 14.0, -alt_iss + 8.0, 70.0, NIGHT,
         ("space station", "Saturn", "Jupiter"), dict(time=t_iss)),
    ]
    frames = [frame(yaw, pitch, w, h, fov=fov, **cfg, **extra) for _, yaw, pitch, fov, cfg, _, extra in shots]
    imgs = render(frames, quality)
    panels = []
    for (text, yaw, pitch, fov, cfg, names, _), img in zip(shots, imgs):
        img = ground(img, yaw, pitch, fov, cfg["star_b"] > 0.2)
        im = Image.fromarray(preview.label(img, text).astype(np.uint8))
        draw = ImageDraw.Draw(im)
        for name in names:
            d = near[name] if name in near else image_direction(real_sky.named_star(name))
            pos = preview.project(d, yaw, pitch, w, h, fov)
            if pos is not None:
                draw.text((pos[0] + 7, pos[1] - 8), name, fill=(190, 210, 255), font=preview.font(13))
        panels.append(np.array(im))
    rows = [np.concatenate(panels[k:k + 2], axis=1) for k in range(0, len(panels), 2)]
    out = np.concatenate(rows, axis=0).astype(np.uint8)
    path = PREVIEWS / ("shader_sky.png" if quality == "high" else f"shader_sky_{quality}.png")
    Image.fromarray(out).save(path, optimize=True)
    print(f"wrote {path.relative_to(HERE.parent)}")
    return imgs


def _save_gif(imgs, path, frame_ms):
    """Animated GIF with one shared palette (so colours do not flicker between frames)."""
    sheet = Image.fromarray(np.concatenate([i[::4, ::4] for i in imgs], axis=0).astype(np.uint8))
    palette = sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pil = [Image.fromarray(i.astype(np.uint8)).quantize(palette=palette, dither=Image.Dither.NONE) for i in imgs]
    pil[0].save(path, save_all=True, append_images=pil[1:], duration=frame_ms, loop=0, optimize=True)
    print(f"wrote {path.relative_to(HERE.parent)} ({path.stat().st_size / 1e6:.1f} MB)")


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


def aurora_animation(seconds=6.0, fps=8, fade=1.0, quality="high", w=512, h=288):
    """The northern lights looking north at night, as a seamless loop: the last `fade` seconds
    are cross-faded into the start. Timed so that a shooting star crosses the view."""
    yaw, pitch, fov = 180.0, -22.0, 78.0
    # a meteor in the northern sky, a second into the loop
    meteor = next(m for m in ss.meteor_schedule(quality) if m["duration"] > 0.6 and m["start"][2] < -0.6
                  and 0.3 < m["start"][1] < 0.7)
    t0 = meteor["time"] - 1.2 / 1200.0
    n, nf = int(round(seconds * fps)), int(round(fade * fps))
    frames = [frame(yaw, pitch, w, h, fov=fov, time=t0 + k / fps / 1200.0, **NIGHT) for k in range(n + nf)]
    imgs = [ground(i, yaw, pitch, fov, True) for i in render(frames, quality)]
    out = []
    for k in range(n):
        if k < nf:      # the start blends from the frames after the end, so the loop has no jump
            a = k / nf
            out.append(imgs[n + k] * (1 - a) + imgs[k] * a)
        else:
            out.append(imgs[k])
    _save_gif(out, PREVIEWS / "shader_sky_aurora.gif", int(round(1000 / fps)))
    return out


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


def green_excess(img):
    """How much greener than red and blue each pixel is (only the aurora is green in this sky)."""
    img = img.astype(float)
    return img[..., 1] - np.maximum(img[..., 0], img[..., 2])


def day_night_check(quality="high"):
    """The black hole only shows at night (fading in at dusk); by day the sky is vanilla's, untouched
    (it does not change with the animation clock, and has no structure); the northern lights hang in
    the north at night only (not in the south, not by day, not in rain). Returns the measurements."""
    w, h, fov = 480, 270, 70.0
    south, north = (0, -22), NORTH[:2]
    frames = [
        frame(*south, w, h, fov=fov, time=0.37, **DAY),
        frame(*south, w, h, fov=fov, time=0.53, **DAY),
        frame(*south, w, h, fov=fov, time=0.37, **SUNSET),
        frame(*south, w, h, fov=fov, time=0.372, **SUNSET),
        frame(*south, w, h, fov=fov, time=0.37, **NIGHT),
        frame(*south, w, h, fov=fov, time=0.372, **NIGHT),
        frame(*north, w, h, fov=fov, time=NORTH_TIME, **NIGHT),
        frame(*north, w, h, fov=fov, time=NORTH_TIME, **DAY),
        frame(*north, w, h, fov=fov, time=NORTH_TIME, **dict(NIGHT, sky=(0.02, 0.02, 0.025), star_b=0.0)),  # rain
        frame(*south, w, h, fov=fov, time=NORTH_TIME, sky_pass=False, **NIGHT),
    ]
    day, day2, dusk, dusk2, night, night2, aurora, aurora_day, aurora_rain, south_stars = (
        i.astype(float) for i in render(frames, quality))
    # where the hole is in the southern view
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = preview.project(ss.BH_DIR, *south, w, h, fov)
    hole = (xx - cx) ** 2 + (yy - cy) ** 2 < (0.22 * w) ** 2
    m = dict(
        day_clock=np.abs(day - day2).max(),                           # 0: nothing animates by day
        day_detail=np.abs(np.diff(day, 2, axis=1)).max(),             # vanilla's smooth gradient
        dusk_clock=np.abs(dusk - dusk2)[hole].max(),                  # the disk orbits at dusk, fainter
        night_clock=np.abs(night - night2)[hole].max(),               # and at night
        dusk_hole=dusk[hole].max(),
        night_hole=night[hole].max(),
        aurora_north=(green_excess(aurora) > 12).mean(),              # share of the view that is aurora
        aurora_peak=aurora[..., 1][green_excess(aurora) > 12].max(),  # its brightest green
        aurora_day=green_excess(aurora_day).max(),
        aurora_rain=green_excess(aurora_rain).max(),
        aurora_south=(green_excess(south_stars) > 12).mean(),
    )
    print(f"day/night check ({quality}): " + ", ".join(f"{k} {v:.3g}" for k, v in m.items()))
    assert m["day_clock"] == 0 and m["day_detail"] <= 3, "the day sky must be vanilla's"
    assert 8 < m["dusk_clock"] < m["night_clock"] and m["night_hole"] > 200, "the hole: faint at dusk, bright at night"
    assert m["aurora_north"] > 0.08 and 90 < m["aurora_peak"] < 200, "northern lights expected in the north at night"
    assert m["aurora_day"] <= 0 and m["aurora_rain"] <= 0, "no northern lights by day or in rain"
    assert m["aurora_south"] < 0.002, "the northern lights belong to the northern sky"
    return m


def _centroid(lum, x, y, r=2):
    """Brightness-weighted centre of the dot nearest pixel position (x, y), minus the sky glow."""
    ix, iy = int(round(x - 0.5)), int(round(y - 0.5))
    win = lum[iy - r:iy + r + 1, ix - r:ix + r + 1]
    win = win - lum[iy - r - 2:iy + r + 3, ix - r - 2:ix + r + 3].min()
    if win.sum() <= 0:
        return 99.0, 0.0
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    cx, cy = ix + 0.5 + (win * xx).sum() / win.sum(), iy + 0.5 + (win * yy).sum() / win.sum()
    return math.hypot(cx - x, cy - y), float(lum[iy - 1:iy + 2, ix - 1:ix + 2].max())


def extras_check(quality="high"):
    """The planets shine where night_sky.py puts them (not bent by the hole); a satellite glides
    along the path satellite_schedule() predicts; the comet's tails glow above the sky; and none of
    it shows by day. Returns the measurements."""
    w, h, fov = 640, 360, 50.0
    night = dict(NIGHT, time=0.31)
    shots = []
    for name, d, peak, _ in night_sky.planets():
        alt, az = real_sky.horizontal(d)
        if alt > 10:
            shots.append((name, d, az + 180.0 + 6.0, -alt - 4.0, night))
    station = next(m for m in ss.satellite_schedule(quality) if m["station"] and m["rise"] < 0.30 < m["set"] - 0.03)
    for t in (0.30, 0.30 + 6.0 / 1200.0):
        d = station["where"](t)
        alt, az = real_sky.horizontal(d)
        shots.append(("station", d, az + 180.0 + 4.0, -alt + 3.0, dict(NIGHT, time=t)))
    head, tail = night_sky.comet_frame()
    tail_pt = bh.normalize(head + math.tan(math.radians(6.0)) * tail)
    ref_pt = bh.normalize(head - math.tan(math.radians(6.0)) * tail)
    alt, az = real_sky.horizontal(head)
    shots.append(("comet", tail_pt, az + 180.0, -alt - 5.0, night))
    shots.append(("comet by day", tail_pt, az + 180.0, -alt - 5.0, dict(DAY, time=0.31)))
    shots.append(("day sky alone", tail_pt, az + 180.0, -alt - 5.0, dict(DAY, time=0.31, stars=False)))
    imgs = render([frame(yaw, pitch, w, h, fov=fov, **cfg) for _, _, yaw, pitch, cfg in shots], quality)
    m = {"by day": float(np.abs(imgs[-2].astype(float) - imgs[-1].astype(float)).max())}
    for (name, d, yaw, pitch, cfg), img in zip(shots[:-2], imgs[:-2]):
        lum = img.astype(float).mean(-1)
        if name == "comet":
            p, q = preview.project(tail_pt, yaw, pitch, w, h, fov), preview.project(ref_pt, yaw, pitch, w, h, fov)
            box = lambda c: lum[int(c[1]) - 4:int(c[1]) + 5, int(c[0]) - 4:int(c[0]) + 5].mean()  # noqa: E731
            m[name] = box(p) - box(q)            # tail minus the sky on the other side of the head
            continue
        p = preview.project(d, yaw, pitch, w, h, fov)
        err, peak = _centroid(lum, *p)
        key = name if name != "station" else f"station@{len([k for k in m if k.startswith('station')])}"
        m[key] = (round(err, 3), peak)
    print(f"extras check ({quality}): " + ", ".join(f"{k} {v}" for k, v in m.items()))
    for k, (err, peak) in ((k, v) for k, v in m.items() if isinstance(v, tuple)):
        assert err < 0.7 and peak > 60, f"{k} should be a dot right where night_sky.py / the schedule put it"
    assert m["comet"] > 6, "the comet's tail should glow"
    assert m["by day"] == 0, "by day the sky is vanilla's: no comet, planets or satellites"
    return m


def main():
    PREVIEWS.mkdir(exist_ok=True)
    stills("high")
    animation()
    aurora_animation()
    if "--check" in sys.argv:
        check()
        day_night_check()
        extras_check()


if __name__ == "__main__":
    main()
