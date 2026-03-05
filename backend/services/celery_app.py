"""
Celery application with Celery Beat schedule for daily scraping.
SRP: ONLY handles task queue configuration and task definitions.
"""
import asyncio
import uuid
from datetime import date

from celery import Celery
from celery.schedules import crontab

from core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "escrapper",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    # Celery Beat schedule — daily 6:00 AM IST
    beat_schedule={
        "daily-thanthi-scrape": {
            "task": "services.celery_app.run_daily_scrape",
            "schedule": crontab(
                hour=_settings.scrape_cron_hour,
                minute=_settings.scrape_cron_minute,
            ),
        },
    },
)


@celery_app.task(name="services.celery_app.run_daily_scrape", bind=True, max_retries=3)
def run_daily_scrape(self, publication_id: str | None = None, target_date_str: str | None = None):
    """
    Celery task to trigger the ScrapingOrchestrator for a given publication and date.
    Runs the async orchestrator in a new event loop.
    """
    from services.scraping_orchestrator import ScrapingOrchestrator

    # Default: Daily Thanthi publication ID from env or seed
    pub_id = uuid.UUID(publication_id) if publication_id else None
    if pub_id is None:
        raise ValueError("publication_id required. Run the seed script to get the UUID.")

    target = date.fromisoformat(target_date_str) if target_date_str else date.today()

    orchestrator = ScrapingOrchestrator(publication_id=pub_id)

    try:
        asyncio.run(orchestrator.run(target))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
