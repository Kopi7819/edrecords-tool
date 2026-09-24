# Maps a journal Luminosity string (e.g. "Vab", "Ia", "III") to a coarse
# bucket used to pick the right EDAstro descriptor ("super giant", "giant",
# or the plain/dwarf form). Based on the Yerkes luminosity classes:
#   0, Ia+, Ia, Iab, Ib  -> supergiant/hypergiant
#   II, III, IV          -> bright giant / giant / subgiant
#   V, VI, VII (+ "ab" variants like "Vab" that Elite uses for main sequence)
#                         -> dwarf / main sequence / subdwarf


def classify_luminosity(luminosity: str | None) -> str:
    if not luminosity:
        return "dwarf"
    l = luminosity.upper()
    if l.startswith("0") or l.startswith("IA") or l.startswith("IB") or l == "I":
        return "supergiant"
    if l.startswith("II") or l.startswith("III") or l.startswith("IV"):
        return "giant"
    return "dwarf"


# Spectral letter -> descriptor per luminosity bucket, using EDAstro's exact
# wording (including the non-breaking hyphen character it uses in
# "Blue-White", "White-Yellow", etc.).
STAR_TYPE_DESCRIPTORS = {
    "O": {
        "dwarf": "O (Blue‑White) Star",
        # No separate giant/supergiant category observed on EDAstro for O stars yet;
        # fall back to the same label as a best-effort approximation.
    },
    "B": {
        "supergiant": "B (Blue‑White super giant) Star",
        "giant": "B (Blue‑White super giant) Star",
        "dwarf": "B (Blue‑White) Star",
    },
    "A": {
        "supergiant": "A (Blue‑White super giant) Star",
        "giant": "A (Blue‑White super giant) Star",
        "dwarf": "A (Blue‑White) Star",
    },
    "F": {
        "supergiant": "F (White super giant) Star",
        "giant": "F (White super giant) Star",
        "dwarf": "F (White) Star",
    },
    "G": {
        "supergiant": "G (White‑Yellow super giant) Star",
        "giant": "G (White‑Yellow super giant) Star",
        "dwarf": "G (White‑Yellow) Star",
    },
    "K": {
        "supergiant": "K (Yellow‑Orange giant) Star",
        "giant": "K (Yellow‑Orange giant) Star",
        "dwarf": "K (Yellow‑Orange) Star",
    },
    "M": {
        "supergiant": "M (Red super giant) Star",
        "giant": "M (Red giant) Star",
        "dwarf": "M (Red dwarf) Star",
    },
}

# Star types that don't vary by luminosity class -- direct code -> EDAstro name.
DIRECT_STAR_TYPE_MAP = {
    "N": "Neutron Star",
    "H": "Black Hole",
    "SupermassiveBlackHole": "Black Hole",  # approximation: no separate SMBH category seen yet
    "D": "White Dwarf (D) Star",
    "DA": "White Dwarf (DA) Star",
    "DAB": "White Dwarf (DAB) Star",
    "DAV": "White Dwarf (DAV) Star",
    "DAZ": "White Dwarf (DAZ) Star",
    "DB": "White Dwarf (DB) Star",
    "DBV": "White Dwarf (DBV) Star",
    "DBZ": "White Dwarf (DBZ) Star",
    "DC": "White Dwarf (DC) Star",
    "DCV": "White Dwarf (DCV) Star",
    "DQ": "White Dwarf (DQ) Star",
    "C": "C Star",
    "CN": "CN Star",
    "CJ": "CJ Star",
    "MS": "MS‑type Star",
    "S": "S‑type Star",
    "W": "Wolf‑Rayet Star",
    "WN": "Wolf‑Rayet N Star",
    "WNC": "Wolf‑Rayet NC Star",
    "WC": "Wolf‑Rayet C Star",
    "WO": "Wolf‑Rayet O Star",
    "L": "L (Brown dwarf) Star",
    "T": "T (Brown dwarf) Star",
    "Y": "Y (Brown dwarf) Star",
    "TTS": "T Tauri Star",
    "AeBe": "Herbig Ae/Be Star",
}


def resolve_star_type_name(star_type: str, luminosity: str | None) -> str:
    """
    Converts a journal StarType + Luminosity pair into the EDAstro-style
    body type name (e.g. "F" + "Vab" -> "F (White) Star").
    Falls back to a raw "<code> Star (unmapped)" label if the star type
    code isn't recognized.
    """
    if star_type in DIRECT_STAR_TYPE_MAP:
        return DIRECT_STAR_TYPE_MAP[star_type]

    if star_type in STAR_TYPE_DESCRIPTORS:
        bucket = classify_luminosity(luminosity)
        descriptors = STAR_TYPE_DESCRIPTORS[star_type]
        return descriptors.get(bucket, descriptors.get("dwarf"))

    return f"{star_type} Star (unmapped)"
