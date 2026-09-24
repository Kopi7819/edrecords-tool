import requests

BASE_URL = "https://edastro.com/records/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EDRecordsTool/0.1"


def fetch_records_page(attribute_slug: str) -> str:
    """
    Downloads a single EDAstro records page for the given attribute slug
    (e.g. "radius" for https://edastro.com/records/radius.html)
    and returns the raw HTML as text.
    """
    url = f"{BASE_URL}{attribute_slug}.html"
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.text
