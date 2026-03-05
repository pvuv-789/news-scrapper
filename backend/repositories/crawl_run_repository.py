"""
CrawlRun Repository — Data Access Layer for crawl_runs.
SRP: ONLY handles database queries related to crawl runs / job metrics.
"""
import traceback
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import CrawlRun
from repositories.base_repository import BaseRepository


class CrawlRunRepository(BaseRepository[CrawlRun]):

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_id(self, record_id: UUID) -> Optional[CrawlRun]:
        result = await self._session.execute(
            select(CrawlRun).where(CrawlRun.id == record_id)
        )
        return result.scalar_one_or_none()

    async def get_all(self, limit: int = 100, offset: int = 0) -> List[CrawlRun]:
        result = await self._session.execute(
            select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, obj: CrawlRun) -> CrawlRun:
        self._session.add(obj)
        await self._session.flush()
        await self._session.refresh(obj)
        return obj

    async def delete(self, record_id: UUID) -> bool:
        run = await self.get_by_id(record_id)
        if run:
            await self._session.delete(run)
            return True
        return False

    async def mark_success(
        self, run_id: UUID, scraped: int, inserted: int, deduplicated: int
    ) -> None:
        run = await self.get_by_id(run_id)
        if run:
            run.status = "success"
            run.ended_at = datetime.now(timezone.utc)
            run.articles_scraped = scraped
            run.articles_inserted = inserted
            run.articles_deduplicated = deduplicated

    async def mark_failed(self, run_id: UUID, exc: Exception) -> None:
        run = await self.get_by_id(run_id)
        if run:
            run.status = "failed"
            run.ended_at = datetime.now(timezone.utc)
            run.error_log = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
