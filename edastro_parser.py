from bs4 import BeautifulSoup


def clean_text(text: str) -> str:
    """Replaces non-breaking spaces with regular spaces and strips whitespace/colons."""
    if text is None:
        return ""
    text = text.replace("\xa0", " ").strip()
    text = text.lstrip(":").strip()
    return text


def parse_records_page(html: str) -> list[dict]:
    """
    Parses an EDAstro /records/<attribute>.html page and returns
    a list of records (one entry per body type, e.g. "Ammonia world").
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="galrecords")
    if table is None:
        return []

    rows = table.find_all("tr")
    results = []

    i = 0
    while i < len(rows):
        tr = rows[i]
        if "recordrow" in (tr.get("class") or []):
            # --- Type name + attribute ---
            name_cell = tr.find("td", class_="recordname")
            bold = name_cell.find("b")
            type_name = clean_text(bold.get_text() if bold else name_cell.get_text())

            # The attribute name comes after the <br/>, e.g. "(Radius)"
            full_text = name_cell.get_text(separator="|")
            parts = full_text.split("|")
            attribute = clean_text(parts[1]).strip("()") if len(parts) > 1 else ""

            # --- Highest row (this row also contains the name cell, so indices shift by 1) ---
            tds = tr.find_all("td")
            highest_value = clean_text(tds[3].get_text()) if len(tds) > 3 else None
            highest_link_tag = tr.find("td", class_="recordlink")
            highest_body = clean_text(highest_link_tag.get_text()) if highest_link_tag else None
            highest_url = None
            if highest_link_tag and highest_link_tag.find("a"):
                highest_url = highest_link_tag.find("a")["href"]

            # --- Lowest row (no name cell here, so indices are one lower) ---
            lowest_value = lowest_body = lowest_url = None
            if i + 1 < len(rows):
                tr_low = rows[i + 1]
                tds_low = tr_low.find_all("td")
                if len(tds_low) > 2:
                    lowest_value = clean_text(tds_low[2].get_text())
                link_low = tr_low.find("td", class_="recordlink")
                if link_low:
                    lowest_body = clean_text(link_low.get_text())
                    if link_low.find("a"):
                        lowest_url = link_low.find("a")["href"]

            # --- Average row (i+3), Count/StdDev row (i+4); i+2 is a blank spacer row ---
            average_value = count_value = stddev_value = None
            if i + 3 < len(rows):
                tr_avg = rows[i + 3]
                tds_avg = tr_avg.find_all("td")
                if len(tds_avg) > 2:
                    average_value = clean_text(tds_avg[2].get_text())
            if i + 4 < len(rows):
                tr_cnt = rows[i + 4]
                name_td = tr_cnt.find("td", class_="recordname")
                if name_td:
                    count_value = clean_text(name_td.get_text()).replace("Count:", "").strip()
                tds_cnt = tr_cnt.find_all("td")
                if len(tds_cnt) > 3:
                    stddev_value = clean_text(tds_cnt[3].get_text())

            results.append({
                "type": type_name,
                "attribute": attribute,
                "highest_value": highest_value,
                "highest_body": highest_body,
                "highest_url": highest_url,
                "lowest_value": lowest_value,
                "lowest_body": lowest_body,
                "lowest_url": lowest_url,
                "average": average_value,
                "count": count_value,
                "stddev": stddev_value,
            })

        i += 1

    return results


if __name__ == "__main__":
    with open("radius_sample.html", "r", encoding="utf-8") as f:
        html = f.read()

    records = parse_records_page(html)
    print(f"Found {len(records)} record blocks.\n")
    for r in records[:5]:
        print(r)
