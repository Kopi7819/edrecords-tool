from data_loader import get_records_for_attribute
from record_status import parse_number, is_reliable_value
from attributes import STAR_TAB_ATTRIBUTES, PLANET_TAB_ATTRIBUTES
from star_types import STAR_TYPE_DESCRIPTORS, DIRECT_STAR_TYPE_MAP
from planet_types import PLANET_CLASS_MAP

# The full set of EDAstro-style type name strings our own resolvers can ever
# produce, used to classify a raw EDAstro row as "star" or "planet" without
# needing to know its specific subtype.
STAR_TYPE_NAMES = set(DIRECT_STAR_TYPE_MAP.values())
for _descriptors in STAR_TYPE_DESCRIPTORS.values():
    STAR_TYPE_NAMES.update(_descriptors.values())

PLANET_TYPE_NAMES = set(PLANET_CLASS_MAP.values())


def is_variant(type_name: str) -> bool:
    """True for EDAstro "variant" rows like "X (as moon)" or "X Systems"."""
    return "(as " in type_name or type_name.endswith("Systems")


def classify_edastro_type(type_name: str) -> str | None:
    """Returns 'star', 'planet', or None if the type isn't recognized."""
    if type_name in STAR_TYPE_NAMES:
        return "star"
    if type_name in PLANET_TYPE_NAMES:
        return "planet"
    return None


def get_type_independent_global_best(kind: str, param_slug: str) -> dict:
    """
    Returns the single best EDAstro max/min for a parameter across ALL types
    of the given kind (star or planet) -- e.g. "the largest star radius ever
    recorded, regardless of star subtype". Includes which subtype held it.
    """
    result = {
        "max": None, "max_type": None, "max_holder": None,
        "min": None, "min_type": None, "min_holder": None,
    }
    try:
        records = get_records_for_attribute(param_slug)
    except Exception:
        return result

    best_max = None
    best_min = None
    for r in records:
        if is_variant(r["type"]) or classify_edastro_type(r["type"]) != kind:
            continue
        high = parse_number(r["highest_value"])
        low = parse_number(r["lowest_value"])
        if (
            high is not None
            and high != 0
            and is_reliable_value(param_slug, high)
            and (best_max is None or high > best_max[0])
        ):
            best_max = (high, r["highest_value"], r["type"], r["highest_body"])
        if (
            low is not None
            and low != 0
            and is_reliable_value(param_slug, low)
            and (best_min is None or low < best_min[0])
        ):
            best_min = (low, r["lowest_value"], r["type"], r["lowest_body"])

    if best_max:
        _, result["max"], result["max_type"], result["max_holder"] = best_max
    if best_min:
        _, result["min"], result["min_type"], result["min_holder"] = best_min
    return result


def get_type_independent_own_best(records: dict, kind: str, param_slug: str) -> dict:
    """Same idea as get_type_independent_global_best, but for own_records."""
    result = {
        "max": None, "max_type": None, "max_holder": None,
        "min": None, "min_type": None, "min_holder": None,
    }
    prefix = f"{kind}|"
    suffix = f"|{param_slug}"

    best_max = None
    best_min = None
    for key, entry in records.items():
        if not key.startswith(prefix) or not key.endswith(suffix):
            continue
        type_name = key[len(prefix):-len(suffix)]

        max_entry = entry.get("max")
        if max_entry and max_entry["value"] != 0 and is_reliable_value(param_slug, max_entry["value"]) and (
            best_max is None or max_entry["value"] > best_max[0]
        ):
            best_max = (max_entry["value"], type_name, max_entry["body_name"], max_entry["star_system"])

        min_entry = entry.get("min")
        if min_entry and min_entry["value"] != 0 and is_reliable_value(param_slug, min_entry["value"]) and (
            best_min is None or min_entry["value"] < best_min[0]
        ):
            best_min = (min_entry["value"], type_name, min_entry["body_name"], min_entry["star_system"])

    if best_max:
        value, type_name, body_name, star_system = best_max
        result["max"], result["max_type"], result["max_holder"] = value, type_name, f"{body_name} ({star_system})"
    if best_min:
        value, type_name, body_name, star_system = best_min
        result["min"], result["min_type"], result["min_holder"] = value, type_name, f"{body_name} ({star_system})"
    return result


def build_type_independent_rows(own_records_full: dict) -> list[dict]:
    """
    Builds one row per parameter, per kind (star/planet) -- the best value
    across all types of that kind, both globally and personally.
    """
    rows = []
    for kind, attr_dict in (("star", STAR_TAB_ATTRIBUTES), ("planet", PLANET_TAB_ATTRIBUTES)):
        for display_name, param_slug in attr_dict.items():
            global_best = get_type_independent_global_best(kind, param_slug)
            own_best = get_type_independent_own_best(own_records_full["records"], kind, param_slug)
            rows.append(
                {
                    "kind": kind,
                    "parameter": display_name,
                    "param_slug": param_slug,
                    "global_max": global_best["max"],
                    "global_max_type": global_best["max_type"],
                    "global_max_holder": global_best["max_holder"],
                    "global_min": global_best["min"],
                    "global_min_type": global_best["min_type"],
                    "global_min_holder": global_best["min_holder"],
                    "own_max": own_best["max"],
                    "own_max_type": own_best["max_type"],
                    "own_max_holder": own_best["max_holder"],
                    "own_min": own_best["min"],
                    "own_min_type": own_best["min_type"],
                    "own_min_holder": own_best["min_holder"],
                }
            )
    return rows


def build_system_records_rows(own_records_full: dict) -> list[dict]:
    """
    Builds one row per system-level metric (Body Count, Stars, Planets,
    ELW, WW, AW, Terraform candidates) -- own records only, since EDAstro's
    equivalent records are grouped by primary star type, which isn't wired
    up here yet.
    """
    labels = {
        "bodyCount": "Body Count",
        "numStars": "Stars",
        "numPlanets": "Planets",
        "numELW": "Earth-like Worlds",
        "numWW": "Water Worlds",
        "numAW": "Ammonia Worlds",
        "numTerra": "Terraform Candidates",
    }
    rows = []
    system_records = own_records_full.get("system_records", {})
    for metric_key, label in labels.items():
        entry = system_records.get(metric_key, {})
        max_entry = entry.get("max")
        min_entry = entry.get("min")
        rows.append(
            {
                "parameter": label,
                "own_max": max_entry["value"] if max_entry else None,
                "own_max_holder": max_entry["star_system"] if max_entry else None,
                "own_min": min_entry["value"] if min_entry else None,
                "own_min_holder": min_entry["star_system"] if min_entry else None,
            }
        )
    return rows
