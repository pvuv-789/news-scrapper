"""
Tagging Service — Keyword extraction and tag assignment.
SRP: ONLY handles tag logic — no DB direct access, no scraping.
"""
import re
from typing import List

from core.logging_config import get_logger

logger = get_logger(__name__)

# Predefined taxonomy of section keywords → tag name mappings (extendable via config)
_KEYWORD_MAP: dict[str, str] = {
    # Politics
    "election": "Politics", "government": "Politics", "minister": "Politics",
    "parliament": "Politics", "dmk": "Politics", "aiadmk": "Politics",
    "bjp": "Politics", "congress": "Politics", "vote": "Politics",
    # Sports
    "cricket": "Sports", "ipl": "Sports", "football": "Sports", "sports": "Sports",
    "match": "Sports", "tournament": "Sports", "player": "Sports",
    # Crime
    "murder": "Crime", "robbery": "Crime", "arrest": "Crime", "police": "Crime",
    "crime": "Crime", "theft": "Crime", "fraud": "Crime",
    # Business
    "market": "Business", "stock": "Business", "economy": "Business",
    "business": "Business", "trade": "Business", "finance": "Business",
    # Technology
    "technology": "Technology", "ai": "Technology", "software": "Technology",
    "internet": "Technology", "digital": "Technology",
    # Health
    "health": "Health", "hospital": "Health", "doctor": "Health",
    "covid": "Health", "medicine": "Health", "disease": "Health",
    # Weather
    "rain": "Weather", "flood": "Weather", "cyclone": "Weather",
    "drought": "Weather", "temperature": "Weather",
    # Education
    "school": "Education", "college": "Education", "university": "Education",
    "exam": "Education", "student": "Education",
}


def _slugify(name: str) -> str:
    """Convert tag name to a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class TaggingService:
    """
    Assigns tags to an article based on keyword matching against title + raw_text.
    Returns a deduplicated list of (tag_name, tag_slug) tuples.
    """

    def extract_tags(self, title: str, raw_text: str = "") -> List[tuple[str, str]]:
        """
        Returns a list of (name, slug) tuples for matched tags.
        Deduplicates by tag name (DRY — single scan).
        """
        combined = f"{title} {raw_text}".lower()
        matched: dict[str, str] = {}  # name → slug

        for keyword, tag_name in _KEYWORD_MAP.items():
            if keyword in combined and tag_name not in matched:
                matched[tag_name] = _slugify(tag_name)

        logger.debug("extract_tags", tags_found=list(matched.keys()))
        return list(matched.items())  # [(name, slug), ...]
