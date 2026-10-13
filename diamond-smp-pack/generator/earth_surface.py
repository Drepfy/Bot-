"""The Earth's surface seen from space under a clear sky: true colour, land, ice and relief.

What a white-balanced, cloud-free satellite mosaic such as NASA's Blue Marble shows,
rebuilt from public-domain Natural Earth vectors (natural_earth.py) plus a small
hand-made climatology. All maps follow the natural_earth convention: equirectangular,
(W // 2, W), row 0 at the north pole, column 0 at the 180th meridian, east positive.

Land, lakes and coasts
----------------------
Land is ne_50m_land with ne_50m_lakes cut out, drawn supersampled so coasts are
anti-aliased. Water is everything else (lakes included, so they glint).

Climate to colour
-----------------
From space, land colour is mostly a question of how much green leaf covers how much
bare soil, and that follows the balance of rain and warmth. The aridity A (0 rainforest,
0.3 humid cropland, 0.6 dry savanna or steppe, 1 hyper-arid desert) is interpolated from
some three hundred climate control points: what any climate atlas shows, the wet Amazon
and Congo, the dry subtropical highs and the west-coast deserts above cold currents, the
rain shadows behind the Andes, Rockies and Himalaya, the drying interior of Asia. Named
Natural Earth geography regions then pin it down where the polygons are better than a
sketch: the deserts, each with its own sand (the pale Libyan Desert, orange ergs, the red
Australian outback, the grey Gobi, dark volcanic Tibesti and Haruj), steppes and savanna
plains, the Amazon and Congo basins, the green river deltas.

Temperature, from latitude, elevation (6.5 K/km) and continental cooling, picks the
vegetation: tropical forest is the darkest, most saturated green, temperate forest and
cropland a lighter olive, boreal taiga a dark green-brown; poleward of the Arctic tree
line (a table along longitude, from 72 N on the Taymyr down to 57 N on Hudson Bay) and
above it in the mountains lies brownish-grey tundra. As A rises the leaf cover thins and
the soil shows through: red laterite in the tropics, iron-red sand in Australia, grey
gravel in Central Asia, mottled into dunes and darker rock.

Natural Earth has no elevation raster, so the terrain is rebuilt: mountain-range and
plateau polygons give the mean height, scaled by the named peaks nearby
(ne_10m_geography_regions_elevation_points), and ridged 3-D noise carves it into crests
and valleys. That height field is hill-shaded (a satellite photo of mountains shows their
sunlit and shaded slopes), sets the snow line, ~5 km high in the dry subtropics (Andes,
Tibet) and falling to sea level near the poles, so snow lies in streaks along the crests
of the Himalaya, Karakoram, Alps, Caucasus and Alaska, and is returned as 'relief'.
Desert rivers (the Nile above all) are green ribbons of irrigation; salt pans are white.

Every climate lookup goes through a domain warp of 3-D noise on the unit sphere, and all
texture is 3-D noise too: seamless across the date line, no pinching at the poles, and
no polygon edge or interpolation blob survives.

Water
-----
Open ocean is a very dark navy: water absorbs nearly all red and most green, and the
renderer adds the blue Rayleigh haze on top. On the continental shelves (inside the
200 m contour, ne_10m_bathymetry_K_200) the depth is estimated from the distances to the
coast and to the shelf edge. Where clear tropical water lies over white carbonate sand,
sunlight reflected from the bottom shows through, turquoise where it is shallower than
~15 m (Bahamas, Great Barrier Reef, Red Sea and Persian Gulf coasts). Big rivers and muddy
shallow seas stain the water green-brown (Yellow Sea, Amazon, Rio de la Plata).

Ice
---
Antarctica (land and ice shelves), the Greenland ice sheet and the glaciers of
ne_50m_glaciated_areas; high mountain snow; and sea ice: the Arctic pack in its
late-winter extent (an edge latitude along longitude: far north in the Gulf Stream-warmed
Norwegian and Barents seas, down into Hudson Bay, the Bering Sea and the Sea of Okhotsk)
and a ring of Antarctic pack ice, with ragged, broken edges and dark leads.
"""

import math
import unicodedata
from functools import lru_cache

import numpy as np
from numba import njit, prange
from PIL import Image, ImageDraw

import blackhole as bh
import natural_earth as ne

WORK_WIDTH = 1024            # climate grid (fields smoother than ~40 km)
SEED = 4242
R_EARTH_KM = 6371.0
WARP_BIG = 0.032             # domain warp (radians on the unit sphere): ~1.8 deg lobes ...
WARP_SMALL = 0.008           # ... and ~0.5 deg wiggles
HILLSHADE_AZ = 120.0         # sun azimuth (deg from north) of the baked-in terrain shading: a morning pass
HILLSHADE_ALT = 40.0
HILLSHADE_EXAG = 5.0         # vertical exaggeration (map pixels are ~20 km; slopes average out)
HILLSHADE_GAIN = 0.55

# --- Colours: sRGB display values a white-balanced satellite photo shows under full sun ---
DEEP_OCEAN = (8, 18, 45)
SHELF_WATER = (12, 30, 54)
TURQUOISE = (76, 182, 188)            # bottom reflection through clear shallow tropical water
LAKE_WATER = (12, 24, 34)
SNOW = (235, 240, 245)
SEA_ICE = (218, 227, 236)
TUNDRA = (112, 104, 84)
POLAR_DESERT = (148, 140, 124)
PLAYA = (226, 222, 210)
IRRIGATED = (62, 88, 40)
LAKE_SPECKLE = (24, 34, 38)
# vegetation ramps over aridity (A = 0, 0.2, 0.4, 0.6) for three thermal zones
VEG_TROPICAL = ((25, 49, 20), (35, 60, 25), (68, 82, 39), (118, 110, 68))
VEG_TEMPERATE = ((38, 60, 29), (56, 79, 38), (92, 101, 56), (130, 122, 80))
VEG_BOREAL = ((33, 45, 28), (43, 55, 33), (76, 80, 50), (116, 112, 82))
DEFAULT_SOIL = (162, 136, 102)

