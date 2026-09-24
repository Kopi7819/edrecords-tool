from data_loader import get_records_for_attribute
from attributes import STAR_TAB_ATTRIBUTES, PLANET_TAB_ATTRIBUTES
from own_records import build_or_update_own_records
from record_status import is_reliable_value

# slug -> display name, across both star and planet attribute sets
ATTRIBUTE_DISPLAY_NAMES = {
    slug: name for name, slug in {**STAR_TAB_ATTRIBUTES, **PLANET_TAB_ATTRIBUTES}.items()
}


def get_own_best(own_records: dict, kind: str, type_name: str, param_slug: str):
    """
    Returns (own_max, own_max_holder, own_min, own_min_holder) for a given
    kind+type+parameter. A "holder" is a "body_name (star_system)" string,
    or None if there's no record / no data.
    """
    key = f"{kind}|{type_name}|{param_slug}"
    entry = own_records.get(key)
    if not entry:
        return None, None, None, None

    max_entry = entry.get("max")
    min_entry = entry.get("min")

    own_max = max_entry.get("value") if max_entry else None
    own_max_holder = (
        f"{max_entry['body_name']} ({max_entry['star_system']})" if max_entry else None
    )
    own_min = min_entry.get("value") if min_entry else None
    own_min_holder = (
        f"{min_entry['body_name']} ({min_entry['star_system']})" if min_entry else None
    )

    return own_max, own_max_holder, own_min, own_min_holder


def get_global_best(kind: str, type_name: str, param_slug: str):
    """
    Returns (global_max, global_max_holder, global_min, global_min_holder)
    for a given kind+type+parameter. A "holder" is the body name EDAstro
    reports for that record, or None if there's no data.
    """
    try:
        records = get_records_for_attribute(param_slug)
    except Exception:
        return None, None, None, None
    for r in records:
        if r["type"] == type_name:
            highest = r["highest_value"] if is_reliable_value(param_slug, r["highest_value"]) else None
            highest_body = r["highest_body"] if highest is not None else None
            lowest = r["lowest_value"] if is_reliable_value(param_slug, r["lowest_value"]) else None
            lowest_body = r["lowest_body"] if lowest is not None else None
            return highest, highest_body, lowest, lowest_body
    return None, None, None, None


def build_current_system_rows(scans: list[dict], own_records: dict) -> list[dict]:
    """
    Builds one comparison row per (body, parameter) combination found in the
    given normalized scans, joining in global and personal best records.
    """
    rows = []
    for scan in scans:
        for param_slug, value in scan["values"].items():
            display_name = ATTRIBUTE_DISPLAY_NAMES.get(param_slug, param_slug)
            global_max, global_max_holder, global_min, global_min_holder = get_global_best(
                scan["kind"], scan["type"], param_slug
            )
            own_max, own_max_holder, own_min, own_min_holder = get_own_best(
                own_records, scan["kind"], scan["type"], param_slug
            )
            rows.append(
                {
                    "body_name": scan["body_name"],
                    "type": scan["type"],
                    "parameter": display_name,
                    "param_slug": param_slug,
                    "current_value": value,
                    "global_max": global_max,
                    "global_max_holder": global_max_holder,
                    "global_min": global_min,
                    "global_min_holder": global_min_holder,
                    "own_max": own_max,
                    "own_max_holder": own_max_holder,
                    "own_min": own_min,
                    "own_min_holder": own_min_holder,
                }
            )
    return rows


def build_records_rows(own_records_full: dict) -> list[dict]:
    """
    Builds one row per (kind, type, param_slug) combination ever tracked in
    own_records -- independent of the current system -- joining in the
    EDAstro global best for each.
    """
    records = own_records_full["records"]
    rows = []
    for key in records.keys():
        kind, type_name, param_slug = key.split("|", 2)
        display_name = ATTRIBUTE_DISPLAY_NAMES.get(param_slug, param_slug)
        global_max, global_max_holder, global_min, global_min_holder = get_global_best(
            kind, type_name, param_slug
        )
        own_max, own_max_holder, own_min, own_min_holder = get_own_best(records, kind, type_name, param_slug)
        rows.append(
            {
                "kind": kind,
                "type": type_name,
                "parameter": display_name,
                "param_slug": param_slug,
                "global_max": global_max,
                "global_max_holder": global_max_holder,
                "global_min": global_min,
                "global_min_holder": global_min_holder,
                "own_max": own_max,
                "own_max_holder": own_max_holder,
                "own_min": own_min,
                "own_min_holder": own_min_holder,
            }
        )
    return rows


if __name__ == "__main__":
    from config import JOURNAL_DIR
    from journal_parser import JournalAccessError

    try:
        data = build_or_update_own_records(JOURNAL_DIR)
    except JournalAccessError as exc:
        print(f"ERROR: {exc}")
        print("Check that the journal folder path in config.py is correct and reachable.")
    else:
        system_name = data["current_system_name"]
        print("Current/last system:", system_name)

        scans = list(data["system_bodies"].get(system_name, {}).values())
        print(f"Found {len(scans)} scanned bodies in this system.\n")

        rows = build_current_system_rows(scans, data["records"])

        print(f"Built {len(rows)} comparison rows.\n")
        for row in rows[:10]:
            print(row)
