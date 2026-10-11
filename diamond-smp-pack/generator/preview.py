"""Renders preview screenshots from the built pack (used for the README).

It reads the generated textures back exactly the way the game maps them
(OptiFine 3x2 skybox, vanilla title panorama), so seams or flipped faces show up.
"""

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import blackhole as bh
from build_pack import MC, OPTIFINE_TILES, ROOT, panorama_dirs  # noqa: F401

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
    out = np.zeros(dirs.shape[:-1] + (3,), dtype=np.uint8)
    for tile, m in enumerate(OPTIFINE_TILES):
        loc = dirs @ m  # world -> tile-local (inverse of a rotation is its transpose)
        depth = -loc[..., 1]
        sel = depth > best
        best = np.where(sel, depth, best)
        u = np.clip(((loc[..., 0] / depth + 1) / 2 * face).astype(int), 0, face - 1)
        v = np.clip(((loc[..., 2] / depth + 1) / 2 * face).astype(int), 0, face - 1)
        r, c = divmod(tile, 3)
        out[sel] = tex[r * face + v[sel], c * face + u[sel]]
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


def add_ground(img, dirs):
    """Silhouette of rolling hills so the sky preview reads as an in-game view."""
    h, w = img.shape[:2]
    yaw = np.degrees(np.arctan2(-dirs[..., 0], dirs[..., 2]))
    elev = np.degrees(np.arcsin(np.clip(dirs[..., 1], -1, 1)))
    hill = 2.5 + 2.0 * np.sin(np.radians(yaw) * 3.0) + 1.2 * np.sin(np.radians(yaw) * 7.3 + 1.0)
    hill = np.round(hill / 1.2) * 1.2  # blocky skyline
    ground = elev < hill
    shade = np.clip(0.5 + (elev - hill) / 30, 0.15, 0.5)
    col = np.stack([0.11 * shade, 0.16 * shade, 0.10 * shade], -1) * 255
    img = img.copy()
    img[ground] = col[ground].astype(np.uint8)
    return img


def font(size):
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def main():
    PREVIEWS.mkdir(exist_ok=True)
    W, H = 1280, 720

    sky = np.array(Image.open(MC / "optifine/sky/world0/blackhole_sky.png").convert("RGB"))
    d = player_view(0, -14, W, H)  # facing south, looking up a little
    Image.fromarray(add_ground(sample_optifine(sky, d), d)).save(PREVIEWS / "overworld_sky.png", optimize=True)
    d = player_view(0, -60, W, H, 90)
    Image.fromarray(sample_optifine(sky, d)).save(PREVIEWS / "overworld_sky_up.png", optimize=True)

    end = np.array(Image.open(MC / "optifine/sky/world1/void_sky.png").convert("RGB"))
    d = player_view(-90, -28, W, H)  # east
    Image.fromarray(sample_optifine(end, d)).save(PREVIEWS / "end_sky.png", optimize=True)

    faces = [np.array(Image.open(MC / f"textures/gui/title/background/panorama_{k}.png").convert("RGB"))
             for k in range(6)]
    d = player_view(-20, 0, W, H, 85)
    title = Image.fromarray(sample_panorama(faces, d)).convert("RGBA")
    logo = Image.open(MC / "textures/gui/title/minecraft.png")
    edition = Image.open(MC / "textures/gui/title/edition.png")
    scale = 3  # GUI scale used for the mock-up (logo is 256 GUI px wide)
    lw = 256 * scale
    logo_s = logo.resize((lw, lw // 4), Image.NEAREST)
    lx, ly = (W - lw) // 2, 30 * scale // 2
    title.alpha_composite(logo_s, (lx, ly))
    ed = edition.resize((128 * scale, 16 * scale), Image.NEAREST)
    title.alpha_composite(ed, (lx + 88 * scale, ly + 37 * scale))
    draw = ImageDraw.Draw(title)
    for i, label in enumerate(["Singleplayer", "Multiplayer", "Minecraft Realms"]):
        bx, by = W // 2 - 150, 300 + i * 72
        draw.rectangle([bx, by, bx + 300, by + 54], fill=(40, 40, 48, 200), outline=(10, 10, 14, 255), width=3)
        draw.text((bx + 150, by + 27), label, fill=(235, 235, 235, 255), font=font(24), anchor="mm")
    splash = Image.new("RGBA", (520, 60), (0, 0, 0, 0))
    ImageDraw.Draw(splash).text((260, 30), "Don't look into the black hole!", fill=(255, 255, 0, 255),
                                font=font(26), anchor="mm")
    splash = splash.rotate(20, expand=True, resample=Image.BICUBIC)
    title.alpha_composite(splash, (lx + lw - 330, ly + 60))
    title.convert("RGB").save(PREVIEWS / "title_screen.png", optimize=True)

    sun = Image.open(MC / "textures/environment/sun.png").convert("RGBA")
    over = Image.new("RGBA", sun.size, (90, 140, 230, 255))  # daytime sky colour behind it
    rgb = np.array(sun).astype(np.float64)
    add = rgb[..., :3] * rgb[..., 3:] / 255
    day = np.clip(np.array(over)[..., :3] + add, 0, 255).astype(np.uint8)
    night = np.clip(add, 0, 255).astype(np.uint8)
    Image.fromarray(np.concatenate([day, night], 1)).save(PREVIEWS / "vanilla_sun.png", optimize=True)
    print("previews written to", PREVIEWS)


if __name__ == "__main__":
    sys.exit(main())
