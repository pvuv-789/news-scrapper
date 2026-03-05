"""Run the scraper directly without Celery."""
import asyncio
import uuid
from datetime import date

from services.scraping_orchestrator import ScrapingOrchestrator

PUBLICATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

async def main():
    print(f"Starting scrape for {date.today()}...")
    orchestrator = ScrapingOrchestrator(publication_id=PUBLICATION_ID)
    await orchestrator.run(date.today())
    print("Scrape complete!")

if __name__ == "__main__":
    asyncio.run(main())