# Climate control points: (lat, lon, radius deg, aridity). Aridity: 0 rainforest, 0.15 humid
# forest, 0.3 humid cropland / moist woodland, 0.45 sub-humid (prairie, Mediterranean,
# moist savanna), 0.6 semi-arid (dry savanna, steppe), 0.75 arid shrub, 0.9+ desert.
CLIMATE = (
    # North America
    (65, -150, 5, 0.32), (70, -156, 3, 0.4), (61, -136, 4, 0.3), (58, -134, 2.5, 0.05),
    (54, -128, 3, 0.05), (48, -123.5, 2, 0.06), (45, -119.5, 2.5, 0.62), (40.5, -117, 3.5, 0.85),
    (39, -121.5, 1.6, 0.42), (36, -119.5, 1.8, 0.6), (34.3, -116, 2.5, 0.88), (32.5, -112.5, 2.5, 0.86),
    (28.5, -113.5, 2.5, 0.9), (24.5, -111.5, 1.8, 0.82), (36, -110.5, 3, 0.74), (39.5, -106, 2.5, 0.45),
    (44.5, -110, 3, 0.48), (47, -106, 3.5, 0.62), (41, -102, 3, 0.6), (35, -102, 2.5, 0.66),
    (31.5, -105, 2.5, 0.84), (28, -104, 3.5, 0.82), (24, -102, 3, 0.66), (20, -100.5, 2.5, 0.48),
    (26, -108, 2, 0.45), (17, -96, 2.5, 0.28), (19.5, -89, 2.5, 0.25), (15, -88, 2.5, 0.12),
    (10, -84, 2.5, 0.06), (8.5, -80, 2, 0.12), (30.5, -98.5, 2.5, 0.52), (27.5, -98.5, 2, 0.62),
    (31, -94, 2.5, 0.22), (39, -97.5, 2.5, 0.46), (42, -93, 3.5, 0.28), (40, -86, 3.5, 0.24),
    (35, -85, 4, 0.13), (31.5, -84, 3, 0.16), (28, -81.5, 2, 0.16), (42.5, -75, 4, 0.15),
    (46.5, -69, 3.5, 0.12), (50, -98, 3, 0.42), (52, -108, 3.5, 0.52), (53.5, -114, 2.5, 0.38),
    (56, -100, 5, 0.2), (52, -75, 5, 0.13), (60, -112, 5, 0.28), (64, -102, 5, 0.38),
    (55, -63, 3.5, 0.2), (75, -95, 6, 0.6), (80, -80, 5, 0.65), (66, -70, 3, 0.45),
    (18.5, -72.5, 1.5, 0.3), (22, -79, 2, 0.32), (18.3, -66.5, 0.8, 0.2), (21, -157, 1.5, 0.25),
    # South America
    (8, -66, 2.5, 0.48), (11.5, -71.5, 1.2, 0.82), (10.5, -64, 1.5, 0.5), (5, -59, 3.5, 0.1),
    (-3, -62, 7, 0.0), (-8, -56, 5, 0.06), (-11, -49, 4, 0.4), (-15.5, -47.5, 3.5, 0.46),
    (-8, -40, 3, 0.68), (-5, -38.5, 2, 0.62), (-10.5, -37.5, 1.5, 0.4), (-20, -42.5, 2.5, 0.32),
    (-25.5, -50, 3.5, 0.2), (-22, -60, 3, 0.5), (-17.5, -57, 1.8, 0.3), (-34, -61, 3, 0.36),
    (-31, -56, 2.5, 0.26), (-38, -65.5, 3, 0.7), (-32, -67.5, 2.5, 0.86), (-27, -65.5, 1.8, 0.6),
    (-25, -66.8, 1.6, 0.82), (-45, -69, 4.5, 0.78), (-52, -70, 2.5, 0.62), (-42, -73, 1.5, 0.05),
    (-48, -74, 1.8, 0.05), (-38.5, -72.5, 1.2, 0.22), (-35, -71.5, 1.2, 0.5), (-30, -71, 1.2, 0.76),
    (-23.5, -69.5, 2.2, 1.0), (-27, -70, 1.5, 0.98), (-19, -70, 1.6, 1.0), (-15, -75, 1.5, 0.97),
    (-10, -78, 1.2, 0.94), (-6.5, -80, 1.2, 0.9), (-18.5, -67.5, 2.5, 0.7), (-14, -71.5, 1.5, 0.5),
    (-1, -78.5, 1.5, 0.3), (-3.5, -80.3, 0.8, 0.72), (5, -75, 2.5, 0.16), (-9, -75, 2.2, 0.06),
    (-13.5, -69, 2, 0.08), (-17, -64, 2, 0.28), (3, -77.5, 1.2, 0.02), (-2, -52, 2, 0.08),
    # Europe
    (64, 15, 3.5, 0.15), (61, 6.5, 2.5, 0.1), (62.5, 26.5, 3.5, 0.13), (68, 25, 3, 0.28),
    (53, -2, 2.5, 0.16), (53, -8, 2, 0.1), (47, 2, 3.5, 0.3), (51, 10, 3.5, 0.27),
    (52, 20, 3.5, 0.3), (47, 19.5, 2.5, 0.44), (45, 25, 2.5, 0.38), (48.5, 32, 3.5, 0.46),
    (46, 35, 2.5, 0.58), (56, 37, 4.5, 0.2), (52.5, 45, 3.5, 0.48), (40, -4, 2.5, 0.6),
    (37.5, -5, 2, 0.63), (42.5, -8, 1.5, 0.24), (43, 12, 2.5, 0.4), (40, 22, 2.5, 0.46),
    (39, 33, 3.5, 0.6), (41.5, 44, 2.5, 0.4), (46, 8, 2, 0.18), (45, 18, 2.5, 0.25),
    (59, 27, 3, 0.2), (58, 50, 4, 0.2), (64, 42, 4, 0.18), (66.5, 55, 3, 0.26),
    # Africa
    (34, -5, 2.2, 0.52), (31, -8, 2, 0.78), (36, 3, 1.8, 0.45), (36, 9.5, 1.8, 0.5),
    (32, 13, 1.8, 0.8), (32.5, 21, 1.5, 0.66), (24, 5, 9, 1.0), (24, 20, 9, 1.0),
    (26, 30, 5, 1.0), (19, -13, 3, 0.95), (16, -15.5, 2.5, 0.68), (13, -5, 4, 0.56),
    (12, 8, 3.5, 0.52), (16, 10, 3.5, 0.8), (13, 22, 3.5, 0.62), (15.5, 32, 3, 0.76),
    (9, 7, 3, 0.32), (7, -5, 3, 0.18), (6, -10, 2.5, 0.06), (7.5, 1, 1.8, 0.38),
    (5, 9, 2, 0.04), (8, 20, 3.5, 0.34), (0, 20, 6, 0.0), (-5, 24, 3.5, 0.08),
    (8, 30, 2.5, 0.36), (9, 38, 2.5, 0.28), (8, 45, 3.5, 0.82), (5, 47, 3.5, 0.84),
    (2, 40, 2.5, 0.76), (12, 41.5, 1.8, 0.9), (-0.5, 37, 1.8, 0.45), (-3, 34, 2.5, 0.48),
    (-6, 35, 3, 0.5), (-12, 18, 3.5, 0.28), (-13, 27, 3.5, 0.3), (-14, 35, 2.5, 0.3),
    (-19, 30, 2.5, 0.46), (-20, 34.5, 2.5, 0.32), (-22.5, 24, 3.5, 0.66), (-24, 18, 2.5, 0.78),
    (-24, 15, 1.8, 0.98), (-19, 13, 1.5, 0.92), (-14, 12.5, 1.2, 0.85), (-30, 20.5, 3, 0.8),
    (-28.5, 30.5, 2.5, 0.34), (-26, 28, 2, 0.48), (-34, 19.5, 1.2, 0.5), (-33.5, 25, 1.2, 0.6),
    (-17, 49, 1.8, 0.06), (-20, 44.5, 2, 0.55), (-24.5, 45, 1.4, 0.76), (-14, 49, 1.2, 0.2),
    (4, 33, 2.5, 0.42), (11, -12, 2.2, 0.32), (2, 12, 2.5, 0.05), (-8, 30, 2.5, 0.3),
    # Middle East and Asia
    (23, 47, 7, 1.0), (16.5, 44, 1.8, 0.62), (33, 44, 2.5, 0.76), (34.5, 37, 1.8, 0.62),
    (37, 44.5, 2, 0.48), (32, 55, 5, 0.86), (37, 53.5, 1.2, 0.38), (34, 47, 2.2, 0.6),
    (34, 66, 3.5, 0.76), (29, 64.5, 2.5, 0.92), (30.5, 72.5, 2.5, 0.58), (26.5, 71, 2.5, 0.86),
    (23, 78, 3.5, 0.48), (17, 77, 3.5, 0.56), (11, 77.5, 2, 0.36), (13, 74.8, 1, 0.04),
    (26, 82, 3.5, 0.34), (24, 90, 2.5, 0.06), (26.5, 93, 2.5, 0.0), (21, 95.5, 1.8, 0.42),
    (17, 97, 2.5, 0.08), (15, 101, 2.5, 0.3), (16, 104, 2, 0.42), (12.5, 105, 2.5, 0.3),
    (18, 106, 2.5, 0.08), (3, 102, 3, 0.0), (0, 113, 5, 0.0), (-1, 102, 3.5, 0.0),
    (-7, 110, 2.5, 0.1), (-9, 120, 2.5, 0.42), (-5, 140, 5, 0.0), (12, 122.5, 3.5, 0.1),
    (25, 113, 4, 0.08), (30, 112, 4, 0.12), (35, 115.5, 2.5, 0.42), (36, 108.5, 2.5, 0.58),
    (39, 106, 2, 0.86), (42, 104, 5, 0.92), (47, 103, 3.5, 0.6), (50.5, 107, 3.5, 0.38),
    (45.5, 126, 3.5, 0.3), (37, 127.5, 2, 0.1), (36, 138, 3, 0.05), (39, 83, 4, 0.98),
    (45, 87, 2.5, 0.76), (37, 95.5, 2.5, 0.88), (33, 88, 5, 0.66), (29.5, 91, 1.8, 0.46),
    (28, 85, 1.2, 0.1), (34, 77.5, 2.5, 0.82), (41.5, 63, 3.5, 0.92), (45, 60, 2.5, 0.92),
    (39, 59, 2.5, 0.95), (47, 70, 4, 0.72), (52, 70, 3.5, 0.52), (55, 60, 3.5, 0.3),
    (60, 75, 7, 0.18), (62, 100, 7, 0.25), (63, 128, 5, 0.35), (66, 160, 5, 0.36),
    (52, 85, 2.5, 0.36), (41.5, 76, 2.5, 0.6), (54, 158, 2.5, 0.1), (48, 136, 3.5, 0.18),
    (23.5, 121, 1, 0.06), (7.5, 81, 1.2, 0.2), (19, 110, 1, 0.2), (50, 118, 3, 0.55),
    (40, 116, 2, 0.48), (31.5, 35.5, 1.2, 0.78), (40, 48, 1.8, 0.62), (40, 72, 1.2, 0.5),
    # Australia and New Zealand
    (-25, 133, 8, 0.88), (-28, 121, 4.5, 0.86), (-32, 116.5, 1.8, 0.42), (-34.5, 117.5, 1.2, 0.26),
    (-25, 114.5, 1.8, 0.86), (-21, 119.5, 2.5, 0.86), (-16.5, 126, 2.5, 0.56), (-13, 133, 2.5, 0.4),
    (-15, 143, 2.5, 0.42), (-17.5, 145.8, 1.2, 0.18), (-23.5, 148, 2.5, 0.5), (-28, 152, 1.8, 0.22),
    (-32.5, 151, 1.6, 0.22), (-33, 147, 2.5, 0.56), (-37, 145, 2.2, 0.36), (-35, 139, 1.8, 0.58),
    (-31, 138.5, 1.8, 0.8), (-42, 146.5, 1.6, 0.1), (-38.5, 175.5, 2, 0.15), (-43.5, 172, 1.2, 0.42),
    (-43, 170.5, 1, 0.06), (-45.5, 169.5, 1.2, 0.36), (-20, 132, 3, 0.76), (-29, 145, 3, 0.74),
    # Islands and high latitudes
    (65, -18, 2, 0.4), (78, 16, 2.5, 0.55), (52, -175, 4, 0.2),
)

