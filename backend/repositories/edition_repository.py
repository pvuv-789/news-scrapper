"""
Edition Repository — Data Access Layer for editions.
SRP: ONLY handles database queries related to editions.
"""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import Edition
from repositories.base_repository import BaseRepository


class EditionRepository(BaseRepository[Edition]):

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_id(self, record_id: UUID) -> Optional[Edition]:
        result = await self._session.execute(
            select(Edition).where(Edition.id == record_id)
        )
        return result.scalar_one_or_none()

    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Edition]:
        result = await self._session.execute(
            select(Edition).where(Edition.is_active == True).limit(limit).offset(offset)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_active_by_publication(self, publication_id: UUID) -> List[Edition]:
        result = await self._session.execute(
            select(Edition).where(
                Edition.publication_id == publication_id,
                Edition.is_active == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def create(self, obj: Edition) -> Edition:
        self._session.add(obj)
        await self._session.flush()
        await self._session.refresh(obj)
        return obj

    async def delete(self, record_id: UUID) -> bool:
        edition = await self.get_by_id(record_id)
        if edition:
            await self._session.delete(edition)
            return True
        return False
