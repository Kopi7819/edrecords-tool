import json
import os

from journal_parser import (
    find_journal_files,
    normalize_scan,
    normalize_organic_scan,
    ensure_journal_dir_accessible,
    JournalAccessError,
    classify_scan_for_counts,
)
from record_status import is_reliable_value

OWN_RECORDS_PATH = "own_records.json"
BODY_COUNT_METRIC = "bodyCount"
SYSTEM_EVENTS = {"Location", "FSDJump", "CarrierJump"}


def load_own_records() -> dict:
    """Loads the own-records database, or returns a fresh empty structure if none exists yet."""
    if not os.path.exists(OWN_RECORDS_PATH):
        return {
            "processed_files": [],
            "last_file": None,
            "last_line": 0,
            "records": {},
            "system_records": {},
            "system_tallies": {},
            "system_tallied_bodies": [],
            "current_system_name": None,
            # "system_bodies" accumulates forever, per system, so revisiting a
            # system later still shows bodies scanned on an earlier visit.
            "system_bodies": {},
            "system_body_counts": {},
            # Exobiology: "genus|species|variant" -> {count, first_seen, system_name, body_id}
            "bio_species": {},
        }
    with open(OWN_RECORDS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Backward compatible with older files that predate these keys.
    data.setdefault("system_records", {})
    data.setdefault("system_tallies", {})
    data.setdefault("system_tallied_bodies", [])
    data.setdefault("current_system_name", None)
    data.setdefault("system_bodies", {})
    data.setdefault("system_body_counts", {})
    data.setdefault("bio_species", {})
    return data


def save_own_records(data: dict) -> None:
    """
    Writes own_records.json atomically: the new content is written to a
    temporary file first, then swapped into place with a single atomic
    rename. Without this, a read happening at the exact moment of a write
    (e.g. the GUI's background refresh thread saving while the Statistics
    tab reloads on the main thread) could see a truncated/partial file and
    fail with a JSONDecodeError.
    """
    temp_path = OWN_RECORDS_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, OWN_RECORDS_PATH)


def _record_key(normalized: dict, param_slug: str) -> str:
    return f"{normalized['kind']}|{normalized['type']}|{param_slug}"


def apply_scan_to_records(records: dict, normalized: dict) -> int:
    """
    Updates the records dict in place with the values from one normalized
    scan. Returns the number of new personal records set (0 if none).
    """
    updates = 0
    for param_slug, value in normalized["values"].items():
        if value == 0 or not is_reliable_value(param_slug, value):
            continue
        key = _record_key(normalized, param_slug)
        entry = records.setdefault(key, {})

        candidate = {
            "value": value,
            "body_name": normalized["body_name"],
            "star_system": normalized["star_system"],
            "timestamp": normalized["timestamp"],
        }

        current_max = entry.get("max")
        if current_max is None or value > current_max["value"]:
            entry["max"] = candidate
            updates += 1

        current_min = entry.get("min")
        if current_min is None or value < current_min["value"]:
            entry["min"] = candidate
            updates += 1

    return updates


def update_system_metric(system_records: dict, metric_key: str, value, system_name: str, timestamp: str) -> bool:
    """
    Updates a single system-level metric (e.g. "bodyCount", "numELW") with a
    candidate value for a given system. Returns True if a new max or min
    personal record was set.
    """
    entry = system_records.setdefault(metric_key, {})
    candidate = {"value": value, "star_system": system_name, "timestamp": timestamp}

    updated = False
    current_max = entry.get("max")
    if current_max is None or value > current_max["value"]:
        entry["max"] = candidate
        updated = True

    current_min = entry.get("min")
    if current_min is None or value < current_min["value"]:
        entry["min"] = candidate
        updated = True

    return updated


def _process_line(entry: dict, data: dict, tallied_bodies: set) -> int:
    """Processes one parsed journal line, updating all tracked state in place. Returns update count."""
    event = entry.get("event")
    updates = 0

    if event in SYSTEM_EVENTS and "StarSystem" in entry:
        # Just move the "current system" pointer -- system_bodies/system_body_counts
        # are keyed by system name and never cleared, so nothing is lost on revisit.
        data["current_system_name"] = entry["StarSystem"]

    elif event == "Scan":
        normalized = normalize_scan(entry)
        if normalized is not None:
            updates += apply_scan_to_records(data["records"], normalized)

            system_name = normalized["star_system"]
            data["system_bodies"].setdefault(system_name, {})[normalized["body_name"]] = normalized

            body_key = f"{system_name}|{normalized['body_name']}"
            if body_key not in tallied_bodies:
                tallied_bodies.add(body_key)
                tally = data["system_tallies"].setdefault(
                    system_name,
                    {"numStars": 0, "numPlanets": 0, "numELW": 0, "numWW": 0, "numAW": 0, "numTerra": 0},
                )
                for metric_key, amount in classify_scan_for_counts(normalized).items():
                    tally[metric_key] = tally.get(metric_key, 0) + amount
                    if update_system_metric(
                        data["system_records"], metric_key, tally[metric_key], system_name, normalized["timestamp"]
                    ):
                        updates += 1

    elif event == "FSSDiscoveryScan":
        system_name = entry.get("SystemName")
        body_count = entry.get("BodyCount")
        if system_name is not None and body_count is not None:
            data["system_body_counts"][system_name] = body_count
            if data["current_system_name"] is None:
                # Bootstrap: a discovery scan happened before we ever saw a
                # Location/FSDJump event (e.g. very start of journal history).
                data["current_system_name"] = system_name
            if update_system_metric(
                data["system_records"], BODY_COUNT_METRIC, body_count, system_name, entry.get("timestamp")
            ):
                updates += 1

    elif event == "ScanOrganic":
        normalized = normalize_organic_scan(entry)
        if normalized is not None and normalized["scan_type"] == "Analyse":
            # "Analyse" is the final, completed scan (after the 3 required
            # samples) -- the point where the species is definitively
            # identified. "Log" and "Sample" are earlier, partial steps.
            key = f"{normalized['genus']}|{normalized['species']}|{normalized['variant']}"
            bio_entry = data["bio_species"].get(key)
            if bio_entry is None:
                data["bio_species"][key] = {
                    "count": 1,
                    "first_seen": normalized["timestamp"],
                    "system_name": data["current_system_name"],
                    "body_id": normalized["body_id"],
                }
                updates += 1
            else:
                bio_entry["count"] += 1

    return updates


