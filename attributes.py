# Attribute display name -> EDAstro URL slug, grouped by which body types they apply to.

STAR_ATTRIBUTES = {
    "Absolute Magnitude": "absoluteMagnitude",
    "Age": "age",
    "Solar Masses": "solarMasses",
    "Solar Radius": "solarRadius",
}

PLANET_ATTRIBUTES = {
    "Earth Masses": "earthMasses",
    "Gravity": "gravity",
    "Radius": "radius",
    "Surface Pressure": "surfacePressure",
}

# Attributes that apply to both stars and planets.
# NOTE: "periapsis", "sol_dist", and "sagittariusA_dist" are listed here so
# their display names resolve correctly if/when they're wired up, but
# journal_parser.py does not currently populate them (see the comment there
# for why) -- so they will never actually appear in a live comparison row yet.
SHARED_ATTRIBUTES = {
    "Orbital Eccentricity": "orbitalEccentricity",
    "Orbital Period": "orbitalPeriod",
    "Periapsis / Closest Approach": "periapsis",
    "Rotational Period": "rotationalPeriod",
    "Sol Distance": "sol_dist",
    "Sagittarius A* Distance": "sagittariusA_dist",
    "Surface Temperature": "surfaceTemperature",
}

# Full parameter lists offered when looking up global records for a star/planet.
STAR_TAB_ATTRIBUTES = {**STAR_ATTRIBUTES, **SHARED_ATTRIBUTES}
PLANET_TAB_ATTRIBUTES = {**PLANET_ATTRIBUTES, **SHARED_ATTRIBUTES}