# Soil colour regions (lat, lon, radius deg, sRGB): what the bare ground looks like.
SOIL = (
    (24, 10, 10, (212, 172, 122)), (22, 48, 7, (214, 168, 112)), (-24, 132, 9, (184, 116, 74)),
    (-21, 119, 4, (170, 98, 62)), (-31, 129, 3, (176, 156, 120)), (-23, 22, 5, (176, 134, 94)),
    (-24, 15, 2, (212, 158, 106)), (-31, 22, 3, (150, 128, 100)), (6, 46, 5, (178, 130, 92)),
    (14, 5, 6, (178, 140, 98)), (32, 56, 6, (180, 160, 128)), (31, 66, 5, (172, 152, 122)),
    (42, 62, 7, (186, 170, 130)), (43, 103, 7, (168, 152, 122)), (39, 83, 5, (206, 182, 138)),
    (33, 88, 7, (150, 132, 108)), (26, 71, 3, (190, 160, 118)), (-23, -69, 4, (178, 152, 132)),
    (-45, -69, 6, (158, 140, 108)), (-32, -67, 4, (170, 140, 108)), (40, -116, 5, (172, 154, 126)),
    (33, -111, 5, (178, 152, 118)), (28, -104, 5, (176, 156, 122)), (36.5, -110.5, 3, (188, 140, 104)),
    (-12, -47, 8, (165, 122, 88)), (20, 77, 8, (160, 130, 95)), (40, 10, 10, (162, 142, 110)),
    (39, 34, 5, (168, 146, 112)), (47, 103, 5, (150, 138, 110)), (48, 68, 7, (166, 152, 118)),
    (0, 20, 10, (150, 112, 80)), (-15, 28, 8, (160, 124, 88)), (65, 100, 20, (128, 116, 96)),
    (60, -100, 20, (128, 116, 96)), (-30, 143, 5, (166, 128, 92)), (-18, 133, 5, (168, 118, 80)),
)

# Named Natural Earth regions (ne_10m_geography_regions_polys, matched on letters only):
# (aridity pin or None, pin strength, soil sRGB or None). Unlisted deserts are pinned dry.
REGIONS = {
    "sahara": (1.0, 0.85, (212, 172, 122)), "libyandesert": (1.0, 1.0, (226, 194, 148)),
    "westerndesert": (1.0, 1.0, (224, 192, 146)), "nubiandesert": (1.0, 1.0, (208, 170, 124)),
    "easterndesert": (1.0, 1.0, (178, 148, 116)), "grandergoccidental": (1.0, 1.0, (228, 172, 110)),
    "grandergoriental": (1.0, 1.0, (230, 176, 114)), "ergchech": (1.0, 1.0, (224, 168, 108)),
    "ergiguidi": (1.0, 1.0, (222, 162, 102)), "idhanmurzuq": (1.0, 1.0, (218, 152, 98)),
    "tenere": (1.0, 1.0, (224, 178, 122)), "sarirkalanshiyuarramlialkabi": (1.0, 1.0, (228, 188, 136)),
    "akchar": (1.0, 1.0, (224, 178, 122)), "trarza": (0.9, 0.8, (206, 166, 116)),
    "eldjouf": (1.0, 1.0, (224, 174, 118)), "hamadadudraa": (1.0, 1.0, (160, 132, 100)),
    "hamadadetinrhert": (1.0, 1.0, (168, 138, 104)), "tassiliouanahaggar": (1.0, 1.0, (136, 104, 78)),
    "tassilinajjer": (1.0, 1.0, (124, 96, 74)), "danakil": (0.95, 0.9, (166, 140, 114)),
    "chalbidesert": (0.9, 0.8, (176, 146, 112)), "rubalkhali": (1.0, 1.0, (224, 166, 104)),
    "annafuddesert": (1.0, 1.0, (212, 146, 92)), "syriandesert": (0.95, 0.9, (188, 164, 130)),
    "wahibasands": (1.0, 1.0, (222, 162, 106)), "negevdesert": (0.95, 0.9, (192, 168, 134)),
    "jabalassawda": (1.0, 1.0, (86, 72, 60)), "kavirdesert": (1.0, 1.0, (198, 180, 148)),
    "lutdesert": (1.0, 1.0, (192, 150, 112)), "margodesert": (1.0, 1.0, (198, 162, 120)),
    "rigestan": (1.0, 1.0, (208, 154, 102)), "thardesert": (0.86, 0.8, (192, 162, 118)),
    "garagumdesert": (0.95, 0.9, (192, 172, 130)), "qizilqumdesert": (0.95, 0.9, (194, 174, 134)),
    "betpaqdaladesert": (0.88, 0.8, (180, 166, 130)), "taklimakandesert": (1.0, 1.0, (210, 186, 140)),
    "gobidesert": (0.95, 0.9, (168, 152, 122)), "muusdesert": (0.85, 0.8, (190, 170, 128)),
    "greatsandydesert": (0.95, 0.9, (196, 112, 66)), "gibsondesert": (0.93, 0.9, (184, 114, 74)),
    "greatvictoriadesert": (0.93, 0.9, (192, 124, 78)), "simpsondesert": (0.96, 0.9, (204, 122, 72)),
    "tanamidesert": (0.88, 0.85, (180, 114, 74)), "strzeleckidesert": (0.9, 0.85, (192, 130, 86)),
    "kalaharidesert": (0.7, 0.6, (180, 136, 94)), "namibdesert": (1.0, 1.0, (214, 160, 106)),
    "desiertodeatacama": (1.0, 1.0, (180, 154, 134)), "sonorandesert": (0.9, 0.8, (180, 154, 120)),
    "chihuahuandesert": (0.88, 0.8, (178, 158, 124)), "greatsaltlakedesert": (1.0, 1.0, (206, 196, 176)),
    "blackrockdesert": (0.95, 0.9, (186, 176, 156)), "whitesands": (1.0, 1.0, (236, 232, 222)),
    "bigbend": (0.85, 0.8, (168, 142, 112)), "caatingas": (0.62, 0.5, (150, 128, 92)),
    "bodeledepression": (1.0, 1.0, (218, 206, 180)), "aoukar": (1.0, 1.0, (210, 168, 118)),
    "punjab": (0.5, 0.6, None), "etoshapan": (0.95, 1.0, (222, 218, 204)),
    "makgadikgadipan": (0.9, 1.0, (220, 214, 200)), "salardeuyuni": (1.0, 1.0, (238, 236, 230)),
    # volcanic and sandstone massifs, escarpments
    "ahaggarmts": (1.0, 0.9, (112, 88, 70)), "tibestimts": (1.0, 0.9, (104, 84, 70)),
    "airmts": (0.95, 0.8, (122, 98, 78)), "alharujalaswad": (1.0, 1.0, (72, 62, 54)),
    "marrahmts": (None, 0, (122, 98, 78)), "ennediplat": (1.0, 0.8, (134, 100, 74)),
    "hejazmts": (None, 0, (114, 94, 76)), "asirmts": (None, 0, (104, 88, 72)),
    "alhajarmts": (None, 0, (126, 106, 88)), "tuwayqmts": (1.0, 0.8, (196, 166, 128)),
    "hadhramaut": (0.95, 0.8, (170, 138, 104)), "jilfalkabirplateau": (1.0, 1.0, (150, 118, 88)),
    "libyanplateau": (1.0, 0.9, (204, 176, 136)), "platdutademait": (1.0, 0.9, (176, 146, 110)),
    "tagant": (0.9, 0.7, (170, 132, 96)), "jabalalabyadplateau": (1.0, 0.9, (196, 176, 140)),
    "ahmarmts": (None, 0, (122, 98, 80)),
    # plains, basins, steppes, wetlands
    "amazonbasin": (0.0, 0.9, None), "congobasin": (0.02, 0.85, None), "selvas": (0.0, 0.8, None),
    "yungas": (0.1, 0.6, None), "sahel": (0.66, 0.6, (178, 140, 98)), "kazakhsteppe": (0.62, 0.6, None),
    "ponticsteppe": (0.5, 0.5, None), "pampas": (0.34, 0.5, None), "granchaco": (0.44, 0.5, None),
    "chacoboreal": (0.46, 0.5, None), "chacoaustral": (0.42, 0.5, None), "llanos": (0.46, 0.6, None),
    "nullarborplain": (0.82, 0.8, (178, 158, 122)), "turanlowland": (0.86, 0.6, None),
    "serengetiplains": (0.58, 0.6, None), "masaisteppe": (0.6, 0.6, None), "iwemberesteppe": (0.5, 0.5, None),
    "gangesplain": (0.32, 0.5, None), "northchinaplain": (0.42, 0.6, None), "manchurianplain": (0.3, 0.5, None),
    "hasaplain": (0.95, 0.8, None), "tihamah": (0.9, 0.7, None), "jabalnafusah": (0.85, 0.6, None),
    "llanoestacado": (0.64, 0.6, None), "greatbasin": (0.84, 0.6, None), "tarimbasin": (0.97, 0.8, None),
    "junggarbasin": (0.8, 0.7, None), "qaidambasin": (0.92, 0.8, (176, 166, 140)),
    "greatartesianbasin": (0.74, 0.5, None), "murraydarlingbasin": (0.56, 0.5, None),
    "sichuanbasin": (0.15, 0.6, None), "pantanal": (0.26, 0.6, None), "sundarbans": (0.0, 0.8, None),
    "entrerios": (0.3, 0.5, None), "sudd": (0.36, 0.6, None), "ogaden": (0.82, 0.7, (178, 132, 92)),
    "baluchistan": (0.88, 0.7, (170, 150, 122)), "mesopotamia": (0.78, 0.5, None),
    "patagonia": (0.74, 0.6, (158, 140, 108)), "anatolia": (0.55, 0.4, None), "hexicorridor": (0.84, 0.6, None),
    "kaokoland": (0.88, 0.7, (170, 132, 98)), "centralvalley": (0.55, 0.5, None),
    "ferganavalley": (0.45, 0.6, None), "caspiandepression": (0.78, 0.6, None),
    "coloradoplateau": (0.74, 0.5, (190, 144, 106)), "altiplano": (0.74, 0.6, (160, 140, 118)),
    "altiplaniciemexicana": (0.7, 0.4, None), "mongolianplateau": (0.66, 0.4, None),
    "plateauoftibet": (0.62, 0.4, (150, 132, 108)), "deccanplateau": (0.52, 0.4, None),
    "westernplateau": (0.84, 0.5, None), "barklytableland": (0.7, 0.5, None),
    "loessplateau": (0.56, 0.5, (176, 156, 120)), "ustyurtplateau": (0.9, 0.7, (188, 178, 150)),
    "kazakhupland": (0.66, 0.5, None), "greatkarroo": (0.8, 0.6, None), "northernkarroo": (0.82, 0.6, None),
    "columbiaplat": (0.64, 0.5, None),
}
REGION_DELTA = (0.18, 0.8, None)     # every "Delta" polygon: green, wet, farmed (the Nile delta)
TUNDRA_REGIONS = ("barrengrounds", "bolshezemelskayatundra", "northslope")
LAKE_DISTRICTS = ("canadianshield", "finnishlakeregion", "karelia", "lapland", "westernsiberianplain",
                  "northsiberianlowland", "kolymalowland", "yukonflats", "northslope", "barrengrounds",
                  "vychegdalowland", "superiorupland", "leslaurentides")
