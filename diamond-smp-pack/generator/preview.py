"""Renders preview screenshots from the built pack (used for the README).

It reads the generated textures back exactly the way the game maps them
(OptiFine 3x2 skybox, vanilla title panorama), so seams or flipped faces show up.
"""

import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import blackhole as bh
import kerr
import real_sky
from build_pack import MC, OPTIFINE_TILES, OVERWORLD, OVERWORLD_DIR, ROOT

PREVIEWS = ROOT / "previews"


def player_view(yaw, pitch, w, h, fov_y=70.0):
    f = bh.mc_direction(yaw, pitch)
    u = bh.mc_direction(yaw, pitch - 90)
    r = np.cross(f, u)
    t = math.tan(math.radians(fov_y / 2))
    xs = ((np.arange(w) + 0.5) / w * 2 - 1) * t * w / h
    ys = ((np.arange(h) + 0.5) / h * 2 - 1) * t
    a, b = np.meshgrid(xs, ys)
    return bh.normalize(f + a[..., None] * r - b[..., None] * u)


def sample_optifine(tex, dirs):
    face = tex.shape[0] // 2
    best = np.full(dirs.shape[:-1], -np.inf)
    out = np.zeros(dirs.shape[:-1] + (3,), dtype=np.float64)
    for tile, m in enumerate(OPTIFINE_TILES):
        loc = dirs @ m  # world -> tile-local (inverse of a rotation is its transpose)
        depth = -loc[..., 1]
        sel = depth > best
        best = np.where(sel, depth, best)
        fu = np.clip((loc[..., 0] / depth + 1) / 2 * face - 0.5, 0, face - 1.001)
        fv = np.clip((loc[..., 2] / depth + 1) / 2 * face - 0.5, 0, face - 1.001)
        iu, iv = fu.astype(int), fv.astype(int)
        du, dv = (fu - iu)[..., None], (fv - iv)[..., None]
        r, c = divmod(tile, 3)
        t = tex[r * face:(r + 1) * face, c * face:(c + 1) * face].astype(np.float64)
        val = ((t[iv, iu] * (1 - du) + t[iv, iu + 1] * du) * (1 - dv)
               + (t[iv + 1, iu] * (1 - du) + t[iv + 1, iu + 1] * du) * dv)
        out[sel] = val[sel]
    return out


def sample_panorama(faces, dirs):
    size = faces[0].shape[0]
    best = np.full(dirs.shape[:-1], -np.inf)
    out = np.zeros(dirs.shape[:-1] + (3,), dtype=np.uint8)
    for k in range(6):
        yaw = [0, 90, 180, -90, 0, 0][k]
        pitch = [0, 0, 0, 0, -90, 90][k]
        f = bh.mc_direction(yaw, pitch)
        u = bh.mc_direction(yaw, pitch - 90)
        r = np.cross(f, u)
        depth = dirs @ f
        sel = depth > best
        best = np.where(sel, depth, best)
        a = np.clip((((dirs @ r) / depth + 1) / 2 * size).astype(int), 0, size - 1)
        b = np.clip((((-(dirs @ u)) / depth + 1) / 2 * size).astype(int), 0, size - 1)
        out[sel] = faces[k][b[sel], a[sel]]
    return out


def project(world_dir, yaw, pitch, w, h, fov_y=70.0):
    """Pixel position of a world direction in player_view(yaw, pitch, w, h, fov_y), or None."""
    f = bh.mc_direction(yaw, pitch)
    u = bh.mc_direction(yaw, pitch - 90)
    r = np.cross(f, u)
    z = world_dir @ f
    if z <= 0:
        return None
    t = math.tan(math.radians(fov_y / 2))
    x = (world_dir @ r) / z / (t * w / h)
    y = -(world_dir @ u) / z / t
    if abs(x) >= 1 or abs(y) >= 1:
        return None
    return (x + 1) / 2 * w, (y + 1) / 2 * h


def lensed(world_dir, iters=8):
    """Where a star actually appears: the black hole bends even far-away starlight by a few
    degrees, so find the view direction whose traced ray escapes towards the star."""
    scene = kerr.KerrScene(background=None, **OVERWORLD)
    w2s = bh.world_to_scene(OVERWORLD_DIR)
    view = np.array(world_dir, dtype=np.float64)
    for _ in range(iters):
        _, diag = scene.trace_info((w2s @ view)[None])
        escaped = bh.normalize(w2s.T @ diag[0, :3])
        view = bh.normalize(view + (world_dir - escaped))
    return view


