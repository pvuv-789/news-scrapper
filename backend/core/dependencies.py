"""
FastAPI dependency injection providers.
DIP: consumers (routes) depend on abstractions injected here, not concrete classes.
"""
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from repositories.article_repository import ArticleRepository
from repositories.crawl_run_repository import CrawlRunRepository
from repositories.edition_repository import EditionRepository
from services.deduplication_service import DeduplicationService
from services.summarization_service import SummarizationService
from services.tagging_service import TaggingService

# ── Database Session ───────────────────────────────────────────────────────────
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ── Repository Providers ───────────────────────────────────────────────────────
def get_article_repository(db: DbSession) -> ArticleRepository:
    return ArticleRepository(db)


def get_edition_repository(db: DbSession) -> EditionRepository:
    return EditionRepository(db)


def get_crawl_run_repository(db: DbSession) -> CrawlRunRepository:
    return CrawlRunRepository(db)


# ── Service Providers ──────────────────────────────────────────────────────────
def get_summarization_service() -> SummarizationService:
    return SummarizationService()


def get_tagging_service() -> TaggingService:
    return TaggingService()


def get_deduplication_service(
    article_repo: Annotated[ArticleRepository, Depends(get_article_repository)],
) -> DeduplicationService:
    return DeduplicationService(article_repo)


# ── Typed Annotated Aliases ────────────────────────────────────────────────────
ArticleRepo = Annotated[ArticleRepository, Depends(get_article_repository)]
EditionRepo = Annotated[EditionRepository, Depends(get_edition_repository)]
CrawlRunRepo = Annotated[CrawlRunRepository, Depends(get_crawl_run_repository)]
SummarizationSvc = Annotated[SummarizationService, Depends(get_summarization_service)]
TaggingSvc = Annotated[TaggingService, Depends(get_tagging_service)]
DedupSvc = Annotated[DeduplicationService, Depends(get_deduplication_service)]