DESERT_RIVERS = ("nile", "damiettabranch", "rosettabranch", "alfurat", "euphrates", "firat", "tigris",
                 "dicle", "shattalarab", "indus", "amudarya", "syrdarya", "helmand")

# Plateau base elevations (m); mountain ranges take their height from the named peaks around them.
PLATEAU_HEIGHT = {
    "plateauoftibet": 4600, "altiplano": 3800, "mongolianplateau": 1500, "coloradoplateau": 1900,
    "altiplaniciemexicana": 1900, "deccanplateau": 600, "brazilianhighlands": 900, "planaltocentral": 1000,
    "planaltodomatogrosso": 600, "centralsiberianplateau": 700, "yunguiplateau": 1900, "loessplateau": 1300,
    "kazakhupland": 600, "peninsulaiberica": 700, "bieplateau": 1500, "katangaplateau": 1200,
    "khomashighland": 1800, "adamawaplateau": 1100, "fraserplateau": 1200, "columbiaplat": 800,
    "yukonplateau": 1200, "putoranaplateau": 1000, "aldanupland": 1000, "stanovoyupland": 1300,
    "shanplateau": 1000, "khoratplat": 200, "westernplateau": 450, "kimberleyplateau": 450,
    "massifcentral": 900, "americanhighland": 2500, "polarplateau": 2800, "ethiopianhighlands": 2400,
    "greatkarroo": 900, "northernkarroo": 1200, "huilaplateau": 1600, "josplateau": 1200,
    "tagant": 400, "ennediplat": 900, "jilfalkabirplateau": 900, "edwardsplateau": 600,
    "alleghenyplateau": 600, "cumberlandplat": 500, "ozarkplateau": 450, "superiorupland": 450,
    "guianashield": 500, "okhotskkolymaupland": 1000, "ustyurtplateau": 200, "libyanplateau": 250,
}
DEFAULT_PLATEAU = 700
RANGE_CREST = 0.62           # mean height of a range / highest named peak around it
DEFAULT_PEAK = 1600

# Lowest permanent-snow altitude (m) along |latitude|, before the dryness and continentality terms.
SNOWLINE = ((0, 4800), (10, 4900), (20, 5200), (30, 5300), (35, 4900), (40, 4100), (45, 3300),
            (50, 2600), (55, 2100), (60, 1700), (65, 1400), (70, 1000), (75, 600), (80, 300), (90, 0))
# Sea-level annual mean temperature (C) along |latitude| (the far south is a little colder).
T_ZONAL = ((0, 27), (10, 27), (20, 25), (30, 20), (40, 14), (50, 8), (60, 2), (70, -6), (80, -14), (90, -20))
# Arctic tree line (lat) along longitude.
TREELINE = ((-180, 64), (-165, 64.5), (-155, 67.5), (-140, 68.5), (-130, 68.5), (-120, 66), (-110, 63.5),
            (-100, 60.5), (-95, 58.8), (-90, 57), (-80, 56), (-75, 58), (-65, 57), (-60, 56), (-50, 62),
            (-20, 64), (0, 70), (10, 70), (20, 69.5), (30, 69), (40, 67.5), (50, 67), (60, 67), (70, 67),
            (80, 69), (90, 70.5), (100, 72), (110, 72), (120, 72), (130, 71), (140, 70.5), (150, 69.5),
            (160, 68.5), (170, 66), (180, 64))
# Sea-ice edges (late winter): the Arctic pack reaches south to this latitude, the Antarctic north to this.
ARCTIC_ICE_EDGE = ((-180, 63.5), (-170, 63), (-162, 64), (-155, 70.5), (-140, 70), (-120, 68), (-100, 61),
                   (-95, 57.5), (-85, 56.5), (-78, 58), (-70, 61.5), (-62, 63), (-56, 66), (-50, 69),
                   (-44, 61.5), (-38, 64.5), (-30, 67.5), (-20, 72), (-10, 75.5), (0, 78), (10, 80),
                   (20, 79), (30, 77.5), (40, 76.5), (50, 75.5), (55, 73), (60, 70), (80, 68), (100, 68),
                   (130, 68), (138, 59), (145, 58.5), (152, 59.5), (160, 62), (170, 63), (180, 63.5))
ANTARCTIC_ICE_EDGE = ((-180, -67), (-150, -69.5), (-120, -69.5), (-95, -69), (-75, -66), (-60, -62.5),
                      (-45, -61.5), (-30, -62), (-10, -63.5), (0, -64), (30, -65.5), (60, -65), (90, -64.5),
                      (120, -64.5), (150, -65.5), (180, -67))

# Clear water over carbonate banks: (lat, lon, radius deg, depth slope factor). An ordinary shelf
# deepens ~0.9 m per km from the coast; these banks and lagoons are far flatter and shallower.
BANKS = (
    (24.5, -77.5, 2.6, 0.10), (23.0, -75.8, 1.5, 0.12), (22.8, -79.5, 1.5, 0.2), (21.6, -80.5, 2.2, 0.22),
    (25.0, -80.9, 1.2, 0.25), (27.0, -83.5, 2.2, 0.6), (21.5, -90.0, 2.8, 0.45), (17.5, -88.0, 1.4, 0.3),
    (14.5, -82.5, 2.2, 0.4), (21.5, -71.6, 1.0, 0.15), (32.3, -64.8, 0.5, 0.25), (-12.0, 143.5, 2.5, 0.35),
    (-16.0, 146.0, 2.5, 0.35), (-19.5, 148.5, 2.5, 0.35), (-22.0, 151.5, 2.5, 0.35), (-10.0, 142.5, 2.0, 0.3),
    (21.0, 38.5, 4.5, 0.3), (15.0, 41.5, 2.5, 0.3), (27.5, 34.0, 1.5, 0.35), (26.0, 52.0, 3.5, 0.45),
    (20.0, -16.5, 1.5, 0.3), (-21.5, 165.5, 1.8, 0.3), (-17.5, 178.5, 1.8, 0.4), (3.0, 73.0, 3.0, 0.3),
    (-4.5, 55.5, 1.5, 0.5), (9.5, 79.5, 1.5, 0.5), (-13.0, 127.0, 3.5, 0.6), (-19.0, 119.5, 2.5, 0.7),
    (-6.5, 72.0, 1.0, 0.3), (22.5, -86.0, 1.0, 0.4), (-22.5, 43.5, 1.5, 0.5), (-12.5, 44.0, 2.5, 0.5),
)
# Sediment- and plankton-stained water: (lat, lon, radius deg, sRGB tint, strength).
TURBID = (
    (36.0, 122.5, 4.0, (56, 90, 82), 0.75), (38.8, 119.5, 1.8, (96, 102, 76), 0.85),
    (31.5, 122.3, 1.6, (100, 100, 72), 0.8), (28.0, 121.0, 2.0, (60, 90, 82), 0.5),
    (20.0, 107.5, 2.5, (56, 86, 76), 0.5), (10.0, 101.0, 3.0, (40, 76, 76), 0.4),
    (-5.0, 110.0, 5.0, (30, 66, 70), 0.4), (3.0, 100.5, 2.5, (40, 76, 70), 0.4),
    (21.3, 90.0, 2.2, (96, 100, 72), 0.75), (24.0, 67.3, 1.0, (90, 96, 76), 0.5),
    (29.5, 49.5, 1.2, (82, 96, 76), 0.5), (0.5, -49.0, 3.0, (112, 100, 68), 0.85),
    (4.0, -51.5, 2.5, (82, 92, 70), 0.6), (9.0, -60.5, 1.5, (92, 96, 70), 0.6),
    (-35.0, -56.8, 1.5, (122, 106, 72), 0.9), (-46.0, -63.0, 7.0, (22, 56, 62), 0.35),
    (29.0, -89.5, 1.2, (76, 92, 72), 0.5), (-15.0, 140.0, 4.0, (40, 86, 80), 0.45),
    (46.2, 36.6, 1.2, (62, 96, 76), 0.8), (45.7, 50.0, 2.0, (72, 102, 82), 0.8),
    (58.0, 20.0, 5.0, (16, 34, 34), 0.6), (55.0, 3.0, 4.0, (22, 44, 50), 0.4),
    (60.0, -170.0, 5.0, (22, 50, 54), 0.35), (45.0, -52.0, 3.0, (20, 44, 54), 0.3),
    (65.5, 38.0, 2.0, (26, 46, 46), 0.4), (45.5, 31.0, 2.0, (32, 62, 62), 0.5),
    (9.5, 106.5, 1.5, (82, 96, 72), 0.6), (22.0, 113.7, 1.0, (82, 96, 72), 0.5),
    (21.5, 72.3, 1.0, (102, 102, 76), 0.7), (15.5, 95.5, 2.0, (92, 96, 70), 0.65),
    (4.0, 6.0, 1.0, (62, 82, 70), 0.4), (-8.5, 143.5, 1.5, (82, 92, 70), 0.5),
    (45.0, -65.5, 1.0, (82, 86, 70), 0.5), (60.0, -85.0, 6.0, (22, 36, 40), 0.3),
)


