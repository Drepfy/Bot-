# 💎 Diamond SMP: Black Hole Sky

A vanilla-friendly Minecraft Java resource pack. Blocks, items and mobs keep their vanilla textures. The sky gets a **physically ray-traced black hole** that stays in the sky all day. A real atmosphere renders the day, sunrise, sunset, night and rain around it.

**Download:**
* [`Diamond-SMP-Black-Hole-Pack.zip`](Diamond-SMP-Black-Hole-Pack.zip): full quality.
* [`Diamond-SMP-Black-Hole-Pack-Lite.zip`](Diamond-SMP-Black-Hole-Pack-Lite.zip): half-resolution skies for low-end PCs and laptops.
* [`Diamond-SMP-Light-Boost.zip`](Diamond-SMP-Light-Boost.zip): optional add-on that brightens dark places a little (see [Light Boost add-on](#light-boost-add-on)).

![Day cycle](previews/day_cycle.png)

| Title screen | The End |
|---|---|
| ![Title screen](previews/title_screen.png) | ![End sky](previews/end_sky.png) |

![Rain](previews/rain.png)

## What's in the pack

| Feature | Needs |
|---|---|
| **Day / sunrise / sunset / night skies** that cross-fade with the Minecraft clock. The black hole sits due south, 24° up, all day. | OptiFine (or Nuit + Nuit Interop) |
| **Rain skies:** overcast by day and night, with the black hole a soft glow behind the clouds | OptiFine (or equivalent) |
| **Realistic sun:** a limb-darkened disc with atmospheric glare | OptiFine (or equivalent) |
| Purple "ender light" black hole over the End | OptiFine (or equivalent) |
| **The vanilla sun is a black hole.** It rises and sets like the sun. | Nothing, pure vanilla |
| **Title screen:** a slowly spinning black hole with the Milky Way bent around it | Nothing |
| **"DIAMOND SMP" logo** made of diamond blocks, plus a "Black Hole Edition" subtitle | Nothing |
| Custom splash texts, a deep space End sky, and the pack icon | Nothing |

### How realistic is it?

Every pixel is computed from physics, not painted:

* **Exact light bending:** each ray is traced through the curved spacetime of a Schwarzschild black hole. That gives the right shadow size, the thin photon ring, and the disk's far side lensed over the top and under the bottom.
* **Real disk physics:** a thin accretion disk with the Novikov–Thorne temperature profile (≈26,000 K at its hottest).
  * Each point glows as a true blackbody, converted to color with the CIE 1931 human-eye curves. That's why it's blue-white, like a real hot disk.
  * Exact relativistic **Doppler beaming and gravitational redshift** make the side spinning toward you brighter and bluer.
  * Limb darkening makes the disk dimmer at grazing angles.
* **Real sky:** Rayleigh, Mie and ozone scattering in Earth's atmosphere.
  * That gives the blue day sky, the orange-to-pink sunrise and sunset, and twilight that stays blue overhead.
  * The black hole and stars dim and redden near the horizon, and a soft haze glows around the black hole.
  * By day, sky light fills in the shadow, the same way the Moon's dark side disappears in daylight.
* **Real night sky:**
  * Stars follow real brightness statistics and blackbody colors.
  * The Milky Way has a warm central bulge, star clouds, dark dust lanes that redden the light behind them, pink hydrogen nebulae, and faint airglow at the horizon. All of it is lensed by the hole too.
* **Camera optics:** glare around bright light, and a filmic tone curve like a long-exposure astrophoto.

## Install

1. Download the zip (Lite if your PC struggles). **Don't unzip it.**
2. In Minecraft open **Options → Resource Packs → Open Pack Folder** and drop the zip in.
3. Move **Diamond SMP Black Hole Sky** to the right-hand column and click **Done**.

Works on **Java Edition 1.20 → 26.x**.

### Getting the full sky

Vanilla Minecraft can't put textures on the Overworld sky, so the sky layers use the OptiFine custom-sky format:

* **OptiFine:** Options → Video Settings → Quality → **Custom Sky: ON**.
* **Fabric / Sodium / Iris:** install **[Nuit](https://modrinth.com/mod/nuit)** and **[Nuit Interop](https://modrinth.com/nuit-interop)**. Nuit Interop loads OptiFine custom skies.

Without those mods you still get the black hole sun, the title screen, the logo, the splashes and the End sky.

## Light Boost add-on

[`Diamond-SMP-Light-Boost.zip`](Diamond-SMP-Light-Boost.zip) is a tiny separate pack. Put it **above** the main pack. It gently brightens the world, and the darker a spot is, the stronger the boost:

| Spot | Vanilla brightness | With boost |
|---|---|---|
| Full daylight | 0.99 | 0.99 (unchanged) |
| Mid-dark cave (light 7) | 0.41 | 0.45 |
| Pitch black | 0.10 | 0.21 |

![Light boost](previews/light_boost.png)

It works by patching Minecraft's lighting shader, so it ships one version per shader:
* Supported: **1.21.9 to 1.21.11, 26.1, 26.2 and 26.3**. On any other version it does nothing.
* It switches itself off during the Warden's **Darkness** effect, so it stays fair in PvP.
* It stacks with your Brightness slider.

## FPS: what helps and what doesn't

Straight answer: **no resource pack can give 100x FPS.** FPS is mostly decided by how many chunks, entities and light updates your PC has to draw. This pack's sky costs about the same as the vanilla sky: a few textured boxes. What actually helps:

**1. Mods (biggest win).** Use Fabric with these:

| Mod | What it does |
|---|---|
| **Sodium** | Rewrites the renderer. Often 2–3x FPS or more. |
| **Lithium** | Faster game logic (singleplayer and servers) |
| **ImmediatelyFast** | Faster GUI, text and entity drawing |
| **Entity Culling** | Skips mobs and chests you can't see |
| **FerriteCore** / **ModernFix** | Less RAM, fewer lag spikes, faster startup |
| **Dynamic FPS** | Throttles the game when it's in the background |
| **Nuit + Nuit Interop** | Shows this pack's sky on Sodium |

**2. Settings (biggest single factor: render distance).**

| Setting | Value |
|---|---|
| Render Distance | 8–12 |
| Simulation Distance | 5–8 |
| Graphics | Fast |
| Clouds | Off or Fast |
| Entity Shadows | Off |
| Particles | Decreased |
| Biome Blend | Off |
| Max Framerate | Unlimited |
| VSync | Off |

**3. Your PC:**
* Give Minecraft 4–6 GB of RAM in the launcher (never more than half your total).
* Update your graphics drivers.
* On a laptop, plug it in and force Minecraft (`javaw.exe`) onto the dedicated GPU: Windows Settings → Display → Graphics → High performance.

**4. Use the Lite zip** if you're on integrated graphics or a GPU with little VRAM. It uses a quarter of the texture memory.

## Using it with other packs (like a PvP pack)

Packs stack, so you don't need to merge anything: put **Diamond SMP above your PvP pack** in the resource pack list. Diamond SMP then supplies the sky, sun, title screen and logo, and the other pack supplies everything else.

If you really want one zip, [`generator/merge_packs.py`](generator/merge_packs.py) builds a merged copy into `personal/`, which is git-ignored:

```bash
python generator/merge_packs.py path/to/OtherPack.zip          # or add --lite
# keep vanilla armor + potions from the other pack, and add the light boost:
python generator/merge_packs.py path/to/OtherPack.zip --vanilla armor potions --light-boost
```

`--vanilla armor` drops the other pack's armor icons, worn armor, armor glint and trim colors. `--vanilla potions` drops its potion bottles, effect icons, effect backgrounds and potion particles. Without those files, the vanilla look of your Minecraft version shows through.

⚠️ Merged zips are **for your own use**. Many packs (Fortyone included) forbid sharing modified versions, so don't upload one or use it as the server pack without that author's permission.

## Use it as the server resource pack

Everyone who joins gets the pack automatically. Upload the zip somewhere with a **direct, public download link**, then set in `server.properties`:

```properties
resource-pack=https://<direct link to>/Diamond-SMP-Black-Hole-Pack.zip
resource-pack-sha1=<sha1 of the zip>
resource-pack-prompt={"text":"Diamond SMP: enable the black hole sky?","color":"aqua"}
require-resource-pack=false
```

Get the SHA-1 with `sha1sum Diamond-SMP-Black-Hole-Pack.zip` (macOS: `shasum`, Windows: `certutil -hashfile <file> SHA1`).

## Tweaks

All of these are plain-text edits inside the zip, under `assets/minecraft/`.

* **Black hole in deep space all day:** delete `optifine/sky/world0/sky2`–`sky4.properties`. In `sky1.properties`, set `blend=replace` and delete the three `Fade` lines.
* **Change when skies fade:** edit the `startFadeIn` / `endFadeIn` / `endFadeOut` times in `optifine/sky/world0/sky*.properties`. The format is 24h, and 06:00 is sunrise in Minecraft.
* **Keep the vanilla sun:** delete `textures/environment/sun.png` and `textures/environment/celestial/sun.png`. With OptiFine, also delete `optifine/sky/world0/sun.properties`.
* **Your own splashes:** edit `texts/splashes.txt`, one per line.

## How it's made

Every texture is generated from scratch by [`generator/`](generator). No Mojang art is used or copied.

* [`blackhole.py`](generator/blackhole.py): the Schwarzschild ray tracer (Numba), blackbody color science, procedural galaxy, glare and tone mapping.
* [`atmosphere.py`](generator/atmosphere.py): single-scattering Rayleigh, Mie and ozone sky model.
* [`build_pack.py`](generator/build_pack.py): renders every layer and zips the full and Lite packs.
  * Skyboxes are 3072×2048, 2×2 supersampled, and padded so glare is seamless across cube faces.
* [`preview.py`](generator/preview.py): reads the textures back the way the game maps them, to make the screenshots above.
* [`light_boost.py`](generator/light_boost.py): builds the Light Boost add-on from the vanilla lighting shaders.
* [`merge_packs.py`](generator/merge_packs.py): personal merges with other packs.

Rebuild (about 10 minutes on 4 cores):

```bash
pip install numpy numba pillow
cd diamond-smp-pack/generator
python build_pack.py      # add --quick for a fast low-res draft
python preview.py
```