def rebuild_own_records(journal_dir: str, progress_callback=None) -> dict:
    """
    Rebuilds own_records.json from scratch by replaying the entire journal
    history. Useful as a manual "full rebuild" action (e.g. after logic
    changes, or if the incremental state is ever suspected to be out of sync).

    Safe by construction: the existing file is only set aside (not deleted)
    once we've confirmed the journal folder is reachable, and is restored
    automatically if the rebuild fails or is interrupted for any reason. It
    is only permanently discarded after the rebuild completes successfully.
    """
    ensure_journal_dir_accessible(journal_dir)  # raises before anything is touched, if unreachable

    backup_path = OWN_RECORDS_PATH + ".bak"
    had_existing = os.path.exists(OWN_RECORDS_PATH)
    if had_existing:
        os.replace(OWN_RECORDS_PATH, backup_path)  # atomic rename -- old data is preserved as a backup

    try:
        result = build_or_update_own_records(journal_dir, progress_callback=progress_callback)
    except Exception:
        if had_existing and os.path.exists(backup_path):
            os.replace(backup_path, OWN_RECORDS_PATH)  # restore original on any failure
        raise
    else:
        if had_existing and os.path.exists(backup_path):
            os.remove(backup_path)  # rebuild succeeded -- safe to discard the backup
        return result


def build_or_update_own_records(journal_dir: str, progress_callback=None) -> dict:
    """
    Processes journal files to build or incrementally update the personal
    records database. Already-processed files are skipped entirely; the
    most recently processed file is resumed from its last known line.

    A single pass over new lines keeps everything in sync: per-type/param
    bests, system-level bests, and the "live view" of the current system
    (current_system_name, system_bodies, system_body_counts) -- no separate
    re-scanning of old journal files is needed anywhere else in the app.

    progress_callback(message: str), if given, is called with short status
    updates (useful for showing progress in a GUI).

    Raises JournalAccessError if the journal folder can't be reached --
    callers should catch this and show a clear warning instead of treating
    a network outage as "nothing new to process".
    """
    ensure_journal_dir_accessible(journal_dir)

    data = load_own_records()
    all_files = find_journal_files(journal_dir)  # oldest to newest

    processed_files = set(data["processed_files"])
    last_file = data["last_file"]
    last_line = data["last_line"]
    tallied_bodies = set(data["system_tallied_bodies"])

    total_updates = 0

    try:
        for path in all_files:
            filename = os.path.basename(path)

            if filename in processed_files:
                continue

            start_line = last_line if filename == last_file else 0

            if progress_callback:
                progress_callback(f"Processing {filename} from line {start_line}...")

            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError as exc:
                # File temporarily locked/unreadable (e.g. the game is writing to
                # it right now) -- skip for this run, it isn't marked processed
                # so it will simply be retried on the next call.
                if progress_callback:
                    progress_callback(f"Warning: could not read {filename}: {exc}")
                continue

            line_count = len(lines)
            for line in lines[start_line:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total_updates += _process_line(entry, data, tallied_bodies)

            # This file is now up to date. If it's the newest file overall, it may
            # still grow later, so we track it as "last_file" rather than "fully processed".
            data["last_file"] = filename
            data["last_line"] = line_count

            if path != all_files[-1]:
                # Not the newest file anymore (a newer one exists) -> mark fully processed.
                processed_files.add(filename)
    finally:
        # Always persist whatever progress was made, even if something above
        # raised partway through -- otherwise a single bad file could discard
        # an entire run's worth of updates.
        data["processed_files"] = sorted(processed_files)
        data["system_tallied_bodies"] = sorted(tallied_bodies)
        save_own_records(data)

    if progress_callback:
        progress_callback(f"Done. {total_updates} personal record slots updated.")

    return data


if __name__ == "__main__":
    from config import JOURNAL_DIR

    def report(msg):
        print(msg)

    try:
        result = build_or_update_own_records(JOURNAL_DIR, progress_callback=report)
    except JournalAccessError as exc:
        print(f"ERROR: {exc}")
        print("Check that the journal folder path in config.py is correct and reachable.")
    else:
        print(f"\nTotal tracked type+parameter combinations: {len(result['records'])}")
        print(f"System-level metrics tracked: {list(result['system_records'].keys())}")
        print(f"Systems with tallies: {len(result['system_tallies'])}")
        print(f"Current system: {result['current_system_name']}")
        current_bodies = result["system_bodies"].get(result["current_system_name"], {})
        print(f"Bodies scanned there (all-time): {len(current_bodies)}")
        print(f"Current system body count (honk): {result['system_body_counts'].get(result['current_system_name'])}")
        if BODY_COUNT_METRIC in result["system_records"]:
            print("Body count best:", result["system_records"][BODY_COUNT_METRIC])
        if "numPlanets" in result["system_records"]:
            print("Most planets best:", result["system_records"]["numPlanets"])

        # Print a handful of example entries
        for key, entry in list(result["records"].items())[:5]:
            print(key, entry)
