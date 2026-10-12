"""The real night sky over the Diamond SMP.

The pack's black hole *is* Sagittarius A*, the 4-million-solar-mass black hole at
the centre of the Milky Way. This module places the real sky around it: every
star of the Yale Bright Star Catalogue (BSC5, public domain, ~9100 stars down to
V ~ 6.5, i.e. everything a dark-sky naked eye can see) at its true J2000
position, magnitude and colour temperature, plus the real galactic frame so the
Milky Way band passes exactly through the hole.

Observer
--------
Sgr A* has to sit due SOUTH at 24 degrees altitude in the Minecraft sky
(world direction ``bh.mc_direction(0, -24)``). A star is highest when it is on
the meridian, at altitude ``90 - latitude + dec``, so

* local sidereal time  LST = RA(Sgr A*)         = 266.41683 deg (17h 45m 40s)
* latitude             phi = 90 - 24 + dec(Sgr A*) = 36.99219 deg N

That is a mid-northern observer (Southern California / Andalusia / Japan) on a
summer evening: LST 17h45m is about 22:15 local mean solar time in mid-July
(23:15 on a daylight-saving clock), when Scorpius and the Sagittarius "teapot"
stand on the southern horizon, the Summer Triangle is overhead, the Big Dipper
hangs in the north-west and Cassiopeia climbs in the north-east.

Public API
----------
LATITUDE_DEG, LST_DEG                       observer (degrees)
SGR_A_WORLD, GALACTIC_NORTH_WORLD, GALACTIC_CENTRE_WORLD   unit vectors, world frame
EQUATORIAL_TO_WORLD, GALACTIC_TO_WORLD      3x3 rotations (world = M @ v)
equatorial_to_world(ra_deg, dec_deg)        -> (..., 3) world unit vectors (vectorised)
world_to_equatorial(world)                  -> (ra_deg, dec_deg)
galactic_to_world(l_deg, b_deg) / world_to_galactic(world)
horizontal(world) -> (alt_deg, az_deg)      azimuth from north through east
horizontal_to_world(alt_deg, az_deg)
catalog_stars(mag_limit=6.6)                -> (world_dirs (N,3), vmag (N,), temp_K (N,))
named_star(name)                            -> world unit vector or None
star_info(name)                             -> dict (hr, designation, names, ra/dec, vmag, temp_K, alt/az, world)
make_galaxy_kwargs(w2s, mag_limit=6.6)      -> kwargs for bh.make_galaxy in a renderer scene frame
render_allsky_preview(path) / render_view_preview(path, look_dir=None)   PNG previews

Frames
------
Minecraft world: x = east, y = up, z = south (so north = -z, west = -x).
Equatorial J2000: unit vector (cos d cos a, cos d sin a, sin d). The mapping is
the constant proper rotation ``EQUATORIAL_TO_WORLD`` (det = +1, so the sky is
never mirrored); directions below the horizon are just as valid, the sky
texture is a full sphere.

Precession (0.36 deg since J2000), nutation, aberration, proper motion and
atmospheric refraction are ignored: they are far below a sky texel and the
frame is pinned to Sgr A* anyway.
"""

import ast
import json
import math
import os
import re
import urllib.request
from functools import lru_cache

import numpy as np

import blackhole as bh

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(HERE, ".cache", "bsc5.json")
CATALOG_URL = "https://raw.githubusercontent.com/brettonw/YaleBrightStarCatalog/master/bsc5.json"

# ---------------------------------------------------------------------------
# Reference positions (J2000, degrees)
# ---------------------------------------------------------------------------

SGR_A_RA_DEG, SGR_A_DEC_DEG = 266.41683, -29.00781      # Sgr A* (radio source, Reid & Brunthaler 2004)
NGP_RA_DEG, NGP_DEC_DEG = 192.85948, 27.12825            # north galactic pole (IAU 1958 -> FK5)
GC_RA_DEG, GC_DEC_DEG = 266.40499, -28.93617             # galactic centre, l = 0, b = 0

BH_ALTITUDE_DEG = 24.0                                   # where the pack draws the hole (due south)
LATITUDE_DEG = 90.0 - BH_ALTITUDE_DEG + SGR_A_DEC_DEG    # 36.99219 N
LST_DEG = SGR_A_RA_DEG                                   # Sgr A* on the meridian

DEFAULT_TEMP_K = 5800.0


def _eq_to_world_matrix(lat_deg, lst_deg):
    """Rotation taking J2000 equatorial unit vectors to Minecraft world directions."""
    p = math.radians(lat_deg)
    meridian = np.array([0.0, math.cos(p), math.sin(p)])   # hour angle 0, dec 0 (south, alt 90-lat)
    west = np.array([-1.0, 0.0, 0.0])                      # hour angle +6h, dec 0
    ncp = np.array([0.0, math.sin(p), -math.cos(p)])       # north celestial pole (north, alt = lat)
    # Hour angle H = LST - RA grows westwards:
    #   v = cos(d) cos(H) meridian + cos(d) sin(H) west + sin(d) ncp
    s = math.radians(lst_deg)
    c0 = math.cos(s) * meridian + math.sin(s) * west     # image of RA 0h
    c1 = math.sin(s) * meridian - math.cos(s) * west     # image of RA 6h
    return np.stack([c0, c1, ncp], axis=1)


EQUATORIAL_TO_WORLD = _eq_to_world_matrix(LATITUDE_DEG, LST_DEG)


