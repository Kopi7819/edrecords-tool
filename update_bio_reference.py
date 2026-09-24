"""
Refreshes bio_reference.py by re-fetching and re-parsing the source data
from the EDMC-BioScan and EDMC-ExploData GitHub repositories. Reports a
summary of what changed (new/removed genera, species, variant counts).

Can be run standalone (python update_bio_reference.py) or triggered from
the app's Actions menu.
"""

import importlib.util
import os
import re
import tempfile

import requests

BIOSCAN_RAW_BASE = "https://raw.githubusercontent.com/Silarn/EDMC-BioScan/master/src/bio_scan/bio_data"
EXPLODATA_RAW_URL = (
    "https://raw.githubusercontent.com/Silarn/EDMC-ExploData/master/src/ExploData/explo_data/bio_data/genus.py"
)
REFERENCE_PATH = "bio_reference.py"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EDRecordsTool/0.1"


def _fetch_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    response.raise_for_status()
    return response.text


def _load_module_from_text(name: str, source: str, tmp_dir: str):
    path = os.path.join(tmp_dir, f"{name}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fetch_fresh_data(progress_callback=None) -> dict:
    """Downloads and parses the current source data. Returns the computed reference dicts."""

    def report(msg):
        if progress_callback:
            progress_callback(msg)

    with tempfile.TemporaryDirectory() as tmp_dir:
        report("Fetching species.py...")
        species_source = _fetch_text(f"{BIOSCAN_RAW_BASE}/species.py")

        # species.py imports each ruleset module by name -- parse those
        # import lines instead of hardcoding the file list, so a newly added
        # genus (with its own ruleset file) is picked up automatically.
        ruleset_names = re.findall(r"from bio_scan\.bio_data\.rulesets\.(\w+) import catalog", species_source)

        rulesets_dir = os.path.join(tmp_dir, "bio_scan", "bio_data", "rulesets")
        os.makedirs(rulesets_dir, exist_ok=True)
        # Make the fake package structure importable.
        for pkg_dir in (
            os.path.join(tmp_dir, "bio_scan"),
            os.path.join(tmp_dir, "bio_scan", "bio_data"),
            rulesets_dir,
        ):
            open(os.path.join(pkg_dir, "__init__.py"), "w").close()

        for name in ruleset_names:
            report(f"Fetching ruleset: {name}...")
            source = _fetch_text(f"{BIOSCAN_RAW_BASE}/rulesets/{name}.py")
            with open(os.path.join(rulesets_dir, f"{name}.py"), "w", encoding="utf-8") as f:
                f.write(source)

        with open(os.path.join(tmp_dir, "bio_scan", "bio_data", "species.py"), "w", encoding="utf-8") as f:
            f.write(species_source)

        import sys

        sys.path.insert(0, tmp_dir)
        try:
            from bio_scan.bio_data.species import rules as species_rules
        finally:
            sys.path.remove(tmp_dir)
            for mod_name in list(sys.modules):
                if mod_name.startswith("bio_scan"):
                    del sys.modules[mod_name]

        report("Fetching genus.py (color/variant data)...")
        genus_source = _fetch_text(EXPLODATA_RAW_URL)
        genus_module = _load_module_from_text("genus_data_fresh", genus_source, tmp_dir)
        genus_data = genus_module.data

    def variant_count_for_species(genus_id, species_id):
        genus_info = genus_data.get(genus_id, {})
        colors = genus_info.get("colors")
        if not colors:
            return 0
        if "star" in colors:
            return len(colors["star"])
        if "species" in colors:
            species_colors = colors["species"].get(species_id)
            if not species_colors:
                return 0
            if "star" in species_colors:
                return len(species_colors["star"])
            if "element" in species_colors:
                return len(species_colors["element"])
        return 0

    genus_species_totals = {}
    species_variant_totals = {}
    genus_variant_totals = {}

    for genus_id, species_dict in species_rules.items():
        genus_name = genus_data.get(genus_id, {}).get("name", genus_id)
        genus_species_totals[genus_name] = len(species_dict)
        genus_total_variants = 0
        for species_id, species_info in species_dict.items():
            species_name = species_info.get("name", species_id)
            vcount = variant_count_for_species(genus_id, species_id)
            species_variant_totals[species_name] = vcount
            genus_total_variants += vcount
        genus_variant_totals[genus_name] = genus_total_variants

    return {
        "genus_species_totals": genus_species_totals,
        "species_variant_totals": species_variant_totals,
        "genus_variant_totals": genus_variant_totals,
    }


def load_current_data() -> dict:
    """Loads the currently-saved bio_reference.py, or empty dicts if it doesn't exist yet."""
    if not os.path.exists(REFERENCE_PATH):
        return {"genus_species_totals": {}, "species_variant_totals": {}, "genus_variant_totals": {}}
    spec = importlib.util.spec_from_file_location("bio_reference_current", REFERENCE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "genus_species_totals": dict(module.GENUS_SPECIES_TOTALS),
        "species_variant_totals": dict(module.SPECIES_VARIANT_TOTALS),
        "genus_variant_totals": dict(module.GENUS_VARIANT_TOTALS),
    }


def diff_summary(old: dict, new: dict) -> list[str]:
    """Returns a list of human-readable lines describing what changed."""
    lines = []

    old_genera = set(old["genus_species_totals"])
    new_genera = set(new["genus_species_totals"])
    for genus in sorted(new_genera - old_genera):
        lines.append(f"+ New genus: {genus}")
    for genus in sorted(old_genera - new_genera):
        lines.append(f"- Removed genus: {genus}")
    for genus in sorted(old_genera & new_genera):
        old_count = old["genus_species_totals"][genus]
        new_count = new["genus_species_totals"][genus]
        if old_count != new_count:
            lines.append(f"~ {genus}: species count {old_count} -> {new_count}")

    old_species = set(old["species_variant_totals"])
    new_species = set(new["species_variant_totals"])
    for species in sorted(new_species - old_species):
        lines.append(f"+ New species: {species}")
    for species in sorted(old_species - new_species):
        lines.append(f"- Removed species: {species}")
    for species in sorted(old_species & new_species):
        old_count = old["species_variant_totals"][species]
        new_count = new["species_variant_totals"][species]
        if old_count != new_count:
            lines.append(f"~ {species}: variant count {old_count} -> {new_count}")

    return lines


def write_reference_file(data: dict) -> None:
    lines = [
        "# Reference data for the Bioscan Stats tab's \"found / total\" progress",
        "# display. Sourced from the EDMC-BioScan / EDMC-ExploData plugins'",
        "# open-source reference data (github.com/Silarn/EDMC-BioScan,",
        "# github.com/Silarn/EDMC-ExploData). Regenerated by update_bio_reference.py --",
        "# run that script (or Actions -> Update Bio Reference Data in the app) to refresh.",
        "",
        "# Total number of known species per genus.",
        "GENUS_SPECIES_TOTALS = {",
    ]
    for genus, count in sorted(data["genus_species_totals"].items()):
        lines.append(f"    {genus!r}: {count},")
    lines.append("}")
    lines.append("")
    lines.append("# Total number of known color variants per species. 0 means no color variants.")
    lines.append("SPECIES_VARIANT_TOTALS = {")
    for species, count in sorted(data["species_variant_totals"].items()):
        lines.append(f"    {species!r}: {count},")
    lines.append("}")
    lines.append("")
    lines.append("# Genus -> total variants across all of that genus's species.")
    lines.append("GENUS_VARIANT_TOTALS = {")
    for genus, count in sorted(data["genus_variant_totals"].items()):
        lines.append(f"    {genus!r}: {count},")
    lines.append("}")
    lines.append("")
    lines.append("TOTAL_KNOWN_GENERA = len(GENUS_SPECIES_TOTALS)")
    lines.append("TOTAL_KNOWN_SPECIES = sum(GENUS_SPECIES_TOTALS.values())")
    lines.append("TOTAL_KNOWN_VARIANTS = sum(SPECIES_VARIANT_TOTALS.values())")
    lines.append("")

    temp_path = REFERENCE_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(temp_path, REFERENCE_PATH)


def update_bio_reference(progress_callback=None) -> list[str]:
    """
    Fetches fresh data, writes it to bio_reference.py, and returns a list of
    change-summary lines (empty list if nothing changed).
    """
    old_data = load_current_data()
    new_data = fetch_fresh_data(progress_callback=progress_callback)
    changes = diff_summary(old_data, new_data)
    write_reference_file(new_data)
    return changes


if __name__ == "__main__":
    def report(msg):
        print(msg)

    changes = update_bio_reference(progress_callback=report)
    print()
    if changes:
        print(f"{len(changes)} change(s) found:")
        for line in changes:
            print(" ", line)
    else:
        print("No changes -- reference data is already up to date.")
