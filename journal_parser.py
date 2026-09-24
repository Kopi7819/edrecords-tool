import glob
import json
import os

from star_types import resolve_star_type_name
from planet_types import resolve_planet_type_name

# --- Unit conversion constants ---
METERS_PER_SOLAR_RADIUS = 695_700_000
SECONDS_PER_DAY = 86_400
STANDARD_GRAVITY = 9.80665  # m/s^2 per 1 G


def identity(x):
    return x


# Maps EDAstro attribute slug -> (journal field name, conversion function to EDAstro units)
STAR_FIELD_MAP = {
    "absoluteMagnitude": ("AbsoluteMagnitude", identity),
    "age": ("Age_MY", identity),
    "solarMasses": ("StellarMass", identity),
    "solarRadius": ("Radius", lambda m: m / METERS_PER_SOLAR_RADIUS),
    "orbitalEccentricity": ("Eccentricity", identity),
    "orbitalPeriod": ("OrbitalPeriod", lambda s: s / SECONDS_PER_DAY),
    "rotationalPeriod": ("RotationPeriod", lambda s: abs(s) / SECONDS_PER_DAY),
    "surfaceTemperature": ("SurfaceTemperature", identity),
}

PLANET_FIELD_MAP = {
    "earthMasses": ("MassEM", identity),
    "gravity": ("SurfaceGravity", lambda g: g / STANDARD_GRAVITY),
    "radius": ("Radius", lambda m: m / 1000),
    "surfacePressure": ("SurfacePressure", identity),
    "orbitalEccentricity": ("Eccentricity", identity),
    "orbitalPeriod": ("OrbitalPeriod", lambda s: s / SECONDS_PER_DAY),
    "rotationalPeriod": ("RotationPeriod", lambda s: abs(s) / SECONDS_PER_DAY),
    "surfaceTemperature": ("SurfaceTemperature", identity),
}

# Not yet handled (need extra work): "periapsis" (distance vs angle mismatch),
# "sol_dist" and "sagittariusA_dist" (need galactic coordinates + distance calc).


class JournalAccessError(Exception):
    """Raised when the journal folder can't be reached (network share down, wrong path, etc.)."""


def ensure_journal_dir_accessible(journal_dir: str) -> None:
    """Raises JournalAccessError with a clear message if the folder isn't reachable."""
    if not os.path.isdir(journal_dir):
        raise JournalAccessError(f"Cannot access journal folder: {journal_dir}")


def find_journal_files(journal_dir: str) -> list[str]:
    """Returns all Journal.*.log files in the given directory, sorted oldest to newest."""
    files = glob.glob(os.path.join(journal_dir, "Journal.*.log"))
    files.sort(key=os.path.getmtime)
    return files


def get_latest_journal_file(journal_dir: str) -> str | None:
    files = find_journal_files(journal_dir)
    return files[-1] if files else None


def read_events(path: str, event_names: set) -> list[dict]:
    """Reads a single journal file and returns all parsed events matching any of event_names."""
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("event") in event_names:
                    events.append(data)
    except OSError as exc:
        print(f"Warning: could not read journal file {path}: {exc}")
    return events


def normalize_organic_scan(entry: dict) -> dict | None:
    """
    Converts a raw ScanOrganic journal event (exobiology sampling) into a
    normalized record. ScanType is "Log" (first detection), "Sample" (one
    of the 3 required samples), or "Analyse" (final completed scan -- this
    is the point where the species is definitively identified).
    """
    if entry.get("event") != "ScanOrganic":
        return None
    return {
        "scan_type": entry.get("ScanType"),
        "genus": entry.get("Genus_Localised") or entry.get("Genus") or "",
        "species": entry.get("Species_Localised") or entry.get("Species") or "",
        "variant": entry.get("Variant_Localised") or entry.get("Variant") or "",
        "body_id": entry.get("Body"),
        "timestamp": entry.get("timestamp"),
    }


def read_scan_events(path: str) -> list[dict]:
    """Reads a single journal file and returns all parsed Scan events."""
    return read_events(path, {"Scan"})


def read_discovery_scan_events(path: str) -> list[dict]:
    """Reads a single journal file and returns all parsed FSSDiscoveryScan events (the 'honk')."""
    return read_events(path, {"FSSDiscoveryScan"})


def normalize_scan(entry: dict) -> dict | None:
    """
    Converts a raw Scan journal event into a normalized record:
    {
        "body_name": str,
        "star_system": str,
        "kind": "star" | "planet",
        "type": str,          # EDAstro-style type name (see star_types.py / planet_types.py)
        "landable": bool | None,
        "timestamp": str,
        "values": {attribute_slug: converted_value, ...},
    }
    Returns None if the entry is not a recognizable star or planet scan.
    """
    if "StarType" in entry:
        kind = "star"
        type_label = resolve_star_type_name(entry["StarType"], entry.get("Luminosity"))
        field_map = STAR_FIELD_MAP
        landable = None
    elif "PlanetClass" in entry:
        kind = "planet"
        type_label = resolve_planet_type_name(entry["PlanetClass"])
        field_map = PLANET_FIELD_MAP
        landable = entry.get("Landable")
        terraform_state = entry.get("TerraformState") or ""
    else:
        return None

    if kind == "star":
        terraform_state = ""

    values = {}
    for slug, (journal_field, convert) in field_map.items():
        if journal_field in entry:
            raw_value = entry[journal_field]
            try:
                values[slug] = convert(raw_value)
            except (TypeError, ZeroDivisionError):
                pass

    return {
        "body_name": entry.get("BodyName"),
        "body_id": entry.get("BodyID"),
        "star_system": entry.get("StarSystem"),
        "kind": kind,
        "type": type_label,
        "landable": landable,
        "terraform_state": terraform_state,
        "timestamp": entry.get("timestamp"),
        "values": values,
    }


TERRAFORM_CANDIDATE_STATES = {"Terraformable", "Candidate for terraforming"}


def classify_scan_for_counts(normalized: dict) -> dict:
    """
    Returns which system-level counters a single normalized scan contributes
    to, e.g. {"numPlanets": 1, "numELW": 1}. Used both for live display and
    for the full-history replay in own_records.py.
    """
    if normalized["kind"] == "star":
        return {"numStars": 1}

    result = {"numPlanets": 1}
    if normalized["type"] == "Earth\u2011like world":
        result["numELW"] = 1
    elif normalized["type"] == "Water world":
        result["numWW"] = 1
    elif normalized["type"] == "Ammonia world":
        result["numAW"] = 1
    if normalized.get("terraform_state") in TERRAFORM_CANDIDATE_STATES:
        result["numTerra"] = 1
    return result


if __name__ == "__main__":
    from config import JOURNAL_DIR

    ensure_journal_dir_accessible(JOURNAL_DIR)

    latest = get_latest_journal_file(JOURNAL_DIR)
    print("Latest journal file:", latest)

    scans = read_scan_events(latest)
    print(f"Found {len(scans)} Scan events in this file.\n")

    for raw in scans[:5]:
        normalized = normalize_scan(raw)
        print(normalized)
        print()
