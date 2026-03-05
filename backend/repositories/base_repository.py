"""
Abstract Base Repository — defines common CRUD interface.
OCP + DIP: consumers depend on this abstraction; concrete repos implement it.
"""
from abc import ABC, abstractmethod
from typing import Generic, List, Optional, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(ABC, Generic[ModelType]):
    """
    Abstract repository providing a consistent interface for all data access.
    Concrete implementations must supply the model class and implement all methods.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @abstractmethod
    async def get_by_id(self, record_id: UUID) -> Optional[ModelType]:
        """Fetch a single record by primary key."""
        ...

    @abstractmethod
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[ModelType]:
        """Fetch a list of records with pagination."""
        ...

    @abstractmethod
    async def create(self, obj: ModelType) -> ModelType:
        """Persist a new record and return it."""
        ...

    @abstractmethod
    async def delete(self, record_id: UUID) -> bool:
        """Delete a record by primary key. Returns True if deleted."""
        ...
