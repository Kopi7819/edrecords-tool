STATUS_NEW_PERSONAL_BEST = "new_personal_best"
STATUS_BEATS_GLOBAL = "beats_global"
STATUS_NORMAL = "normal"


# Currently no parameter needs special-casing here -- kept as an extension
# point in case a future attribute needs its max or min side excluded from
# record tracking (format: slug -> (track_max, track_min)).
RECORD_ELIGIBILITY = {}

# Known Elite Dangerous / EDAstro data reliability issue: a "Stellar Forge"
# bug occasionally generates absurdly exaggerated Surface Pressure values.
# It turns out to affect many different body types unpredictably (not just
# the couple originally documented), so a per-type blocklist can't keep up --
# a physical sanity cap is more robust. 50,000,000 Pa (~493 atm) is generous:
# legitimate EDAstro pressures for landable worlds sit far below this.
SURFACE_PRESSURE_SANITY_LIMIT_PA = 50_000_000


def is_reliable_value(param_slug: str, value) -> bool:
    """
    Returns False for values known to reflect a data-reliability issue
    rather than a genuine reading (currently just the Surface Pressure
    Stellar Forge bug). Used to keep such values out of own_records.json in
    the first place, and to skip them when reading EDAstro's global data.
    """
    if param_slug != "surfacePressure":
        return True
    numeric = parse_number(value) if not isinstance(value, (int, float)) else value
    if numeric is None:
        return True
    return numeric <= SURFACE_PRESSURE_SANITY_LIMIT_PA


def get_record_eligibility(param_slug: str, type_name: str = None) -> tuple[bool, bool]:
    """Returns (track_max, track_min) for a given parameter."""
    return RECORD_ELIGIBILITY.get(param_slug, (True, True))


def parse_number(value) -> float | None:
    """
    Converts an EDAstro-style number string (e.g. "21,475.806", "0") into a
    float. Returns None for missing/empty/unparseable values.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return None
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def determine_status(
    current_value: float, global_max, global_min, own_max, own_min, param_slug: str = None, type_name: str = None
) -> tuple[str, str | None]:
    """
    Determines the record status for a single (body, parameter) row, and
    which specific field (own_max/own_min/global_max/global_min) triggered
    it -- returned as (status, matched_field). matched_field is None when
    status is "normal".

    - "new_personal_best": current_value matches or exceeds the player's own
      previous max, or matches/goes below their own previous min. Ties DO
      count here -- once own_records.json has absorbed this scan, the value
      naturally equals the stored best, and we want that status to persist
      for as long as you're in the system, not just flash for one refresh.
    - "beats_global": current_value strictly beats the EDAstro global max or
      global min outright. Ties do NOT count here, since a tie is usually
      just many different bodies sharing a common galaxy-wide floor value
      (e.g. 0 eccentricity), not a meaningful match with the real record.
    - "normal": none of the above.

    A current_value of exactly 0 never counts as a record for any parameter
    -- there's no parameter where hitting 0 is itself an interesting extreme,
    and it's a common floor/default shared by huge numbers of bodies (e.g.
    most orbits aren't measurably eccentric, most airless worlds show 0
    pressure), so treating it as a "new best" or "matches the record" would
    just be noise.

    Any missing comparison values are simply skipped (treated as "no data").
    """
    track_max, track_min = get_record_eligibility(param_slug, type_name)

    if current_value == 0 or not is_reliable_value(param_slug, current_value):
        return STATUS_NORMAL, None

    g_max = parse_number(global_max)
    g_min = parse_number(global_min)
    o_max = parse_number(own_max)
    o_min = parse_number(own_min)

    # Personal best: ties count (see docstring above).
    if track_max and o_max is not None and current_value >= o_max:
        return STATUS_NEW_PERSONAL_BEST, "own_max"
    if track_min and o_min is not None and current_value <= o_min:
        return STATUS_NEW_PERSONAL_BEST, "own_min"

    # Global record: only an outright strict beat counts -- ties don't.
    if track_max and g_max is not None and current_value > g_max:
        return STATUS_BEATS_GLOBAL, "global_max"
    if track_min and g_min is not None and current_value < g_min:
        return STATUS_BEATS_GLOBAL, "global_min"

    return STATUS_NORMAL, None


def annotate_rows(rows: list[dict]) -> list[dict]:
    """
    Adds "status" and "matched_field" keys to each comparison row (as
    produced by current_system.build_current_system_rows), using parsed
    numeric values.
    """
    for row in rows:
        current = parse_number(row["current_value"])
        if current is None:
            row["status"] = STATUS_NORMAL
            row["matched_field"] = None
            continue
        row["status"], row["matched_field"] = determine_status(
            current,
            row["global_max"],
            row["global_min"],
            row["own_max"],
            row["own_min"],
            row.get("param_slug"),
            row.get("type"),
        )
    return rows


if __name__ == "__main__":
    from config import JOURNAL_DIR
    from current_system import build_current_system_rows
    from own_records import build_or_update_own_records
    from journal_parser import JournalAccessError

    try:
        data = build_or_update_own_records(JOURNAL_DIR)
    except JournalAccessError as exc:
        print(f"ERROR: {exc}")
    else:
        system_name = data["current_system_name"]
        scans = list(data["system_bodies"].get(system_name, {}).values())
        rows = build_current_system_rows(scans, data["records"])
        rows = annotate_rows(rows)

        for row in rows:
            print(row["body_name"], "|", row["parameter"], "|", row["status"])
