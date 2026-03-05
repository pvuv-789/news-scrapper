"""Seed test articles to verify the frontend displays correctly."""
import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from core.database import AsyncSessionFactory
from models.db_models import Article, Edition, Publication

PUBLICATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

TEST_ARTICLES = [
    {"title": "Chennai sees heavy rainfall today", "summary": "Heavy rains lash Chennai causing waterlogging in low-lying areas.", "page_number": 1},
    {"title": "Tamil Nadu budget session begins", "summary": "The state legislature opens its budget session with key announcements expected.", "page_number": 1},
    {"title": "IPL 2026: CSK wins opening match", "summary": "Chennai Super Kings defeat Mumbai Indians in a thrilling last-over finish.", "page_number": 3},
    {"title": "New metro line inaugurated in Chennai", "summary": "Phase 2 of Chennai metro opens connecting airport to central station.", "page_number": 2},
    {"title": "Rising fuel prices hit commuters hard", "summary": "Petrol prices cross Rs 100 mark again causing hardship for daily commuters.", "page_number": 2},
]

async def seed():
    async with AsyncSessionFactory() as session:
        # Get first active edition
        result = await session.execute(
            select(Edition).where(Edition.publication_id == PUBLICATION_ID, Edition.is_active == True)
        )
        edition = result.scalars().first()
        if not edition:
            print("No editions found. Run seed.py first.")
            return

        for i, data in enumerate(TEST_ARTICLES):
            article = Article(
                publication_id=PUBLICATION_ID,
                edition_id=edition.id,
                title=data["title"],
                summary=data["summary"],
                url=f"https://epaper.dailythanthi.com/test/{i+1}",
                page_number=data["page_number"],
                published_at=datetime.now(timezone.utc),
                is_active=True,
                is_duplicate=False,
            )
            session.add(article)
            print(f"  Added: {data['title']}")

        await session.commit()
        print("\n✅ Test articles seeded successfully!")

if __name__ == "__main__":
    asyncio.run(seed())
