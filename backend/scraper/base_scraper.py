"""
Abstract Base Scraper — defines the interface all scrapers must implement.
OCP: Open for extension (add new publisher scrapers), closed for modification.
LSP: Any concrete scraper substitutable via BaseScraper.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class ScrapedArticle:
    """
    Immutable data class representing a single article scraped from an e-paper.
    This is the contract between the scraper layer and the service layer.
    """
    title: str
    url: str
    subtitle: Optional[str] = None
    byline: Optional[str] = None
    page_number: Optional[int] = None
    page_label: Optional[str] = None
    location: Optional[str] = None
    raw_text: Optional[str] = None
    published_date: Optional[date] = None


class BaseScraper(ABC):
    """
    Abstract base class for all e-paper scrapers.
    Implements the Template Method pattern:
      - `scrape()` is the public interface.
      - Subclasses implement `_fetch_articles()`.
    """

    @abstractmethod
    async def scrape(self, edition_code: str, target_date: date) -> List[ScrapedArticle]:
        """
        Scrape all articles from a given edition on a given date.

        Args:
            edition_code: City code matching the editions table (e.g. 'chennai').
            target_date: The publication date to scrape.

        Returns:
            List of ScrapedArticle dataclasses.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release browser/session resources."""
        ...