def equatorial_unit(ra_deg, dec_deg):
    """J2000 equatorial unit vector(s), shape (..., 3)."""
    a = np.radians(np.asarray(ra_deg, dtype=np.float64))
    d = np.radians(np.asarray(dec_deg, dtype=np.float64))
    a, d = np.broadcast_arrays(a, d)
    cd = np.cos(d)
    return np.stack([cd * np.cos(a), cd * np.sin(a), np.sin(d)], axis=-1)


def equatorial_to_world(ra_deg, dec_deg):
    """Minecraft world direction(s) of J2000 (RA, Dec) in degrees. Vectorised, returns (..., 3)."""
    return equatorial_unit(ra_deg, dec_deg) @ EQUATORIAL_TO_WORLD.T


def world_to_equatorial(world):
    """Inverse of equatorial_to_world: (ra_deg in [0, 360), dec_deg)."""
    e = bh.normalize(world) @ EQUATORIAL_TO_WORLD  # inverse of a rotation is its transpose
    ra = np.degrees(np.arctan2(e[..., 1], e[..., 0])) % 360.0
    dec = np.degrees(np.arcsin(np.clip(e[..., 2], -1.0, 1.0)))
    return ra, dec


def horizontal(world):
    """(altitude_deg, azimuth_deg) of world direction(s); azimuth from north through east."""
    v = bh.normalize(world)
    alt = np.degrees(np.arcsin(np.clip(v[..., 1], -1.0, 1.0)))
    az = np.degrees(np.arctan2(v[..., 0], -v[..., 2])) % 360.0
    return alt, az


def horizontal_to_world(alt_deg, az_deg):
    """World direction(s) of an (altitude, azimuth-from-north-through-east) pair."""
    alt = np.radians(np.asarray(alt_deg, dtype=np.float64))
    az = np.radians(np.asarray(az_deg, dtype=np.float64))
    alt, az = np.broadcast_arrays(alt, az)
    ca = np.cos(alt)
    return np.stack([ca * np.sin(az), np.sin(alt), -ca * np.cos(az)], axis=-1)


SGR_A_WORLD = equatorial_to_world(SGR_A_RA_DEG, SGR_A_DEC_DEG)
GALACTIC_NORTH_WORLD = equatorial_to_world(NGP_RA_DEG, NGP_DEC_DEG)
GALACTIC_CENTRE_WORLD = equatorial_to_world(GC_RA_DEG, GC_DEC_DEG)


def _galactic_basis():
    """Rows: l=0 (centre), l=90 (towards Cygnus, the direction of rotation), b=90 (pole)."""
    gn = bh.normalize(GALACTIC_NORTH_WORLD)
    gc = bh.normalize(GALACTIC_CENTRE_WORLD - gn * np.dot(GALACTIC_CENTRE_WORLD, gn))
    return np.stack([gc, np.cross(gn, gc), gn])


GALACTIC_TO_WORLD = _galactic_basis().T


def galactic_to_world(l_deg, b_deg):
    """World direction(s) of galactic longitude/latitude (degrees), shape (..., 3)."""
    l = np.radians(np.asarray(l_deg, dtype=np.float64))
    b = np.radians(np.asarray(b_deg, dtype=np.float64))
    l, b = np.broadcast_arrays(l, b)
    cb = np.cos(b)
    return np.stack([cb * np.cos(l), cb * np.sin(l), np.sin(b)], axis=-1) @ GALACTIC_TO_WORLD.T


def world_to_galactic(world):
    """(l_deg in [0, 360), b_deg) of world direction(s)."""
    g = bh.normalize(world) @ GALACTIC_TO_WORLD
    l = np.degrees(np.arctan2(g[..., 1], g[..., 0])) % 360.0
    b = np.degrees(np.arcsin(np.clip(g[..., 2], -1.0, 1.0)))
    return l, b


def angle_deg(a, b):
    """Angle between two (arrays of) directions, robust for tiny angles."""
    a, b = bh.normalize(a), bh.normalize(b)
    return np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, axis=-1)))


# ---------------------------------------------------------------------------
# Catalogue parsing
# ---------------------------------------------------------------------------

_NUM = re.compile(r"\d+(?:\.\d*)?|\.\d+")
_MINUS = ("-", "−", "–", "‒")


def _sexagesimal(text):
    parts = [float(x) for x in _NUM.findall(text)][:3]
    if not parts:
        raise ValueError(f"no numbers in {text!r}")
    parts += [0.0] * (3 - len(parts))
    return parts[0] + parts[1] / 60.0 + parts[2] / 3600.0


def parse_ra(value):
    """Right ascension -> degrees. Accepts '00h 05m 09.9s', '0 5 9.9', '00:05:09.9' (hours)
    or a plain number (taken as degrees)."""
    if isinstance(value, (int, float)):
        return float(value)
    return 15.0 * _sexagesimal(str(value))


