"""
Article Repository — Data Access Layer for articles.
SRP: ONLY handles database queries related to articles.
LSP: Substitutable wherever BaseRepository[Article] is expected.
"""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Select, and_, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.db_models import Article, Tag
from repositories.base_repository import BaseRepository


class ArticleRepository(BaseRepository[Article]):
    """Data Access Layer for articles — all DB logic lives here."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_id(self, record_id: UUID) -> Optional[Article]:
        stmt = (
            select(Article)
            .where(Article.id == record_id)
            .options(
                selectinload(Article.edition),
                selectinload(Article.section),
                selectinload(Article.tags),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Article]:
        stmt = (
            select(Article)
            .where(Article.is_active == True)  # noqa: E712
            .order_by(Article.published_at.desc())
            .limit(limit)
            .offset(offset)
            .options(
                selectinload(Article.edition),
                selectinload(Article.section),
                selectinload(Article.tags),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, obj: Article) -> Article:
        self._session.add(obj)
        await self._session.flush()
        await self._session.refresh(obj)
        return obj

    async def delete(self, record_id: UUID) -> bool:
        article = await self.get_by_id(record_id)
        if article:
            await self._session.delete(article)
            return True
        return False

    async def get_filtered(
        self,
        edition_id: Optional[UUID] = None,
        section_id: Optional[UUID] = None,
        tag: Optional[str] = None,
        published_date=None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[Article], int]:
        """Filtered article list with total count for pagination."""
        conditions = [Article.is_active == True]  # noqa: E712

        if edition_id:
            conditions.append(Article.edition_id == edition_id)
        if section_id:
            conditions.append(Article.section_id == section_id)
        if published_date:
            # Convert stored UTC timestamp → IST (UTC+5:30) before extracting date
            # so that articles scraped overnight don't land on the wrong calendar day.
            ist_date = func.date(func.timezone('Asia/Kolkata', Article.published_at))
            conditions.append(ist_date == published_date)

        base_stmt: Select = select(Article).where(and_(*conditions))

        if tag:
            base_stmt = base_stmt.join(Article.tags).where(Tag.slug == tag)

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            base_stmt.order_by(Article.published_at.desc())
            .limit(limit)
            .offset(offset)
            .options(
                selectinload(Article.edition),
                selectinload(Article.section),
                selectinload(Article.tags),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def find_similar_by_trgm(
        self, title: str, threshold: float = 0.85
    ) -> Optional[Article]:
        """
        Use PostgreSQL pg_trgm similarity to detect near-duplicate articles.
        Requires pg_trgm extension: CREATE EXTENSION IF NOT EXISTS pg_trgm;
        """
        stmt = text(
            """
            SELECT id FROM articles
            WHERE similarity(title, :title) >= :threshold
              AND is_active = TRUE
            ORDER BY similarity(title, :title) DESC
            LIMIT 1
            """
        )
        result = await self._session.execute(stmt, {"title": title, "threshold": threshold})
        row = result.fetchone()
        if row:
            return await self.get_by_id(row[0])
        return None

    async def url_exists(self, publication_id: UUID, url: str) -> bool:
        """Check UNIQUE(publication_id, url) before inserting."""
        stmt = select(Article.id).where(
            and_(Article.publication_id == publication_id, Article.url == url)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def mark_as_duplicate(self, duplicate_id: UUID, original_id: UUID) -> None:
        """Mark article as inactive duplicate, pointing to the original."""
        stmt = (
            update(Article)
            .where(Article.id == duplicate_id)
            .values(is_active=False, is_duplicate=True, duplicate_of_id=original_id)
        )
        await self._session.execute(stmt)
