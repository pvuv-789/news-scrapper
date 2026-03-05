"""
Scraping Orchestrator Service — coordinates scrape → summarize → tag → deduplicate → persist.
SRP: ONLY orchestrates the pipeline; delegates ALL work to other services and repos.
"""
import uuid
from datetime import date, datetime, timezone
from typing import List

from core.database import AsyncSessionFactory
from core.logging_config import get_logger
from models.db_models import Article, ArticleTag, CrawlRun, Tag
from repositories.article_repository import ArticleRepository
from repositories.crawl_run_repository import CrawlRunRepository
from repositories.edition_repository import EditionRepository
from scraper.base_scraper import BaseScraper, ScrapedArticle
from scraper.daily_thanthi_scraper import DailyThanthiScraper
from services.deduplication_service import DeduplicationService
from services.summarization_service import SummarizationService
from services.tagging_service import TaggingService
from sqlalchemy import select

logger = get_logger(__name__)


class ScrapingOrchestrator:
    """
    Coordinates the full ingestion pipeline for one publication.
    Called by Celery tasks; uses standalone async sessions (not FastAPI DI).
    """

    def __init__(
        self,
        publication_id: uuid.UUID,
        scraper: BaseScraper | None = None,
    ) -> None:
        self._publication_id = publication_id
        self._scraper: BaseScraper = scraper or DailyThanthiScraper()
        self._summarizer = SummarizationService()
        self._tagger = TaggingService()

    async def run(self, target_date: date) -> None:
        """Execute the full pipeline for all active editions of the publication."""
        async with AsyncSessionFactory() as session:
            crawl_repo = CrawlRunRepository(session)
            edition_repo = EditionRepository(session)
            article_repo = ArticleRepository(session)
            dedup_svc = DeduplicationService(article_repo)

            # Log crawl run start
            run = CrawlRun(
                publication_id=self._publication_id,
                target_date=datetime.combine(target_date, datetime.min.time()).replace(
                    tzinfo=timezone.utc
                ),
                status="running",
            )
            run = await crawl_repo.create(run)
            await session.commit()

            scraped_count = 0
            inserted_count = 0
            dedup_count = 0

            try:
                editions = await edition_repo.get_active_by_publication(self._publication_id)
                for edition in editions:
                    articles = await self._scraper.scrape(edition.city_code, target_date)
                    scraped_count += len(articles)

                    for scraped in articles:
                        result = await self._ingest_article(
                            scraped,
                            article_repo,
                            dedup_svc,
                            session,
                            edition_id=edition.id,
                        )
                        if result == "inserted":
                            inserted_count += 1
                        elif result == "duplicate":
                            dedup_count += 1

                    await session.commit()

                await crawl_repo.mark_success(run.id, scraped_count, inserted_count, dedup_count)
                await session.commit()
                logger.info(
                    "orchestrator_success",
                    scraped=scraped_count,
                    inserted=inserted_count,
                    deduplicated=dedup_count,
                )

            except Exception as exc:
                await crawl_repo.mark_failed(run.id, exc)
                await session.commit()
                logger.error("orchestrator_failed", error=str(exc))
                raise

            finally:
                await self._scraper.close()

    async def _ingest_article(
        self,
        scraped: ScrapedArticle,
        article_repo: ArticleRepository,
        dedup_svc: DeduplicationService,
        session,
        edition_id: uuid.UUID,
    ) -> str:
        """
        Process a single scraped article through the pipeline.
        Returns: 'inserted' | 'duplicate' | 'skipped'
        """
        # 1. Hard dedup: skip if exact URL already exists
        if await article_repo.url_exists(self._publication_id, scraped.url):
            logger.debug("url_exists_skip", url=scraped.url[:80])
            return "skipped"

        # 2. Soft dedup: similarity check via pg_trgm
        original_id = await dedup_svc.find_original(scraped.title)

        # 3. Summarize + word count
        summary = self._summarizer.summarize(scraped.raw_text or scraped.title)
        word_count = self._summarizer.word_count(scraped.raw_text or "")

        # 4. Persist article
        published_dt = (
            datetime.combine(scraped.published_date, datetime.min.time()).replace(
                tzinfo=timezone.utc
            )
            if scraped.published_date
            else None
        )
        article = Article(
            publication_id=self._publication_id,
            edition_id=edition_id,
            title=scraped.title,
            subtitle=scraped.subtitle,
            byline=scraped.byline,
            url=scraped.url,
            summary=summary,
            word_count_estimate=word_count,
            page_number=scraped.page_number,
            page_label=scraped.page_label,
            location=scraped.location,
            published_at=published_dt,
            is_active=True,
            is_duplicate=original_id is not None,
            duplicate_of_id=original_id,
        )
        article = await article_repo.create(article)
        await session.flush()

        # 5. Tag assignment
        tag_pairs = self._tagger.extract_tags(scraped.title, scraped.raw_text or "")
        for tag_name, tag_slug in tag_pairs:
            tag = await self._get_or_create_tag(session, tag_name, tag_slug)
            session.add(ArticleTag(article_id=article.id, tag_id=tag.id))

        if original_id:
            await dedup_svc.handle_duplicate(article.id, original_id)
            return "duplicate"

        return "inserted"

    @staticmethod
    async def _get_or_create_tag(session, name: str, slug: str) -> Tag:
        result = await session.execute(select(Tag).where(Tag.slug == slug))
        tag = result.scalar_one_or_none()
        if not tag:
            tag = Tag(name=name, slug=slug)
            session.add(tag)
            await session.flush()
        return tag