def _key(name):
    s = unicodedata.normalize("NFKD", name or "")
    return "".join(c for c in s.lower() if "a" <= c <= "z")


def _linear(srgb):
    c = np.asarray(srgb, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _table(tab):
    a = np.asarray(tab, dtype=np.float64)
    return np.ascontiguousarray(a[:, 0]), np.ascontiguousarray(a[:, 1])


# ---------------------------------------------------------------------------
# Spherical helpers
# ---------------------------------------------------------------------------


def _blur(m, sigma_deg):
    """Gaussian blur of an equirectangular map by sigma_deg of great-circle arc: along each
    row with the longitude scale stretched by 1/cos(lat) (wrapping), then along columns
    continued across the poles (a row beyond the pole is the same row 180 degrees away)."""
    if sigma_deg <= 0:
        return m
    h, w = m.shape[:2]
    lat, _ = ne.grid(w)
    extra = (1,) * (m.ndim - 2)
    f = np.fft.rfftfreq(w, d=360.0 / w)
    s_lon = sigma_deg / np.maximum(np.cos(np.radians(lat)), 1e-3)
    kern = np.exp(-2.0 * math.pi ** 2 * (s_lon[:, None] * f[None, :]) ** 2).reshape((h, len(f)) + extra)
    out = np.fft.irfft(np.fft.rfft(m, axis=1) * kern, n=w, axis=1)
    pad = min(h, int(3.5 * sigma_deg * h / 180.0) + 1)
    top = np.roll(out[:pad][::-1], w // 2, axis=1)
    bot = np.roll(out[h - pad:][::-1], w // 2, axis=1)
    ext = np.concatenate([top, out, bot], axis=0)
    n = ext.shape[0] + pad
    fy = np.fft.rfftfreq(n, d=180.0 / h)
    ky = np.exp(-2.0 * math.pi ** 2 * (sigma_deg * fy) ** 2).reshape((len(fy), 1) + extra)
    res = np.fft.irfft(np.fft.rfft(ext, n=n, axis=0) * ky, n=n, axis=0)
    return res[pad:pad + h]


@njit(cache=True)
def _chamfer_km(src, row_dx_km, dy_km):
    """Distance (km) of every pixel to the nearest src pixel: two-pass 3x3 chamfer with the
    true east-west pixel size of each row, repeated so it wraps across the date line."""
    h, w = src.shape
    d = np.empty((h, w), np.float32)
    for i in range(h):
        for j in range(w):
            d[i, j] = 0.0 if src[i, j] else 1e9
    for _ in range(2):
        for i in range(h):
            dx = row_dx_km[i]
            dg = 0.0
            if i > 0:
                dxa = 0.5 * (dx + row_dx_km[i - 1])
                dg = math.sqrt(dxa * dxa + dy_km * dy_km)
            for j in range(w):
                best = min(d[i, j], d[i, (j - 1) % w] + dx)
                if i > 0:
                    best = min(best, d[i - 1, j] + dy_km)
                    best = min(best, d[i - 1, (j - 1) % w] + dg)
                    best = min(best, d[i - 1, (j + 1) % w] + dg)
                d[i, j] = best
        for i in range(h - 1, -1, -1):
            dx = row_dx_km[i]
            dg = 0.0
            if i < h - 1:
                dxa = 0.5 * (dx + row_dx_km[i + 1])
                dg = math.sqrt(dxa * dxa + dy_km * dy_km)
            for j in range(w - 1, -1, -1):
                best = min(d[i, j], d[i, (j + 1) % w] + dx)
                if i < h - 1:
                    best = min(best, d[i + 1, j] + dy_km)
                    best = min(best, d[i + 1, (j - 1) % w] + dg)
                    best = min(best, d[i + 1, (j + 1) % w] + dg)
                d[i, j] = best
    return d


def _distance_km(src):
    h, w = src.shape
    lat, _ = ne.grid(w)
    dx = (2 * math.pi * R_EARTH_KM / w) * np.maximum(np.cos(np.radians(lat)), 1e-4)
    return _chamfer_km(np.ascontiguousarray(src), dx.astype(np.float64), math.pi * R_EARTH_KM / h)


@njit(cache=True, parallel=True)
def _gauss_points(lat, vec, pts, out_vals, out_w):
    """Nadaraya-Watson interpolation of control points on the sphere with Gaussian weights in
    great-circle degrees. pts rows: (lat, x, y, z, radius_deg, value...); cut off at 3.5 radii."""
    h, w = vec.shape[:2]
    nv = out_vals.shape[2]
    for i in prange(h):
        for k in range(pts.shape[0]):
            r = pts[k, 4]
            if abs(lat[i] - pts[k, 0]) > 3.5 * r:
                continue
            cmin = math.cos(math.radians(min(3.5 * r, 180.0)))
            for j in range(w):
                d = vec[i, j, 0] * pts[k, 1] + vec[i, j, 1] * pts[k, 2] + vec[i, j, 2] * pts[k, 3]
                if d < cmin:
                    continue
                q = math.degrees(math.acos(min(d, 1.0))) / r
                wt = math.exp(-q * q)
                out_w[i, j] += wt
                for c in range(nv):
                    out_vals[i, j, c] += wt * pts[k, 5 + c]


def _interp_points(width, rows, prior_value, prior_weight):
    """Smooth field from (lat, lon, radius, values...) control points; far from every point it
    relaxes to prior_value (broadcastable to (H, W, nv))."""
    a = np.asarray(rows, dtype=np.float64)
    la, lo = np.radians(a[:, 0]), np.radians(a[:, 1])
    pts = np.column_stack([a[:, 0], np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la), a[:, 2:]])
    lat, _ = ne.grid(width)
    vec = ne.unit_vectors(width)
    nv = a.shape[1] - 3
    vals = np.zeros(vec.shape[:2] + (nv,))
    wts = np.zeros(vec.shape[:2])
    _gauss_points(lat, vec, np.ascontiguousarray(pts), vals, wts)
    prior = np.broadcast_to(prior_value, vals.shape)
    return (vals + prior * prior_weight) / (wts[..., None] + prior_weight)


@njit(cache=True)
def _peak_heights(vec, plat, plon, pelev, radius_deg, out):
    """out = max over named peaks within radius_deg of elevation * (1 - 0.3 (d / r)^2)."""
    h, w = vec.shape[:2]
    cmin = math.cos(math.radians(radius_deg))
    for k in range(plat.shape[0]):
        la, lo = math.radians(plat[k]), math.radians(plon[k])
        px, py, pz = math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)
        i0 = max(int((90.0 - plat[k] - radius_deg) / 180.0 * h), 0)
        i1 = min(int((90.0 - plat[k] + radius_deg) / 180.0 * h) + 1, h)
        for i in range(i0, i1):
            for j in range(w):
                d = vec[i, j, 0] * px + vec[i, j, 1] * py + vec[i, j, 2] * pz
                if d < cmin:
                    continue
                ang = math.degrees(math.acos(min(d, 1.0)))
                v = pelev[k] * (1.0 - 0.3 * (ang / radius_deg) ** 2)
                if v > out[i, j]:
                    out[i, j] = v


def _raster_local(features, width, ss=2):
    """Coverage of polygon features drawn only inside their bounding box: (r0, r1, c0, c1, tile)."""
    h = width // 2
    polys = ne.polygons(features)
    if not polys:
        return None
    pts = np.concatenate([rings[0] for rings in polys])
    c0 = max(int(math.floor((pts[:, 0].min() + 180.0) / 360.0 * width)) - 1, 0)
    c1 = min(int(math.ceil((pts[:, 0].max() + 180.0) / 360.0 * width)) + 1, width)
    r0 = max(int(math.floor((90.0 - pts[:, 1].max()) / 180.0 * h)) - 1, 0)
    r1 = min(int(math.ceil((90.0 - pts[:, 1].min()) / 180.0 * h)) + 1, h)
    img = Image.new("L", ((c1 - c0) * ss, (r1 - r0) * ss), 0)
    draw = ImageDraw.Draw(img)
    sx, sy = width * ss / 360.0, h * ss / 180.0
    for rings in polys:
        for k, ring in enumerate(rings):
            if len(ring) < 3:
                continue
            xy = np.stack([(ring[:, 0] + 180.0) * sx - c0 * ss, (90.0 - ring[:, 1]) * sy - r0 * ss], -1)
            draw.polygon([tuple(p) for p in xy], fill=255 if k == 0 else 0)
    tile = np.asarray(img.resize((c1 - c0, r1 - r0), Image.BOX), dtype=np.float64) / 255.0
    return r0, r1, c0, c1, tile


def _draw_lines(features, width, ss=2):
    """Anti-aliased coverage of (line feature, width km) pairs, e.g. rivers."""
    h = width // 2
    big = Image.new("L", (width * ss, h * ss), 0)
    draw = ImageDraw.Draw(big)
    sx, sy = width * ss / 360.0, h * ss / 180.0
    px_km = 2 * math.pi * R_EARTH_KM / (width * ss)
    for ft, km in features:
        g = ft["geometry"]
        lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        for ln in lines:
            a = np.asarray(ln, dtype=np.float64)[:, :2]
            if len(a) < 2:
                continue
            wpx = max(1, int(round(km / (px_km * max(math.cos(math.radians(a[:, 1].mean())), 0.2)))))
            xy = np.stack([(a[:, 0] + 180.0) * sx, (90.0 - a[:, 1]) * sy], -1)
            draw.line([tuple(p) for p in xy], fill=255, width=wpx, joint="curve")
    return np.asarray(big.resize((width, h), Image.BOX), dtype=np.float32) / 255.0


# ---------------------------------------------------------------------------
# Climate grid
# ---------------------------------------------------------------------------

CH_ARID, CH_TEMP, CH_ELEV, CH_MTN, CH_SOIL, CH_TUNDRA, CH_LAKES, CH_SNOWLINE = 0, 1, 2, 3, 4, 7, 8, 9
CH_BANK, CH_CLARITY, CH_TURBID, CH_TURBID_K = 10, 11, 12, 15


@lru_cache(maxsize=4)
def _climate(wc):
    """Low-resolution parameter maps (Hc, Wc, 16) that the full-resolution passes sample."""
    hc = wc // 2
    lat, lon = ne.grid(wc)
    alat = np.abs(lat)[:, None] * np.ones((1, wc))
    land = np.clip(ne.rasterize(ne.load("ne_50m_land"), wc, ss=2)
                   - ne.rasterize(ne.load("ne_50m_lakes"), wc, ss=2), 0, 1)

    # --- named regions ---
    by_key = {}
    for ft in ne.load("ne_10m_geography_regions_polys"):
        p = ft["properties"]
        by_key.setdefault((_key(p.get("NAME")), p.get("FEATURECLA")), []).append(ft)
    pin_num, pin_den = np.zeros((hc, wc)), np.zeros((hc, wc))
    soil_num, soil_den = np.zeros((hc, wc, 3)), np.zeros((hc, wc))
    ranges, plateau_h = np.zeros((hc, wc)), np.zeros((hc, wc))
    tundra, lakes_d = np.zeros((hc, wc)), np.zeros((hc, wc))
    for (k, cla), fts in by_key.items():
        spec = REGIONS.get(k)
        if spec is None and cla == "Desert":
            spec = (0.95, 0.8, None)
        if spec is None and cla == "Delta":
            spec = REGION_DELTA
        is_range = cla == "Range/mtn" and k not in PLATEAU_HEIGHT
        is_plat = (cla == "Plateau" or k in PLATEAU_HEIGHT) and not is_range
        if spec is None and not (is_range or is_plat or k in TUNDRA_REGIONS or k in LAKE_DISTRICTS):
            continue
        loc = _raster_local(fts, wc)
        if loc is None:
            continue
        r0, r1, c0, c1, m = loc
        sl = (slice(r0, r1), slice(c0, c1))
        if spec is not None:
            arid, strength, soil = spec
            if arid is not None and strength > 0:
                pin_num[sl] += m * strength * arid
                pin_den[sl] += m * strength
            if soil is not None:
                wt = 4.0 if k != "sahara" else 1.5
                soil_num[sl] += (m * wt)[..., None] * _linear(soil)
                soil_den[sl] += m * wt
        if is_range:
            ranges[sl] = np.maximum(ranges[sl], m)
        if is_plat:
            plateau_h[sl] = np.maximum(plateau_h[sl], m * PLATEAU_HEIGHT.get(k, DEFAULT_PLATEAU))
        if k in TUNDRA_REGIONS:
            tundra[sl] = np.maximum(tundra[sl], m)
        if k in LAKE_DISTRICTS:
            lakes_d[sl] = np.maximum(lakes_d[sl], m)

    # --- elevation (m): ranges scaled by the peaks around them, plateaus, lone volcanoes ---
    vec = ne.unit_vectors(wc)
    plon, plat, pp = ne.points(ne.load("ne_10m_geography_regions_elevation_points"), "elevation")
    pel = np.array([float(e) if e is not None else 0.0 for e in pp["elevation"]])
    ok = pel > 300
    regional = np.zeros((hc, wc))
    _peak_heights(vec, plat[ok], plon[ok], pel[ok], 4.0, regional)
    regional = np.where(regional > 0, regional, DEFAULT_PEAK)
    local = np.zeros((hc, wc))
    _peak_heights(vec, plat[ok], plon[ok], pel[ok], 0.35, local)
    mtn = _blur(ranges, 0.35)
    elev = np.maximum(mtn * regional * RANGE_CREST, _blur(plateau_h, 0.6))
    elev = np.maximum(_blur(elev, 0.4), _blur(local, 0.15) * 0.85)

    # --- aridity: control points, then the named regions ---
    prior = np.interp(alat, [0, 10, 20, 30, 45, 60, 75, 90], [0.15, 0.3, 0.6, 0.6, 0.35, 0.25, 0.5, 0.6])
    arid = _interp_points(wc, CLIMATE, prior[..., None], 0.02)[..., 0]
    pin_num, pin_den = _blur(pin_num, 0.5), _blur(pin_den, 0.5)
    pin = np.clip(pin_den, 0, 1)
    arid = np.clip(arid * (1 - pin) + pin_num / np.maximum(pin_den, 1e-6) * pin, 0.0, 1.0)

    # --- soil colour ---
    soil_pts = _interp_points(wc, [r[:3] + tuple(_linear(r[3])) for r in SOIL], _linear(DEFAULT_SOIL), 0.05)
    soil_num, soil_den = _blur(soil_num, 0.4), _blur(soil_den, 0.4)
    soil = (soil_pts + soil_num) / (1.0 + soil_den[..., None])

    # --- temperature (C): latitude, lapse rate, cold continental interiors ---
    lf = _blur(land, 8.0)
    cont = _smoothstep(0.5, 0.95, lf)
    t0, t1 = _table(T_ZONAL)
    temp = (np.interp(alat, t0, t1) - 2.0 * (lat[:, None] < -40) - 6.5e-3 * elev
            - 7.0 * cont * _smoothstep(35, 55, alat))

    # --- tundra: poleward of the tree line, above it in the mountains, and the named tundras ---
    tl0, tl1 = _table(TREELINE)
    tline = np.interp(lon, tl0, tl1)[None, :]
    tw = _smoothstep(tline - 1.5, tline + 2.0, lat[:, None])
    alpine = _smoothstep(-2.0, -9.0, temp) * _smoothstep(1000.0, 2500.0, elev)
    tw = np.maximum(np.maximum(tw, alpine), _blur(tundra, 0.6))

    # --- snow line: higher in dry and continental country ---
    sl0, sl1 = _table(SNOWLINE)
    snowline = (np.interp(alat, sl0, sl1) + 1000.0 * np.maximum(arid - 0.5, 0.0)
                - 700.0 * np.maximum(0.3 - arid, 0.0) + 700.0 * cont)

    # --- ocean: flat carbonate banks, clear tropical water, sediment ---
    banks = _interp_points(wc, BANKS, np.array([1.0]), 0.03)[..., 0]
    tur = _interp_points(wc, [r[:3] + tuple(_linear(r[3])) + (r[4],) for r in TURBID], np.zeros(4), 0.03)
    clarity = 0.3 * _smoothstep(36.0, 24.0, alat) + 0.7 * np.clip((1.0 - banks) / 0.6, 0.0, 1.0)

    ch = [arid, temp, elev, mtn, soil[..., 0], soil[..., 1], soil[..., 2], tw, _blur(lakes_d, 0.3), snowline,
          banks, clarity, tur[..., 0], tur[..., 1], tur[..., 2], tur[..., 3]]
    return np.ascontiguousarray(np.stack(ch, -1).astype(np.float64))


# ---------------------------------------------------------------------------
# Full-resolution passes
# ---------------------------------------------------------------------------


@njit(cache=True)
def _fbm(x, y, z, octaves, seed):
    """Fractal value noise, 0..1, each octave rotated so the lattices never line up."""
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        total += amp * bh.value_noise3(x, y, z, seed + 31 * o)
        norm += amp
        amp *= 0.5
        x, y, z = ((0.36 * x + 0.48 * y - 0.80 * z) * 2.03, (-0.80 * x + 0.60 * y) * 2.03,
                   (0.48 * x + 0.64 * y + 0.60 * z) * 2.03)
    return total / norm


@njit(cache=True)
def _ridged(x, y, z, octaves, seed):
    """Ridged multifractal, 0..1: sharp crests, soft valleys."""
    total, amp, norm, prev = 0.0, 1.0, 0.0, 1.0
    for o in range(octaves):
        n = 1.0 - abs(2.0 * bh.value_noise3(x, y, z, seed + 53 * o) - 1.0)
        n = n * n
        total += amp * n * (0.4 + 0.6 * prev)
        prev = n
        norm += amp
        amp *= 0.5
        x, y, z = ((0.36 * x + 0.48 * y - 0.80 * z) * 2.1, (-0.80 * x + 0.60 * y) * 2.1,
                   (0.48 * x + 0.64 * y + 0.60 * z) * 2.1)
    return total / norm


@njit(cache=True, inline="always")
def _ss(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


@njit(cache=True)
def _interp1(xs, ys, x):
    n = xs.shape[0]
    if x <= xs[0]:
        return ys[0]
    if x >= xs[n - 1]:
        return ys[n - 1]
    k = 1
    while xs[k] < x:
        k += 1
    return ys[k - 1] + (ys[k] - ys[k - 1]) * (x - xs[k - 1]) / (xs[k] - xs[k - 1])


@njit(cache=True, inline="always")
def _sample(cm, lat, lon, c):
    h, w = cm.shape[0], cm.shape[1]
    y = min(max((90.0 - lat) / 180.0 * h - 0.5, 0.0), h - 1.001)
    x = (lon + 180.0) / 360.0 * w - 0.5
    i = int(y)
    fy = y - i
    j = int(math.floor(x))
    fx = x - j
    j0 = j % w
    j1 = (j + 1) % w
    return ((cm[i, j0, c] * (1 - fx) + cm[i, j1, c] * fx) * (1 - fy)
            + (cm[i + 1, j0, c] * (1 - fx) + cm[i + 1, j1, c] * fx) * fy)


@njit(cache=True, inline="always")
def _ramp(pal, a, k):
    """Channel k of a 4-stop colour ramp at aridity 0, 0.2, 0.4, 0.6 (clamped)."""
    t = min(max(a / 0.2, 0.0), 2.999)
    i = int(t)
    f = t - i
    return pal[i, k] * (1 - f) + pal[i + 1, k] * f


@njit(cache=True, parallel=True)
def _terrain(lat_a, lon_a, land, cm, octaves, seed, wlat, wlon, ridge, height):
    """Pass 1 (land pixels): the domain-warped climate coordinates and the height field (m)."""
    h, w = land.shape
    for i in prange(h):
        cla, sla = math.cos(math.radians(lat_a[i])), math.sin(math.radians(lat_a[i]))
        for j in range(w):
            if land[i, j] <= 0.0:
                continue
            px, py, pz = cla * math.cos(math.radians(lon_a[j])), cla * math.sin(math.radians(lon_a[j])), sla
            wx = (_fbm(px * 3.1 + 11.3, py * 3.1, pz * 3.1, 3, seed) - 0.5) * WARP_BIG * 2.0
            wy = (_fbm(px * 3.1, py * 3.1 + 7.7, pz * 3.1, 3, seed + 1) - 0.5) * WARP_BIG * 2.0
            wz = (_fbm(px * 3.1, py * 3.1, pz * 3.1 + 3.9, 3, seed + 2) - 0.5) * WARP_BIG * 2.0
            wx += (_fbm(px * 16.0 + 5.1, py * 16.0, pz * 16.0, 3, seed + 3) - 0.5) * WARP_SMALL * 2.0
            wy += (_fbm(px * 16.0, py * 16.0 + 2.3, pz * 16.0, 3, seed + 4) - 0.5) * WARP_SMALL * 2.0
            wz += (_fbm(px * 16.0, py * 16.0, pz * 16.0 + 8.8, 3, seed + 5) - 0.5) * WARP_SMALL * 2.0
            qx, qy, qz = px + wx, py + wy, pz + wz
            qn = math.sqrt(qx * qx + qy * qy + qz * qz)
            la = math.degrees(math.asin(min(max(qz / qn, -1.0), 1.0)))
            lo = math.degrees(math.atan2(qy, qx))
            wlat[i, j] = la
            wlon[i, j] = lo
            elev = _sample(cm, la, lo, CH_ELEV)
            mtn = _sample(cm, la, lo, CH_MTN)
            r = 0.0
            hgt = 300.0 * _fbm(px * 40.0, py * 40.0, pz * 40.0, 4, seed + 6)
            if elev > 150.0:
                r = _ridged(qx * 20.0, qy * 20.0, qz * 20.0, octaves, seed + 30)
                amp = elev * (0.3 + 0.7 * min(mtn * 1.3, 1.0))
                big = 0.75 + 0.5 * _fbm(px * 6.0, py * 6.0, pz * 6.0, 3, seed + 7)
                hgt += max(elev * big - 0.55 * amp + amp * 1.25 * r, 0.0)
            ridge[i, j] = r
            height[i, j] = hgt


def _hillshade(height, land):
    """Lambertian shading of the height field relative to flat ground (1 = flat, land only)."""
    h, w = height.shape
    lat, _ = ne.grid(w)
    dx = (2 * math.pi * R_EARTH_KM * 1000.0 / w) * np.maximum(np.cos(np.radians(lat)), 0.05)[:, None]
    dy = math.pi * R_EARTH_KM * 1000.0 / h
    gx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) / (2.0 * dx) * HILLSHADE_EXAG
    gy = np.zeros_like(height)
    gy[1:-1] = (height[:-2] - height[2:]) / (2.0 * dy) * HILLSHADE_EXAG       # north-positive
    az, alt = math.radians(HILLSHADE_AZ), math.radians(HILLSHADE_ALT)
    lx, ly, lz = math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt)
    shade = (-gx * lx - gy * ly + lz) / np.sqrt(gx * gx + gy * gy + 1.0) / lz
    return np.where(land > 0, np.clip(1.0 + HILLSHADE_GAIN * (shade - 1.0), 0.35, 1.6), 1.0)