def add_sun(img, dirs, sun_dir, strength=1.0):
    """Approximate the OptiFine sun sprite the game draws on top of the sky."""
    ang = np.degrees(np.arccos(np.clip(dirs @ sun_dir, -1, 1)))
    glow = np.where(ang < 1.4, 1.0, 0) + 0.6 * np.exp(-ang / 0.9) + 0.12 * np.exp(-ang / 4.0)
    col = np.array([255, 244, 225]) * strength
    return np.clip(img + glow[..., None] * col, 0, 255)


def add_ground(img, dirs, colour):
    """Silhouette of blocky hills so the sky preview reads as an in-game view."""
    yaw = np.degrees(np.arctan2(-dirs[..., 0], dirs[..., 2]))
    elev = np.degrees(np.arcsin(np.clip(dirs[..., 1], -1, 1)))
    hill = 2.5 + 2.0 * np.sin(np.radians(yaw) * 3.0) + 1.2 * np.sin(np.radians(yaw) * 7.3 + 1.0)
    hill = np.round(hill / 1.2) * 1.2
    ground = elev < hill
    shade = np.clip(1.0 + (elev - hill) / 40, 0.45, 1.0)[..., None]
    img = img.copy()
    img[ground] = (np.array(colour) * shade)[ground]
    return img


def font(size):
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def label(img, text):
    im = Image.fromarray(img.astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 14 + 15 * len(text), 40], fill=(0, 0, 0))
    d.text((10, 6), text, fill=(255, 255, 255), font=font(24))
    return np.array(im)


def sky(name, world="world0"):
    return np.array(Image.open(MC / f"optifine/sky/{world}/{name}.png").convert("RGB"))


