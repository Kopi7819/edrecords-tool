from datetime import datetime, timezone

from edastro_fetch import fetch_records_page
from edastro_parser import parse_records_page
from cache import save_records, load_records, has_cache
from config import EDASTRO_CACHE_MAX_AGE_DAYS


def _is_cache_stale(cached: dict) -> bool:
    fetched_at = datetime.fromisoformat(cached["fetched_at"])
    age = datetime.now(timezone.utc) - fetched_at
    return age.days >= EDASTRO_CACHE_MAX_AGE_DAYS


def get_records_for_attribute(slug: str, force_refresh: bool = False) -> list[dict]:
    """
    Returns the parsed records for a single attribute slug, using the local
    cache when available and fresh (less than CACHE_MAX_AGE_DAYS old).
    Downloads fresh data from EDAstro and updates the cache if force_refresh
    is True, no cache exists yet, or the existing cache has gone stale.
    """
    if not force_refresh and has_cache(slug):
        cached = load_records(slug)
        if not _is_cache_stale(cached):
            return cached["records"]

    html = fetch_records_page(slug)
    records = parse_records_page(html)
    save_records(slug, records)
    return records


def refresh_all_cached_attributes(progress_callback=None) -> None:
    """
    Force-refreshes every EDAstro attribute the app actually uses (both star
    and planet parameter sets), regardless of current cache age. Meant for a
    manual "refresh now" action, since normal operation already refreshes
    automatically once a cache entry turns stale.
    """
    from attributes import STAR_TAB_ATTRIBUTES, PLANET_TAB_ATTRIBUTES

    slugs = sorted(set(STAR_TAB_ATTRIBUTES.values()) | set(PLANET_TAB_ATTRIBUTES.values()))
    for i, slug in enumerate(slugs, start=1):
        if progress_callback:
            progress_callback(f"Refreshing EDAstro data ({i}/{len(slugs)}): {slug}...")
        try:
            get_records_for_attribute(slug, force_refresh=True)
        except Exception as exc:
            if progress_callback:
                progress_callback(f"Warning: failed to refresh {slug}: {exc}")
