import json
import os

SETTINGS_PATH = "settings.json"

DEFAULT_SETTINGS = {
    "journal_dir": None,  # None means "use the default in config.py"
    "auto_refresh_ms": None,
    "edastro_cache_max_age_days": None,
}


def load_settings() -> dict:
    """Loads user-saved settings, filling in None for anything not yet customized."""
    if not os.path.exists(SETTINGS_PATH):
        return dict(DEFAULT_SETTINGS)
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    return merged


def save_settings(settings: dict) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
