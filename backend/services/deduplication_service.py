"""
Deduplication Service — Article similarity detection and management.
SRP: ONLY handles deduplication logic, delegates DB access to the repository.
"""
from typing import Optional
from uuid import UUID

from core.config import get_settings
from core.logging_config import get_logger
from repositories.article_repository import ArticleRepository

logger = get_logger(__name__)


class DeduplicationService:
    """
    Checks incoming articles against existing ones using pg_trgm similarity.
    Delegates all DB reads/writes to ArticleRepository (DIP).
    """

    def __init__(self, article_repo: ArticleRepository) -> None:
        self._repo = article_repo
        self._threshold = get_settings().dedup_similarity_threshold

    async def find_original(self, title: str) -> Optional["UUID"]:
        """
        Returns the id of an existing active article that is similar to the given title,
        or None if no duplicate is found.
        """
        original = await self._repo.find_similar_by_trgm(title, self._threshold)
        if original:
            logger.info(
                "duplicate_detected",
                incoming_title=title[:60],
                original_id=str(original.id),
                threshold=self._threshold,
            )
            return original.id
        return None

    async def handle_duplicate(self, duplicate_id: UUID, original_id: UUID) -> None:
        """Delegate marking to the repository."""
        await self._repo.mark_as_duplicate(duplicate_id, original_id)
        logger.info(
            "duplicate_marked",
            duplicate_id=str(duplicate_id),
            original_id=str(original_id),
        )
