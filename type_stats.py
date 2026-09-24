from journal_parser import TERRAFORM_CANDIDATE_STATES


def build_type_crosstab(
    system_bodies: dict, landable_only: bool = False, terraformable_only: bool = False
) -> dict:
    """
    Returns {star_type: {planet_type: count}}, based on each system's
    primary star (the star with the lowest BodyID in that system) and the
    planet types found in that same system. Only star/planet types you've
    actually encountered appear -- there's no fixed universe of rows/columns.

    If landable_only/terraformable_only are True, only planets matching that
    criterion are counted.
    """
    crosstab = {}

    for bodies in system_bodies.values():
        stars = [b for b in bodies.values() if b["kind"] == "star"]
        if not stars:
            continue

        primary_star = min(stars, key=lambda s: s["body_id"] if s.get("body_id") is not None else 0)
        star_type = primary_star["type"]

        for body in bodies.values():
            if body["kind"] != "planet":
                continue
            if landable_only and not body.get("landable"):
                continue
            if terraformable_only and body.get("terraform_state") not in TERRAFORM_CANDIDATE_STATES:
                continue
            planet_type = body["type"]
            row = crosstab.setdefault(star_type, {})
            row[planet_type] = row.get(planet_type, 0) + 1

    return crosstab


def count_all_stars(system_bodies: dict) -> int:
    """
    Total number of distinct stars scanned across all systems -- including
    secondary/tertiary stars in multi-star systems, unlike count_primary_stars
    (which only counts one, the primary, per system).
    """
    total = 0
    for bodies in system_bodies.values():
        total += sum(1 for b in bodies.values() if b["kind"] == "star")
    return total


def count_primary_stars(system_bodies: dict) -> dict:
    """
    Returns {star_type: count} -- how many systems (visited so far) have a
    primary star of that type. Independent of the planet crosstab, since the
    crosstab's row totals count *planets*, not *systems*/*stars*.
    """
    counts = {}
    for bodies in system_bodies.values():
        stars = [b for b in bodies.values() if b["kind"] == "star"]
        if not stars:
            continue
        primary_star = min(stars, key=lambda s: s["body_id"] if s.get("body_id") is not None else 0)
        counts[primary_star["type"]] = counts.get(primary_star["type"], 0) + 1
    return counts


def compute_margins(crosstab: dict) -> tuple[dict, dict, int]:
    """Returns (row_totals, col_totals, grand_total) for a crosstab from build_type_crosstab."""
    row_totals = {star_type: sum(row.values()) for star_type, row in crosstab.items()}

    col_totals = {}
    for row in crosstab.values():
        for planet_type, count in row.items():
            col_totals[planet_type] = col_totals.get(planet_type, 0) + count

    grand_total = sum(row_totals.values())
    return row_totals, col_totals, grand_total


if __name__ == "__main__":
    from own_records import load_own_records

    data = load_own_records()
    crosstab = build_type_crosstab(data["system_bodies"])
    row_totals, col_totals, grand_total = compute_margins(crosstab)

    print(f"Star types: {len(crosstab)}, Planet types: {len(col_totals)}, Grand total: {grand_total}\n")
    for star_type, row in sorted(crosstab.items(), key=lambda item: -row_totals[item[0]]):
        print(f"{star_type} (total {row_totals[star_type]}):")
        for planet_type, count in sorted(row.items(), key=lambda item: -item[1]):
            print(f"    {planet_type}: {count}")