def main():
    PREVIEWS.mkdir(exist_ok=True)
    W, H = 1280, 720
    shots = []

    d = player_view(0, -14, W, H)  # facing south, looking up a little
    night = add_ground(sample_optifine(sky("night"), d), d, (8, 11, 8))
    Image.fromarray(night.astype(np.uint8)).save(PREVIEWS / "overworld_night.png", optimize=True)
    shots.append(label(night, "Night"))

    d = player_view(-45, -12, W, H, 78)  # south-east: sunrise and the black hole
    img = add_sun(sample_optifine(sky("sunrise"), d), d, bh.normalize([1.0, 0.05, 0.0]))
    sunrise = add_ground(img, d, (34, 30, 30))
    shots.append(label(sunrise, "Sunrise"))

    d = player_view(0, -14, W, H)
    day = add_ground(sample_optifine(sky("day"), d), d, (62, 92, 44))
    Image.fromarray(day.astype(np.uint8)).save(PREVIEWS / "overworld_day.png", optimize=True)
    shots.append(label(day, "Day"))

    d = player_view(45, -12, W, H, 78)  # south-west: sunset
    img = add_sun(sample_optifine(sky("sunset"), d), d, bh.normalize([-1.0, 0.05, 0.0]))
    sunset = add_ground(img, d, (34, 28, 30))
    shots.append(label(sunset, "Sunset"))

    grid = np.concatenate([np.concatenate(shots[:2], 1), np.concatenate(shots[2:], 1)], 0).astype(np.uint8)
    Image.fromarray(grid).resize((W, H), Image.LANCZOS).save(PREVIEWS / "day_cycle.png", optimize=True)

    d = player_view(0, -14, W // 2, H // 2)
    rain = np.concatenate([
        label(add_ground(sample_optifine(sky("overcast_day"), d), d, (50, 66, 40)), "Rain (day)"),
        label(add_ground(sample_optifine(sky("overcast_night"), d), d, (6, 8, 6)), "Rain (night)")], 1)
    Image.fromarray(rain.astype(np.uint8)).save(PREVIEWS / "rain.png", optimize=True)

    d = player_view(-90, -28, W, H)  # east, in the End
    Image.fromarray(sample_optifine(sky("void_sky", "world1"), d).astype(np.uint8)).save(
        PREVIEWS / "end_sky.png", optimize=True)

    faces = [np.array(Image.open(MC / f"textures/gui/title/background/panorama_{k}.png").convert("RGB"))
             for k in range(6)]
    d = player_view(-20, 0, W, H, 85)
    title = Image.fromarray(sample_panorama(faces, d)).convert("RGBA")
    logo = Image.open(MC / "textures/gui/title/minecraft.png")
    edition = Image.open(MC / "textures/gui/title/edition.png")
    scale = 3  # GUI scale used for the mock-up (logo is 256 GUI px wide)
    lw = 256 * scale
    lx, ly = (W - lw) // 2, 45
    title.alpha_composite(logo.resize((lw, lw // 4), Image.NEAREST), (lx, ly))
    title.alpha_composite(edition.resize((128 * scale, 16 * scale), Image.NEAREST), (lx + 88 * scale, ly + 37 * scale))
    draw = ImageDraw.Draw(title)
    for i, text in enumerate(["Singleplayer", "Multiplayer", "Minecraft Realms"]):
        bx, by = W // 2 - 150, 300 + i * 72
        draw.rectangle([bx, by, bx + 300, by + 54], fill=(40, 40, 48, 200), outline=(10, 10, 14, 255), width=3)
        draw.text((bx + 150, by + 27), text, fill=(235, 235, 235, 255), font=font(24), anchor="mm")
    splash = Image.new("RGBA", (520, 60), (0, 0, 0, 0))
    ImageDraw.Draw(splash).text((260, 30), "Don't look into the black hole!", fill=(255, 255, 0, 255),
                                font=font(26), anchor="mm")
    splash = splash.rotate(20, expand=True, resample=Image.BICUBIC)
    title.alpha_composite(splash, (lx + lw - 330, ly + 60))
    title.convert("RGB").save(PREVIEWS / "title_screen.png", optimize=True)

    # The real stars, away from the lensing: looking north-west at the Big Dipper and Polaris.
    yaw, pitch, fov = 135, -30, 80
    d = player_view(yaw, pitch, W, H, fov)
    north = Image.fromarray(add_ground(sample_optifine(sky("night"), d), d, (8, 11, 8)).astype(np.uint8))
    draw = ImageDraw.Draw(north)
    for name in ("Polaris", "Kochab", "Dubhe", "Merak", "Phecda", "Megrez", "Alioth", "Mizar", "Alkaid",
                 "Arcturus", "Capella"):
        pos = project(lensed(real_sky.named_star(name)), yaw, pitch, W, H, fov)
        if pos is not None:
            draw.text((pos[0] + 9, pos[1] - 9), name, fill=(170, 200, 255), font=font(15))
    north.save(PREVIEWS / "real_stars_north.png", optimize=True)

    def additive(rel, bg):
        rgba = np.array(Image.open(MC / rel).convert("RGBA")).astype(np.float64)
        return np.clip(bg + rgba[..., :3] * rgba[..., 3:] / 255, 0, 255).astype(np.uint8)

    sun_day = additive("textures/environment/celestial/sun.png", np.array([90, 140, 230]))
    sun_night = additive("textures/environment/celestial/sun.png", np.zeros(3))
    s = sun_day.shape[0]
    order = ["waxing_crescent", "first_quarter", "waxing_gibbous", "full_moon",
             "waning_gibbous", "third_quarter", "waning_crescent"]
    moons = [additive(f"textures/environment/celestial/moon/{n}.png", np.full(3, 4.0)) for n in order]
    m = moons[0].shape[0]
    crop = [mo[m * 3 // 8:m * 5 // 8, m * 3 // 8:m * 5 // 8] for mo in moons]  # zoom on the disc
    strip = Image.fromarray(np.concatenate(crop, 1)).resize((7 * s // 3, s // 3), Image.LANCZOS)
    top = np.concatenate([sun_day, sun_night], 1)
    sheet = Image.new("RGB", (max(top.shape[1], strip.width), top.shape[0] + strip.height), (4, 4, 4))
    sheet.paste(Image.fromarray(top), (0, 0))
    sheet.paste(strip, ((sheet.width - strip.width) // 2, top.shape[0]))
    sheet.save(PREVIEWS / "sun_moon.png", optimize=True)
    print("previews written to", PREVIEWS)


if __name__ == "__main__":
    sys.exit(main())
