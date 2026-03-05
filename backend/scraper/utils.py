"""
Shared scraper utilities — string sanitization, date parsing, HTML cleaning.
DRY: All common utilities live here; no scraper duplicates these functions.
"""
import re
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup


def sanitize_text(text: Optional[str]) -> Optional[str]:
    """Strip HTML tags, collapse whitespace, and strip leading/trailing spaces."""
    if not text:
        return None
    soup = BeautifulSoup(text, "lxml")
    clean = soup.get_text(separator=" ")
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean if clean else None


def parse_date(raw: Optional[str], formats: list[str] | None = None) -> Optional[date]:
    """
    Attempt to parse a date string using the provided formats.
    Falls back to today's date if parsing fails.
    """
    if not raw:
        return date.today()

    if formats is None:
        formats = [
            "%d/%m/%Y",
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d %B %Y",
            "%B %d, %Y",
        ]
    raw = raw.strip()
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return date.today()


def extract_page_number(label: Optional[str]) -> Optional[int]:
    """Extract numeric page number from a label string like 'Page 3' or 'P-3'."""
    if not label:
        return None
    match = re.search(r"\d+", label)
    return int(match.group()) if match else None


def build_absolute_url(base_url: str, path: str) -> str:
    """Construct an absolute URL from a base and a relative path."""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base_url = base_url.rstrip("/")
    path = path.lstrip("/")
    return f"{base_url}/{path}"