@njit(cache=True, parallel=True)
def _compose(lat_a, lon_a, land, lake, glac, shelf_ice, depth, dland, river, playa, cm,
             wlat, wlon, ridge, height, shade, pal_trop, pal_temp, pal_bor, cols,
             ice_n0, ice_n1, ice_s0, ice_s1, seed, albedo, ice_out):
    """Pass 2: the reflectance and ice cover of every pixel."""
    h, w = land.shape
    for i in prange(h):
        la = lat_a[i]
        cla, sla = math.cos(math.radians(la)), math.sin(math.radians(la))
        rgb = np.empty(3)
        for j in range(w):
            lo = lon_a[j]
            px, py, pz = cla * math.cos(math.radians(lo)), cla * math.sin(math.radians(lo)), sla
            lf = land[i, j]
            wf = 1.0 - lf
            land_ice = 0.0
            for k in range(3):
                rgb[k] = 0.0
            if lf > 0.0:
                wla, wlo = wlat[i, j], wlon[i, j]
                arid = _sample(cm, wla, wlo, CH_ARID)
                temp = _sample(cm, wla, wlo, CH_TEMP)
                mtn = _sample(cm, wla, wlo, CH_MTN)
                tun = _sample(cm, wla, wlo, CH_TUNDRA)
                lakes_d = _sample(cm, wla, wlo, CH_LAKES)
                snowline = _sample(cm, wla, wlo, CH_SNOWLINE)
                s_r = _sample(cm, wla, wlo, CH_SOIL)
                s_g = _sample(cm, wla, wlo, CH_SOIL + 1)
                s_b = _sample(cm, wla, wlo, CH_SOIL + 2)
                lum = 0.2126 * s_r + 0.7152 * s_g + 0.0722 * s_b
                n_patch = _fbm(px * 8.0, py * 8.0, pz * 8.0, 4, seed + 10)
                n_mid = _fbm(px * 30.0, py * 30.0, pz * 30.0, 3, seed + 11)
                n_fine = _fbm(px * 110.0, py * 110.0, pz * 110.0, 3, seed + 12)
                # leaf cover: forest, fields and scrub in patches around the climate value
                a = arid + 0.55 * (n_patch - 0.5) + 0.35 * (n_mid - 0.5) + 0.15 * (n_fine - 0.5)
                a = min(max(a, 0.0), 1.0)
                trop = _ss(17.0, 23.0, temp)
                bor = _ss(4.0, -3.0, temp)
                tem = max(1.0 - trop - bor, 0.0)
                ar = min(a, 0.6)
                bare = _ss(0.45, 0.97, a)
                # bare ground: sand and gravel with darker rock outcrops
                rock = _ss(0.48, 0.66, _fbm(px * 14.0 + 3.3, py * 14.0, pz * 14.0, 4, seed + 13)) * 0.7
                tw = min(max(tun + 0.3 * (n_patch - 0.5), 0.0), 1.0)
                pd = _ss(74.0, 80.0, abs(la))
                rv = min(max(river[i, j] * _ss(0.45, 0.8, a) * (0.6 + 0.8 * (n_mid - 0.5)), 0.0), 1.0)
                lk = 0.0
                if lakes_d > 0.02:
                    lk = lakes_d * _ss(0.6, 0.7, _fbm(px * 420.0, py * 420.0, pz * 420.0, 2, seed + 40)) * 0.7
                pl = playa[i, j]
                m = min(mtn * 1.3, 1.0)
                tex = ((1.0 + 0.5 * (n_fine - 0.5) + 0.35 * (n_mid - 0.5)) * shade[i, j]
                       * (1.0 - m * (0.22 - 0.3 * ridge[i, j])))
                snow = _ss(snowline - 150.0, snowline + 500.0, height[i, j])
                ant = 1.0 if la < -60.0 else 0.0
                land_ice = max(max(glac[i, j], ant), snow)
                for k in range(3):
                    veg = trop * _ramp(pal_trop, ar, k) + tem * _ramp(pal_temp, ar, k) + bor * _ramp(pal_bor, ar, k)
                    s = s_r if k == 0 else (s_g if k == 1 else s_b)
                    soil = s * (1.0 - rock) + (0.55 * lum + 0.45 * s) * 0.68 * rock
                    c = veg * (1.0 - bare) + soil * bare
                    c = c * (1.0 - tw) + (cols[0, k] * (1.0 - pd) + cols[1, k] * pd) * tw
                    c = c * (1.0 - rv) + cols[3, k] * rv
                    c = c * (1.0 - lk) + cols[11, k] * lk
                    c = c * (1.0 - pl) + cols[4, k] * pl
                    c *= tex
                    c = c * (1.0 - land_ice) + cols[5, k] * min(shade[i, j], 1.05) * land_ice
                    rgb[k] = c * lf
            sea_ice = 0.0
            if wf > 0.0:
                lk = min(lake[i, j], wf) / wf
                bank = _sample(cm, la, lo, CH_BANK)
                clar = _sample(cm, la, lo, CH_CLARITY)
                n_o = _fbm(px * 14.0, py * 14.0, pz * 14.0, 4, seed + 50)
                dep = depth[i, j]
                if dep < 200.0:
                    dep = dep * bank + 1.0
                shelf = _ss(150.0, 20.0, dep) * 0.6
                vis = min(clar * math.exp(-dep / 10.0) * (0.8 + 0.4 * n_o), 0.95)
                tau = (_sample(cm, la, lo, CH_TURBID_K) * math.exp(-dland[i, j] / 300.0)
                       * _ss(260.0, 60.0, depth[i, j]))
                tau = min(tau * (0.75 + 0.5 * n_o), 0.95)
                si = 0.0
                if la > 45.0 or la < -50.0:
                    n1 = _fbm(px * 5.0 + 2.0, py * 5.0, pz * 5.0, 4, seed + 60)
                    n2 = _fbm(px * 25.0, py * 25.0, pz * 25.0, 3, seed + 61)
                    if la > 0:
                        x = la - _interp1(ice_n0, ice_n1, lo)
                    else:
                        x = _interp1(ice_s0, ice_s1, lo) - la
                    x += 7.0 * (n1 - 0.5) + 2.5 * (n2 - 0.5)
                    conc = _ss(-0.3, 0.4, x)
                    if conc > 0.0:
                        # the marginal ice zone breaks into floes; leads crack the pack
                        floes = _fbm(px * 90.0, py * 90.0, pz * 90.0, 3, seed + 63)
                        conc *= _ss(0.62, 0.48, floes - 0.08 * min(x, 2.0))
                        leads = _ridged(px * 60.0, py * 60.0, pz * 60.0, 3, seed + 62)
                        conc *= 1.0 - 0.5 * _ss(0.7, 0.92, leads)
                        si = conc * (1.0 - lk)
                sh = min(shelf_ice[i, j] / wf, 1.0) if wf > 1e-6 else 0.0
                for k in range(3):
                    c = cols[6, k] * (1.0 - shelf) + cols[7, k] * shelf
                    c = c * (1.0 - vis) + cols[8, k] * vis
                    if tau > 0.0:
                        c = c * (1.0 - tau) + _sample(cm, la, lo, CH_TURBID + k) * tau
                    c *= 1.0 + 0.16 * (n_o - 0.5)
                    c = c * (1.0 - si) + cols[9, k] * (0.9 + 0.2 * n_o) * si
                    c = c * (1.0 - sh) + cols[5, k] * sh
                    c = c * (1.0 - lk) + cols[10, k] * lk
                    rgb[k] += c * wf
                sea_ice = max(si, sh)
            for k in range(3):
                albedo[i, j, k] = rgb[k]
            ice_out[i, j] = land_ice * lf + sea_ice * wf