def parse_dec(value):
    """Declination -> degrees. Accepts '+45° 13′ 45″', '-00 30 11', '-00:30:11' or a number."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    sign = -1.0 if text[:1] in _MINUS else 1.0  # sign first: '-00 30 11' is negative
    return sign * _sexagesimal(text)


def _float(value):
    if value is None:
        return None
    try:
        out = float(str(value).strip().replace("−", "-"))
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def bv_to_temperature(bv):
    """Ballesteros (2012) colour temperature from B-V: T = 4600 (1/(0.92 BV + 1.7) + 1/(0.92 BV + 0.62))."""
    bv = np.clip(np.asarray(bv, dtype=np.float64), -0.4, 2.2)
    return 4600.0 * (1.0 / (0.92 * bv + 1.7) + 1.0 / (0.92 * bv + 0.62))


def _temperature(rec):
    k = _float(rec.get("K"))
    if k is not None and 1000.0 <= k <= 60000.0:
        return k
    bv = _float(rec.get("B-V"))
    if bv is not None:
        return float(bv_to_temperature(bv))
    return DEFAULT_TEMP_K


def _download(path=CATALOG_PATH, url=CATALOG_URL):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as fh:
        fh.write(resp.read())
    with open(tmp, encoding="utf-8") as fh:
        json.load(fh)  # refuse to cache a truncated / HTML error page
    os.replace(tmp, path)


def _squash(text):
    """Normalised name key: lower case, no spaces / hyphens / apostrophes / dots."""
    return re.sub(r"[\s\-'_.’]+", "", str(text).lower())


_ALIAS_TOKEN = re.compile(r"^[A-Z][A-Za-z'’\- ]{2,30}$")
_ALIAS_LEAD = {"also", "called", "according", "name", "formerly", "see", "in", "not", "same", "the", "of",
               "sometimes", "with", "dm", "however", "bayer", "heis", "heis-hr", "pgc-bac"}
_ALIAS_STOP = {"called", "according", "says", "gives", "shared", "unnamed", "is", "this", "number", "allen",
               "becvar", "cod", "dm", "hd", "hr", "previous", "named", "re-named", "originally", "catalogues",
               "superscripts", "retained", "followers", "boundary", "kids", "third"}


def _note_list(notes):
    """BSC 'Notes' as a list of {'Category', 'Remark'} dicts (it may be a list or its repr)."""
    if isinstance(notes, list):
        return notes
    if isinstance(notes, str) and notes.strip().startswith("["):
        try:
            return json.loads(notes)
        except ValueError:
            try:
                return ast.literal_eval(notes)
            except (ValueError, SyntaxError):
                return []
    return []


def _record_names(rec):
    """Proper names carried by a catalogue record: a 'Common' field if present, and the
    BSC5 'Star names' remarks ('VEGA; Wega; Fidis; Harp Star.'). Only name-like tokens are
    kept, so remarks such as '4 Cet in Psc.' or 'Achird, according to Becvar' yield nothing
    or just the name."""
    out = []
    common = rec.get("Common")
    if isinstance(common, str):
        common = [common]
    for c in common or ():
        if isinstance(c, str) and c.strip():
            out.append(c.strip())
    for note in _note_list(rec.get("Notes")):
        if not isinstance(note, dict) or str(note.get("Category", "")).lower() != "star names":
            continue
        remark = re.sub(r"\([^)]*\)", "", str(note.get("Remark", "")))
        for tok in re.split(r"[;,]|\.\s", remark):
            tok = re.sub(r"\s+(in|according to|per)\s+(becvar|allen)\b.*$", "", tok.strip(" .\""), flags=re.I)
            if not _ALIAS_TOKEN.match(tok):
                continue
            words = tok.lower().split()
            if len(words) > 4 or words[0] in _ALIAS_LEAD or _ALIAS_STOP.intersection(words):
                continue
            out.append(tok.title() if tok.isupper() else tok)
    seen, uniq = set(), []
    for n in out:
        if _squash(n) not in seen:
            seen.add(_squash(n))
            uniq.append(n)
    return tuple(uniq)


_NAME_RE = re.compile(r"^(\d*)\s*([A-Z][a-z]{1,2})?\s*(\d?)\s*([A-Z][A-Za-z]{2})$")


def _designation_keys(name):
    """Lower-case lookup keys for a BSC 'Name' such as '21Alp Sco', 'Mu 1Cru', '80 UMa'."""
    m = _NAME_RE.match(name.strip())
    if not m:
        return ()
    flam, bayer, sup, con = m.groups()
    con = con.lower()
    keys = []
    if bayer:
        keys.append(f"{bayer.lower()}{sup} {con}")
        if sup:
            keys.append(f"{bayer.lower()} {con}")
    if flam:
        keys.append(f"{flam} {con}")
    return tuple(keys)


class Catalog:
    """Parsed BSC5: numpy arrays over all usable records (any magnitude)."""

    def __init__(self, records):
        hr, names, aliases, ra, dec, vmag, temp, bv = [], [], [], [], [], [], [], []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            try:
                r = parse_ra(rec["RA"])
                d = parse_dec(rec["Dec"])
            except (KeyError, ValueError, TypeError):
                continue
            m = _float(rec.get("Vmag"))
            if m is None or not (-2.0 < m < 12.0) or not (-90.0 <= d <= 90.0):
                continue
            hr.append(int(_float(rec.get("HR")) or 0))
            names.append(str(rec.get("Name", "") or "").strip())
            aliases.append(_record_names(rec))
            ra.append(r % 360.0)
            dec.append(d)
            vmag.append(m)
            temp.append(_temperature(rec))
            b = _float(rec.get("B-V"))
            bv.append(np.nan if b is None else b)
        self.hr = np.array(hr, dtype=np.int64)
        self.name = names          # BSC designation field, e.g. '21Alp Sco'
        self.aliases = aliases     # proper names from the record ('Common', 'Star names' notes)
        self.ra = np.array(ra)
        self.dec = np.array(dec)
        self.vmag = np.array(vmag)
        self.temp = np.array(temp)
        self.bv = np.array(bv)
        self.world = equatorial_to_world(self.ra, self.dec)
        self._keys = {}
        for i, n in enumerate(names):
            for k in _designation_keys(n):
                self._keys.setdefault(k, []).append(i)
        self._alias_keys = {}
        for i, al in enumerate(aliases):
            for a in al:
                self._alias_keys.setdefault(_squash(a), []).append(i)

    def __len__(self):
        return len(self.vmag)

    def brightest(self, indices):
        indices = list(indices)
        return min(indices, key=lambda i: self.vmag[i]) if indices else None

    def by_designation(self, designation):
        """Index of the brightest star with this designation ('Alp Sco', 'Alp1Cru', '80 UMa',
        or an already lower-cased key such as 'alp1 cru'); None if absent."""
        keys = _designation_keys(designation) or (designation.strip().lower(),)
        key = keys[0]
        hits = self._keys.get(key)
        if not hits:
            loose = re.sub(r"^([a-z]+)\d ", r"\1 ", key)  # 'gam2 sgr' -> 'gam sgr'
            hits = self._keys.get(loose, ())
        return self.brightest(hits)

    def by_alias(self, name):
        """Index of the brightest star whose own catalogue record names it `name`
        (case, spaces and hyphens ignored); None if absent."""
        return self.brightest(self._alias_keys.get(_squash(name), ()))


@lru_cache(maxsize=4)
def load_catalog(path=CATALOG_PATH):
    """Load (downloading once if needed) and parse the Yale Bright Star Catalogue."""
    if not os.path.exists(path):
        _download(path)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):  # tolerate {"stars": [...]} style wrappers
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return Catalog(data)


def catalog_stars(mag_limit=6.6):
    """Every catalogue star with V <= mag_limit.

    Returns (world_dirs (N,3) unit vectors in the Minecraft world frame,
    vmag (N,), temperature_K (N,)). The whole sphere is returned, including
    stars below the horizon."""
    cat = load_catalog()
    sel = cat.vmag <= mag_limit
    return cat.world[sel].copy(), cat.vmag[sel].copy(), cat.temp[sel].copy()


# ---------------------------------------------------------------------------
# Star names
# ---------------------------------------------------------------------------

# IAU (WGSN) proper names -> BSC Bayer / Flamsteed designations as they appear
# in the catalogue's Name field ('Alp1Cru' = alpha-1 Crucis, '80 UMa' = 80 Ursae Majoris).
PROPER_NAMES = {
    "Sirius": "Alp CMa", "Canopus": "Alp Car", "Rigil Kentaurus": "Alp1Cen", "Toliman": "Alp2Cen",
    "Arcturus": "Alp Boo", "Vega": "Alp Lyr", "Capella": "Alp Aur", "Rigel": "Bet Ori",
    "Procyon": "Alp CMi", "Achernar": "Alp Eri", "Betelgeuse": "Alp Ori", "Hadar": "Bet Cen",
    "Altair": "Alp Aql", "Acrux": "Alp1Cru", "Aldebaran": "Alp Tau", "Antares": "Alp Sco",
    "Spica": "Alp Vir", "Pollux": "Bet Gem", "Fomalhaut": "Alp PsA", "Deneb": "Alp Cyg",
    "Mimosa": "Bet Cru", "Regulus": "Alp Leo", "Adhara": "Eps CMa", "Castor": "Alp Gem",
    "Gacrux": "Gam Cru", "Shaula": "Lam Sco", "Bellatrix": "Gam Ori", "Elnath": "Bet Tau",
    "Miaplacidus": "Bet Car", "Alnilam": "Eps Ori", "Alnair": "Alp Gru", "Alnitak": "Zet Ori",
    "Alioth": "Eps UMa", "Dubhe": "Alp UMa", "Mirfak": "Alp Per", "Wezen": "Del CMa",
    "Sargas": "The Sco", "Kaus Australis": "Eps Sgr", "Avior": "Eps Car", "Alkaid": "Eta UMa",
    "Menkalinan": "Bet Aur", "Atria": "Alp TrA", "Alhena": "Gam Gem", "Peacock": "Alp Pav",
    "Mirzam": "Bet CMa", "Alphard": "Alp Hya", "Polaris": "Alp UMi", "Hamal": "Alp Ari",
    "Algieba": "Gam1Leo", "Diphda": "Bet Cet", "Nunki": "Sig Sgr", "Menkent": "The Cen",
    "Mirach": "Bet And", "Alpheratz": "Alp And", "Rasalhague": "Alp Oph", "Kochab": "Bet UMi",
    "Saiph": "Kap Ori", "Denebola": "Bet Leo", "Algol": "Bet Per", "Suhail": "Lam Vel",
    "Alphecca": "Alp CrB", "Mintaka": "Del Ori", "Sadr": "Gam Cyg", "Eltanin": "Gam Dra",
    "Schedar": "Alp Cas", "Naos": "Zet Pup", "Almach": "Gam1And", "Caph": "Bet Cas",
    "Izar": "Eps Boo", "Dschubba": "Del Sco", "Larawag": "Eps Sco", "Merak": "Bet UMa",
    "Ankaa": "Alp Phe", "Enif": "Eps Peg", "Scheat": "Bet Peg", "Sabik": "Eta Oph",
    "Phecda": "Gam UMa", "Aludra": "Eta CMa", "Markab": "Alp Peg", "Aljanah": "Eps Cyg",
    "Acrab": "Bet1Sco", "Zubeneschamali": "Bet Lib", "Zubenelgenubi": "Alp2Lib",
    "Unukalhai": "Alp Ser", "Rasalgethi": "Alp1Her", "Albireo": "Bet1Cyg", "Megrez": "Del UMa",
    "Mizar": "Zet UMa", "Alcor": "80 UMa", "Ruchbah": "Del Cas", "Segin": "Eps Cas",
    "Navi": "Gam Cas", "Kaus Media": "Del Sgr", "Kaus Borealis": "Lam Sgr", "Ascella": "Zet Sgr",
    "Alnasl": "Gam2Sgr", "Tarazed": "Gam Aql", "Sheliak": "Bet Lyr", "Sulafat": "Gam Lyr",
    "Alderamin": "Alp Cep", "Thuban": "Alp Dra", "Rastaban": "Bet Dra", "Lesath": "Ups Sco",
    "Girtab": "Kap Sco", "Fang": "Pi Sco", "Alniyat": "Sig Sco", "Paikauhale": "Tau Sco",
    "Xamidimura": "Mu1Sco", "Pipirima": "Mu2Sco", "Gienah": "Gam Crv", "Algorab": "Del Crv",
    "Kraz": "Bet Crv", "Porrima": "Gam Vir", "Vindemiatrix": "Eps Vir", "Cor Caroli": "Alp2CVn",
    "Muphrid": "Eta Boo", "Seginus": "Gam Boo", "Nekkar": "Bet Boo", "Kornephoros": "Bet Her",
    "Sarin": "Del Her", "Errai": "Gam Cep", "Menkar": "Alp Cet", "Mira": "Omi Cet",
    "Alcyone": "Eta Tau", "Aspidiske": "Iot Car", "Alsephina": "Del Vel", "Markeb": "Kap Vel",
    "Furud": "Zet CMa", "Nashira": "Gam Cap", "Deneb Algedi": "Del Cap", "Sadalmelik": "Alp Aqr",
    "Sadalsuud": "Bet Aqr", "Mothallah": "Alp Tri", "Sheratan": "Bet Ari", "Zaurak": "Gam Eri",
    "Cursa": "Bet Eri", "Arneb": "Alp Lep", "Phact": "Alp Col", "Hatysa": "Iot Ori",
    "Graffias": "Bet1Sco", "Alrescha": "Alp Psc", "Algenib": "Gam Peg", "Mirphak": "Alp Per",
}

_GREEK = {
    "alpha": "alp", "beta": "bet", "gamma": "gam", "delta": "del", "epsilon": "eps", "zeta": "zet",
    "eta": "eta", "theta": "the", "iota": "iot", "kappa": "kap", "lambda": "lam", "mu": "mu",
    "nu": "nu", "xi": "xi", "omicron": "omi", "pi": "pi", "rho": "rho", "sigma": "sig", "tau": "tau",
    "upsilon": "ups", "phi": "phi", "chi": "chi", "psi": "psi", "omega": "ome",
}


def _designation_query(text):
    """'alpha Sco', 'Alp Sco', 'alpha-1 Cru', 'Alp1Cru', '80 UMa' -> catalogue key or None."""
    t = text.strip().lower().replace("-", " ")
    m = re.match(r"^([a-z]+)\s*(\d?)\s+([a-z]{3})$", t) or re.match(r"^([a-z]{2,3})(\d)([a-z]{3})$", t)
    if m:
        g, sup, con = m.groups()
        g = _GREEK.get(g, g)
        return f"{g}{sup} {con}"
    m = re.match(r"^(\d+)\s*([a-z]{3})$", t)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return None


def find_star(name):
    """Catalogue index of a star, or None. Accepts, in this order of precedence:

    1. a proper name, exactly (case / spaces / hyphens ignored): first the IAU names in
       PROPER_NAMES, then the names in the catalogue's own records ('Common' field and the
       BSC5 'Star names' remarks, e.g. 'Wega', 'Lodestar', 'Baten Kaitos');
    2. 'HR 6134' (Harvard Revised / BSC number);
    3. a Bayer or Flamsteed designation: 'alpha Sco', 'Alp Sco', 'alpha-1 Cru', 'Alp1Cru', '80 UMa';
    4. any case-insensitive substring of a proper name or of the catalogue Name field
       ('kentaurus', '3Alp Lyr').
    Among several matches the brightest star wins."""
    if name is None:
        return None
    q = str(name).strip()
    sq = _squash(q)
    if not sq:
        return None
    cat = load_catalog()
    # 1. exact proper name
    idx = cat.brightest(i for i in (cat.by_designation(d) for p, d in PROPER_NAMES.items() if _squash(p) == sq)
                        if i is not None)
    if idx is None:
        idx = cat.by_alias(q)
    if idx is not None:
        return idx
    # 2. HR number
    m = re.match(r"^hr\s*(\d+)$", q.lower())
    if m:
        hits = np.nonzero(cat.hr == int(m.group(1)))[0]
        return int(hits[0]) if len(hits) else None
    # 3. Bayer / Flamsteed designation
    key = _designation_query(q)
    if key is not None:
        idx = cat.by_designation(key)
        if idx is not None:
            return idx
    # 4. substring of any name field
    low = q.lower()
    hits = [cat.by_designation(d) for p, d in PROPER_NAMES.items() if sq in _squash(p)]
    hits += [i for i, al in enumerate(cat.aliases) if any(sq in _squash(a) for a in al)]
    hits += [i for i, n in enumerate(cat.name) if n and low in n.lower()]
    return cat.brightest(i for i in hits if i is not None)


def named_star(name):
    """World unit vector of a named star (see find_star), or None if unknown."""
    idx = find_star(name)
    return None if idx is None else load_catalog().world[idx].copy()


def star_info(name):
    """Dict with catalogue data and sky position of a named star, or None."""
    idx = find_star(name)
    if idx is None:
        return None
    cat = load_catalog()
    alt, az = horizontal(cat.world[idx])
    return dict(index=idx, hr=int(cat.hr[idx]), designation=cat.name[idx], ra_deg=float(cat.ra[idx]),
                dec_deg=float(cat.dec[idx]), vmag=float(cat.vmag[idx]), temp_K=float(cat.temp[idx]),
                names=cat.aliases[idx], world=cat.world[idx].copy(), alt_deg=float(alt), az_deg=float(az))


# Stick figures (catalogue designations) used by the previews.
ASTERISMS = {
    "Scorpius": [["Bet1Sco", "Del Sco", "Pi Sco", "Rho Sco"],
                 ["Del Sco", "Sig Sco", "Alp Sco", "Tau Sco", "Eps Sco", "Mu1Sco", "Zet2Sco",
                  "Eta Sco", "The Sco", "Iot1Sco", "Kap Sco", "Lam Sco", "Ups Sco"]],
    "Sagittarius": [["Gam2Sgr", "Del Sgr", "Eps Sgr", "Gam2Sgr"], ["Del Sgr", "Lam Sgr", "Phi Sgr", "Del Sgr"],
                    ["Eps Sgr", "Zet Sgr", "Phi Sgr"], ["Zet Sgr", "Tau Sgr", "Sig Sgr", "Phi Sgr"]],
    "Ursa Major": [["Eta UMa", "Zet UMa", "Eps UMa", "Del UMa", "Alp UMa", "Bet UMa", "Gam UMa", "Del UMa"]],
    "Ursa Minor": [["Alp UMi", "Del UMi", "Eps UMi", "Zet UMi", "Bet UMi", "Gam UMi", "Eta UMi", "Zet UMi"]],
    "Cassiopeia": [["Eps Cas", "Del Cas", "Gam Cas", "Alp Cas", "Bet Cas"]],
    "Summer Triangle": [["Alp Lyr", "Alp Cyg", "Alp Aql", "Alp Lyr"]],
    "Lyra": [["Alp Lyr", "Eps1Lyr", "Zet1Lyr", "Alp Lyr"], ["Zet1Lyr", "Del2Lyr", "Gam Lyr", "Bet Lyr", "Zet1Lyr"]],
    "Cygnus": [["Alp Cyg", "Gam Cyg", "Eta Cyg", "Bet1Cyg"], ["Del Cyg", "Gam Cyg", "Eps Cyg"]],
    "Aquila": [["Zet Aql", "Gam Aql", "Alp Aql", "Bet Aql"], ["Alp Aql", "Del Aql", "Lam Aql"]],
    "Bootes": [["Alp Boo", "Eps Boo", "Del Boo", "Bet Boo", "Gam Boo", "Rho Boo", "Alp Boo", "Eta Boo"]],
    "Corona Borealis": [["The CrB", "Bet CrB", "Alp CrB", "Gam CrB", "Del CrB", "Eps CrB"]],
    "Hercules": [["Eps Her", "Zet Her", "Eta Her", "Pi Her", "Eps Her"], ["Zet Her", "Bet Her"],
                 ["Pi Her", "Rho Her"], ["Eps Her", "Del Her", "Alp1Her"]],
    "Orion": [["Alp Ori", "Gam Ori", "Del Ori", "Eps Ori", "Zet Ori", "Alp Ori"],
              ["Del Ori", "Bet Ori"], ["Zet Ori", "Kap Ori"]],
    "Crux": [["Alp1Cru", "Gam Cru"], ["Bet Cru", "Del Cru"]],
}


def asterism_lines():
    """{name: [ (k,3) world polylines ]} for ASTERISMS (missing stars are skipped)."""
    cat = load_catalog()
    out = {}
    for name, strokes in ASTERISMS.items():
        lines = []
        for stroke in strokes:
            idx = [cat.by_designation(d) for d in stroke]
            pts = [cat.world[i] for i in idx if i is not None]
            if len(pts) >= 2:
                lines.append(np.array(pts))
        out[name] = lines
    return out


# ---------------------------------------------------------------------------
# Hooks for the renderer (blackhole.make_galaxy works in the scene frame)
# ---------------------------------------------------------------------------


def make_galaxy_kwargs(w2s, mag_limit=6.6, faint_limit=12.5):
    """Keyword arguments for bh.make_galaxy that put the real sky in a scene frame.

    w2s: bh.world_to_scene(direction) used by the renderer. Returns galactic_north,
    galactic_centre (scene frame), extra_stars = real stars (scene dirs, vmag, temp) and
    mag_range so the procedural population only adds stars fainter than the catalogue:
        bh.make_galaxy(size, seed, n_stars=..., star_flux=..., **make_galaxy_kwargs(w2s))
    """
    w2s = np.asarray(w2s, dtype=np.float64)
    dirs, vmag, temp = catalog_stars(mag_limit)
    return dict(galactic_north=w2s @ GALACTIC_NORTH_WORLD,
                galactic_centre=w2s @ GALACTIC_CENTRE_WORLD,
                extra_stars=(np.ascontiguousarray(dirs @ w2s.T), vmag, temp),
                mag_range=(mag_limit, faint_limit))


# ---------------------------------------------------------------------------
# Previews
# ---------------------------------------------------------------------------

_LABELS = ["Antares", "Shaula", "Kaus Australis", "Nunki", "Vega", "Deneb", "Altair", "Arcturus",
           "Polaris", "Dubhe", "Alkaid", "Spica", "Schedar", "Rasalhague", "Alphecca", "Capella",
           "Fomalhaut", "Enif", "Albireo", "Mizar", "Kochab", "Eltanin", "Zubeneschamali", "Sargas"]


def _star_rgb(temp, gain=1.0, sat=1.6):
    """Display colour for a star dot: blackbody tint with a mild saturation boost."""
    c = bh.blackbody_colour(temp)
    c = np.clip(1.0 + (c - 1.0) * sat, 0.05, None)
    return c / c.max(-1, keepdims=True) * gain


def _splat(img, x, y, sigma, rgb):
    h, w, _ = img.shape
    r = int(math.ceil(3.0 * sigma)) + 1
    x0, x1 = max(int(x) - r, 0), min(int(x) + r + 2, w)
    y0, y1 = max(int(y) - r, 0), min(int(y) + r + 2, h)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    g = np.exp(-((xx + 0.5 - x) ** 2 + (yy + 0.5 - y) ** 2) / (2 * sigma * sigma))
    img[y0:y1, x0:x1] += g[..., None] * rgb


def _render_points(img, xy, vmag, temp, mag_limit, scale):
    order = np.argsort(-vmag)  # faint first, bright on top
    for k in order:
        m = vmag[k]
        sigma = scale * (0.55 + 0.33 * max(mag_limit - m, 0.0))
        peak = min(1.0, 0.28 + 0.16 * (mag_limit - m))
        _splat(img, xy[k, 0], xy[k, 1], sigma, _star_rgb(temp[k], peak * 1.6))


def _polyline(draw, pts, valid, fill, width):
    seg = []
    for p, ok in zip(pts, valid):
        if ok:
            seg.append((float(p[0]), float(p[1])))
        else:
            if len(seg) >= 2:
                draw.line(seg, fill=fill, width=width)
            seg = []
    if len(seg) >= 2:
        draw.line(seg, fill=fill, width=width)


def _densify(poly, step_deg=0.5):
    out = [poly[0]]
    for a, b in zip(poly[:-1], poly[1:]):
        n = max(int(angle_deg(a, b) / step_deg), 1)
        t = np.linspace(0, 1, n + 1)[1:, None]
        out.extend(bh.normalize(a * (1 - t) + b * t))
    return np.array(out)


def render_allsky_preview(path, size=1600, mag_limit=6.6, max_zenith_deg=112.0):
    """Fisheye (azimuthal equidistant) all-sky chart as seen lying on your back with
    your head to the north: zenith in the centre, south at the bottom, east on the
    LEFT (as on every planisphere). The ring marks the horizon; the band outside it
    shows the sky just below the horizon (the pack's sky is a full sphere)."""
    from PIL import Image, ImageDraw, ImageFont

    c = size / 2.0
    rad = (size / 2.0 - 40) / max_zenith_deg  # px per degree of zenith distance

    def project(world):
        v = bh.normalize(world)
        zd = np.degrees(np.arccos(np.clip(v[..., 1], -1, 1)))
        rho = np.hypot(v[..., 0], v[..., 2]) + 1e-12
        x = c - rad * zd * v[..., 0] / rho   # east (+x world) to the left
        y = c + rad * zd * v[..., 2] / rho   # south (+z world) at the bottom
        return np.stack([x, y], -1), zd <= max_zenith_deg

    yy, xx = np.mgrid[0:size, 0:size] + 0.5
    rr = np.hypot(xx - c, yy - c) / rad
    img = np.zeros((size, size, 3))
    img[rr <= max_zenith_deg] = (0.010, 0.014, 0.030)
    img[(rr > 90.0) & (rr <= max_zenith_deg)] = (0.022, 0.016, 0.012)  # below the horizon

    dirs, vmag, temp = catalog_stars(mag_limit)
    xy, ok = project(dirs)
    _render_points(img, xy[ok], vmag[ok], temp[ok], mag_limit, size / 1600.0)

    disp = np.clip(img, 0, 1) ** (1 / 2.2)
    pil = Image.fromarray((disp * 255).astype(np.uint8))
    draw = ImageDraw.Draw(pil, "RGBA")
    try:
        font = ImageFont.load_default(size=max(int(size / 85), 11))
        big = ImageFont.load_default(size=max(int(size / 50), 14))
    except TypeError:
        font = big = ImageFont.load_default()

    for alt in (0, 30, 60):
        r = (90 - alt) * rad
        draw.ellipse([c - r, c - r, c + r, c + r], outline=(90, 110, 140, 150 if alt == 0 else 60),
                     width=3 if alt == 0 else 1)
    # galactic equator (faint) and the asterism stick figures
    gal = galactic_to_world(np.arange(0, 360.25, 0.25), 0.0)
    gxy, gok = project(gal)
    _polyline(draw, gxy, gok, (190, 120, 255, 110), 2)
    for b in (-10, 10):
        bxy, bok = project(galactic_to_world(np.arange(0, 360.25, 0.5), b))
        _polyline(draw, bxy, bok, (190, 120, 255, 40), 1)
    for name, lines in asterism_lines().items():
        for poly in lines:
            pxy, pok = project(_densify(poly))
            _polyline(draw, pxy, pok, (110, 170, 255, 95), 1)

    # Sgr A* = the pack's black hole
    (sx, sy), _ = project(SGR_A_WORLD)
    draw.ellipse([sx - 9, sy - 9, sx + 9, sy + 9], outline=(255, 150, 40, 255), width=3)
    draw.text((sx + 12, sy - 6), "Sgr A* (black hole)", fill=(255, 170, 70, 255), font=font)

    for nm in _LABELS:
        info = star_info(nm)
        if info is None:
            continue
        (px, py), vis = project(info["world"])
        if vis:
            draw.text((px + 7, py + 3), nm, fill=(200, 215, 235, 210), font=font)

    for lab, az in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
        (px, py), _ = project(horizontal_to_world(-1.0, az))
        draw.text((px - 6, py - 9), lab, fill=(255, 230, 150, 255), font=big)
    draw.text((16, 12), f"Real sky, lat {LATITUDE_DEG:.3f} N, LST {LST_DEG / 15:.3f} h", fill=(220, 220, 220, 255),
              font=font)
    n_up = int((dirs[:, 1] > 0).sum())
    draw.text((16, 12 + size / 70), f"{len(vmag)} BSC5 stars V<={mag_limit} ({n_up} above the horizon); "
              "ring = horizon; east is left", fill=(160, 160, 170, 255), font=font)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    pil.save(path)
    return path


def render_view_preview(path, look_dir=None, width=1600, height=900, fov_x_deg=110.0, mag_limit=6.6):
    """Pinhole view through bh.world_to_scene(look_dir) (default: at Sgr A*), exactly the
    camera convention the renderer uses (scene +z forward, +y up, screen-right = scene -x)."""
    from PIL import Image, ImageDraw, ImageFont

    look = SGR_A_WORLD if look_dir is None else bh.normalize(look_dir)
    w2s = bh.world_to_scene(look)
    tx = math.tan(math.radians(fov_x_deg / 2))
    f = width / 2 / tx

    def project(world):
        s = np.asarray(world) @ w2s.T
        z = s[..., 2]
        safe = np.where(z > 1e-6, z, 1.0)
        x = width / 2 - f * s[..., 0] / safe
        y = height / 2 - f * s[..., 1] / safe
        return np.stack([x, y], -1), (z > 0.05) & (x > -50) & (x < width + 50) & (y > -50) & (y < height + 50)

    img = np.zeros((height, width, 3))
    img[:] = (0.010, 0.014, 0.030)
    # ground (below the horizon) tinted
    ys, xs = np.mgrid[0:height, 0:width] + 0.5
    ray = bh.normalize(np.stack([-(xs - width / 2) / f, -(ys - height / 2) / f, np.ones_like(xs)], -1))
    world = ray @ w2s
    img[world[..., 1] < 0] = (0.03, 0.022, 0.015)

    dirs, vmag, temp = catalog_stars(mag_limit)
    xy, ok = project(dirs)
    _render_points(img, xy[ok], vmag[ok], temp[ok], mag_limit, 1.0)
    pil = Image.fromarray((np.clip(img, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8))
    draw = ImageDraw.Draw(pil, "RGBA")
    try:
        font = ImageFont.load_default(size=16)
    except TypeError:
        font = ImageFont.load_default()
    gxy, gok = project(_densify(galactic_to_world(np.arange(0, 360.5, 1.0), 0.0)))
    _polyline(draw, gxy, gok, (190, 120, 255, 110), 2)
    for name, lines in asterism_lines().items():
        for poly in lines:
            pxy, pok = project(_densify(poly))
            _polyline(draw, pxy, pok, (110, 170, 255, 95), 1)
    hxy, hok = project(horizontal_to_world(0.0, np.arange(0, 360.25, 0.25)))
    _polyline(draw, hxy, hok, (200, 160, 110, 160), 2)
    for lab, az in (("N", 0), ("NE", 45), ("E", 90), ("SE", 135), ("S", 180), ("SW", 225), ("W", 270), ("NW", 315)):
        (px, py), vis = project(horizontal_to_world(0.0, az))
        if vis:
            draw.text((px - 8, py + 6), lab, fill=(255, 230, 150, 255), font=font)
    (sx, sy), svis = project(SGR_A_WORLD)
    if svis:
        draw.ellipse([sx - 10, sy - 10, sx + 10, sy + 10], outline=(255, 150, 40, 255), width=3)
        draw.text((sx + 13, sy - 8), "Sgr A*", fill=(255, 170, 70, 255), font=font)
    for nm in _LABELS:
        info = star_info(nm)
        if info is None:
            continue
        (px, py), vis = project(info["world"])
        if vis:
            draw.text((px + 7, py + 3), nm, fill=(200, 215, 235, 210), font=font)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    pil.save(path)
    return path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Render previews of the real sky placement.")
    ap.add_argument("outdir")
    ap.add_argument("--size", type=int, default=1600)
    args = ap.parse_args()
    print(render_allsky_preview(os.path.join(args.outdir, "real_sky_allsky.png"), size=args.size))
    print(render_view_preview(os.path.join(args.outdir, "real_sky_south.png")))
    for nm in ("Polaris", "Vega", "Antares", "Altair", "Deneb", "Arcturus", "Shaula", "Kaus Australis"):
        i = star_info(nm)
        print(f"{nm:15s} {i['designation']:10s} V={i['vmag']:5.2f} T={i['temp_K']:6.0f}K "
              f"alt={i['alt_deg']:6.2f} az={i['az_deg']:6.2f}")
