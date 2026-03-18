"""
Daily Thanthi E-Paper Scraper — Playwright-based concrete implementation.
SRP: ONLY handles scraping logic for Daily Thanthi epaper.
OCP: Extends BaseScraper without modifying any shared pipeline code.
LSP: Fully substitutable wherever BaseScraper is expected.
Resilience: Uses tenacity for exponential backoff retries on network failures.
"""
import asyncio
from datetime import date
from typing import List, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.config import get_settings
from core.logging_config import get_logger
from scraper.base_scraper import BaseScraper, ScrapedArticle
from scraper.utils import build_absolute_url, extract_page_number, sanitize_text

logger = get_logger(__name__)
_settings = get_settings()


class DailyThanthiScraper(BaseScraper):
    """
    Playwright scraper for https://epaper.dailythanthi.com.

    Navigation flow:
        1. Open epaper homepage for the target date.
        2. Locate edition links matching the edition_code.
        3. Iterate pages and extract article metadata.

    NOTE: Selectors are illustrative — adjust to actual DOM after
    inspecting the live epaper page.
    """

    _EDITION_URL_TEMPLATE = "{base}/Home/GetEditionPages?editionName={edition}&date={date}"

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def _ensure_browser(self) -> None:
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=_settings.scraper_headless,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            self._context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="ta-IN",
            )

    async def scrape(self, edition_code: str, target_date: date) -> List[ScrapedArticle]:
        """Entry point — scrape all articles for a given edition and date."""
        await self._ensure_browser()
        articles: List[ScrapedArticle] = []

        try:
            url = self._build_edition_url(edition_code, target_date)
            logger.info("scrape_start", edition=edition_code, date=str(target_date), url=url)
            page = await self._context.new_page()
            await self._navigate_with_retry(page, url)
            articles = await self._extract_articles(page, edition_code, target_date)
            await page.close()
        except Exception as exc:
            logger.error("scrape_failed", edition=edition_code, error=str(exc))
            raise

        logger.info("scrape_complete", edition=edition_code, count=len(articles))
        return articles

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ── Private Helpers ────────────────────────────────────────────────────────

    def _build_edition_url(self, edition_code: str, target_date: date) -> str:
        return self._EDITION_URL_TEMPLATE.format(
            base=_settings.epaper_base_url,
            edition=edition_code,
            date=target_date.strftime("%Y-%m-%d"),
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(_settings.scraper_max_retries),
        wait=wait_exponential(
            multiplier=_settings.scraper_backoff_multiplier, min=2, max=30
        ),
        reraise=True,
    )
    async def _navigate_with_retry(self, page: Page, url: str) -> None:
        """Navigate to a URL with exponential backoff retries (REQ-NFR resilience)."""
        logger.debug("navigate", url=url)
        await page.goto(url, timeout=_settings.scraper_timeout_ms, wait_until="networkidle")

    async def _extract_articles(
        self, page: Page, edition_code: str, target_date: date
    ) -> List[ScrapedArticle]:
        """
        Extract article metadata from the loaded epaper page.

        NOTE: CSS selectors below are illustrative.
        Update after inspecting the actual Daily Thanthi epaper DOM structure.
        """
        articles: List[ScrapedArticle] = []

        # Wait for article containers to load
        try:
            await page.wait_for_selector(".article-container", timeout=10_000)
        except Exception:
            logger.warning("no_articles_found", edition=edition_code, date=str(target_date))
            return articles

        article_elements = await page.query_selector_all(".article-container")

        for element in article_elements:
            try:
                title_el = await element.query_selector(".article-title")
                subtitle_el = await element.query_selector(".article-subtitle")
                byline_el = await element.query_selector(".article-byline")
                link_el = await element.query_selector("a")
                page_label_el = await element.query_selector(".page-label")
                location_el = await element.query_selector(".article-location")

                title = sanitize_text(await title_el.inner_text() if title_el else None)
                if not title:
                    continue

                href = await link_el.get_attribute("href") if link_el else None
                url = (
                    build_absolute_url(_settings.epaper_base_url, href)
                    if href
                    else _settings.epaper_base_url
                )

                page_label_raw = (
                    sanitize_text(await page_label_el.inner_text()) if page_label_el else None
                )

                article = ScrapedArticle(
                    title=title,
                    url=url,
                    subtitle=sanitize_text(
                        await subtitle_el.inner_text() if subtitle_el else None
                    ),
                    byline=sanitize_text(await byline_el.inner_text() if byline_el else None),
                    page_label=page_label_raw,
                    page_number=extract_page_number(page_label_raw),
                    location=sanitize_text(
                        await location_el.inner_text() if location_el else None
                    ),
                    published_date=target_date,
                )
                articles.append(article)

            except Exception as exc:
                logger.warning("article_extraction_error", error=str(exc))
                continue

        return articles