@lru_cache(maxsize=4)
def surface_maps(width=2048):
    """Clear-sky surface maps of the whole Earth on a (width // 2, width) equirectangular grid.

    Returns a dict of float32 arrays:
      'land'   (H, W)    land fraction 0..1 (lakes are water), anti-aliased coasts
      'water'  (H, W)    1 - land
      'ice'    (H, W)    ice and snow cover 0..1 (ice sheets, glaciers, mountain snow, sea ice)
      'albedo' (H, W, 3) linear-sRGB reflectance 0..1, ocean and ice included
      'relief' (H, W)    0..1 mountain relief (height / 7 km, compressed) for bump shading
    """
    h = width // 2
    lat, lon = ne.grid(width)
    land_raw = ne.rasterize(ne.load("ne_50m_land"), width)
    lakes = np.clip(ne.rasterize(ne.load("ne_50m_lakes"), width), 0, 1)
    land = np.clip(land_raw - lakes, 0.0, 1.0)
    lake = np.minimum(lakes, land_raw)
    glac = ne.rasterize(ne.load("ne_50m_glaciated_areas"), width)
    shelf_ice = np.minimum(np.clip(ne.rasterize(ne.load("ne_50m_antarctic_ice_shelves_polys"), width), 0, 1),
                           1.0 - land)
    deep = ne.rasterize(ne.load("ne_10m_bathymetry_K_200"), width) > 0.5
    is_land = land_raw > 0.5
    dland = _distance_km(is_land)
    ddeep = _distance_km(deep & ~is_land)
    # ~0.9 m per km off the coast, steepening into the 200 m shelf edge
    depth = np.maximum(np.minimum(0.9 * dland, 200.0), 200.0 * np.exp(-ddeep / 25.0))
    depth = np.where(deep, 400.0, depth)
    rivers = [(ft, 8.0 if (ft["properties"].get("scalerank") or 6) <= 3 else 5.0)
              for ft in ne.load("ne_50m_rivers_lake_centerlines")
              if _key(ft["properties"].get("name")) in DESERT_RIVERS]
    river = _draw_lines(rivers, width)
    playa = np.clip(ne.rasterize(ne.load("ne_10m_playas"), width), 0, 1) * 0.85

    cm = _climate(min(WORK_WIDTH, max(512, width)))
    f64 = lambda a: np.ascontiguousarray(a, dtype=np.float64)  # noqa: E731
    lat64, lon64, land64 = f64(lat), f64(lon), f64(land)
    wlat, wlon = np.zeros((h, width)), np.zeros((h, width))
    ridge, height = np.zeros((h, width)), np.zeros((h, width))
    octaves = 5 + max(0, int(round(math.log2(width / 2048.0))))
    _terrain(lat64, lon64, land64, cm, octaves, SEED, wlat, wlon, ridge, height)
    shade = _hillshade(height, land)

    cols = np.stack([_linear(c) for c in (TUNDRA, POLAR_DESERT, LAKE_WATER, IRRIGATED, PLAYA, SNOW, DEEP_OCEAN,
                                           SHELF_WATER, TURQUOISE, SEA_ICE, LAKE_WATER, LAKE_SPECKLE)])
    pals = [np.ascontiguousarray(np.stack([_linear(c) for c in p])) for p in (VEG_TROPICAL, VEG_TEMPERATE, VEG_BOREAL)]
    n0, n1 = _table(ARCTIC_ICE_EDGE)
    s0, s1 = _table(ANTARCTIC_ICE_EDGE)
    albedo = np.zeros((h, width, 3))
    ice = np.zeros((h, width))
    _compose(lat64, lon64, land64, f64(lake), f64(glac), f64(shelf_ice), f64(depth), f64(dland), f64(river),
             f64(playa), cm, wlat, wlon, ridge, height, f64(shade), pals[0], pals[1], pals[2], cols,
             n0, n1, s0, s1, SEED, albedo, ice)
    relief = np.clip(height / 7000.0, 0.0, 1.0) ** 0.6 * land
    return {
        "land": land.astype(np.float32),
        "water": (1.0 - land).astype(np.float32),
        "ice": np.clip(ice, 0, 1).astype(np.float32),
        "albedo": np.clip(albedo, 0, 1).astype(np.float32),
        "relief": relief.astype(np.float32),
    }
