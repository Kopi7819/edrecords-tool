import json
import os
from datetime import datetime, timezone

CACHE_DIR = "cache"


def _cache_path(attribute_slug: str) -> str:
    """Returns the file path for a given attribute's cache file."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{attribute_slug}.json")


def save_records(attribute_slug: str, records: list[dict]) -> None:
    """Saves parsed records to a JSON file, along with a fetch timestamp."""
    payload = {
        "attribute_slug": attribute_slug,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    path = _cache_path(attribute_slug)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_records(attribute_slug: str) -> dict | None:
    """
    Loads cached records for the given attribute slug.
    Returns a dict with keys "attribute_slug", "fetched_at", "records",
    or None if no cache file exists yet.
    """
    path = _cache_path(attribute_slug)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def has_cache(attribute_slug: str) -> bool:
    """Quick check whether a cache file exists for the given attribute slug."""
    return os.path.exists(_cache_path(attribute_slug))
