# Maps a journal "PlanetClass" value to the exact EDAstro type name.
# Built by comparing the actual PlanetClass values seen in journal files
# against EDAstro's type list (which uses different wording in places,
# e.g. "body" vs "world", and non-breaking hyphens in a few names).
PLANET_CLASS_MAP = {
    "Metal rich body": "Metal‑rich body",
    "High metal content body": "High metal content world",
    "Rocky body": "Rocky body",
    "Icy body": "Icy body",
    "Rocky ice body": "Rocky Ice world",
    "Earthlike body": "Earth‑like world",
    "Water world": "Water world",
    "Ammonia world": "Ammonia world",
    "Water giant": "Water giant",
    "Gas giant with water based life": "Gas giant with water‑based life",
    "Gas giant with ammonia based life": "Gas giant with ammonia‑based life",
    "Sudarsky class I gas giant": "Class I gas giant",
    "Sudarsky class II gas giant": "Class II gas giant",
    "Sudarsky class III gas giant": "Class III gas giant",
    "Sudarsky class IV gas giant": "Class IV gas giant",
    "Sudarsky class V gas giant": "Class V gas giant",
    "Helium rich gas giant": "Helium‑rich gas giant",
    "Helium gas giant": "Helium gas giant",
}


def resolve_planet_type_name(planet_class: str) -> str:
    """
    Converts a journal PlanetClass value into the exact EDAstro type name.
    Falls back to the raw value (tagged "unmapped") if not recognized, so
    mismatches are visible instead of silently failing.
    """
    if planet_class in PLANET_CLASS_MAP:
        return PLANET_CLASS_MAP[planet_class]
    return f"{planet_class} (unmapped)"
