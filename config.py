import os

from settings import load_settings

# --- Hardcoded defaults (used unless overridden via the in-app Settings panel) ---

# Standard Elite Dangerous journal location (works out of the box for most
# players). If your journals live somewhere else -- e.g. a network share, or
# a non-default Saved Games location -- change this in the in-app Settings
# dialog rather than editing this file.
_DEFAULT_JOURNAL_DIR = os.path.expandvars(r"%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous")

# How often the GUI re-checks the current system / personal records, in milliseconds.
# This does NOT by itself trigger an EDAstro download -- it just re-reads local
# journal/cache files. An actual EDAstro download only happens when a given
# attribute's cache turns out to be older than EDASTRO_CACHE_MAX_AGE_DAYS.
_DEFAULT_AUTO_REFRESH_MS = 5000

# EDAstro states its records are "updated weekly", so any cached attribute
# page older than this many days is treated as stale and re-downloaded.
_DEFAULT_EDASTRO_CACHE_MAX_AGE_DAYS = 7

# --- Effective values: settings.json overrides the defaults above, if set ---
_settings = load_settings()

JOURNAL_DIR = _settings.get("journal_dir") or _DEFAULT_JOURNAL_DIR
AUTO_REFRESH_MS = _settings.get("auto_refresh_ms") or _DEFAULT_AUTO_REFRESH_MS
EDASTRO_CACHE_MAX_AGE_DAYS = _settings.get("edastro_cache_max_age_days") or _DEFAULT_EDASTRO_CACHE_MAX_AGE_DAYS
