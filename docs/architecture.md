# Architecture Overview

## N-Tier Design

```
Presentation Layer  →  Controller Layer  →  Service Layer  →  DAL  →  Database
      (Vue 3)            (FastAPI)         (Python classes)  (SQLAlchemy) (PG)
```

No layer bypasses the hierarchy. Services never call FastAPI. Repositories never call Service logic.

## SOLID Compliance

| Principle | Implementation |
|---|---|
| **SRP** | `DailyThanthiScraper` only scrapes HTML; `ArticleRepository` only runs DB queries |
| **OCP** | `BaseScraper` ABC — add new publisher by subclassing only |
| **LSP** | All scrapers substitutable via `BaseScraper` interface |
| **ISP** | `BaseRepository` has narrow interface; each repo extends only what it needs |
| **DIP** | FastAPI deps inject `AsyncSession` into repos; repos injected into services |

## Data Model ERD

```
publications ──< editions ──< articles >── sections
                                 │
                            article_tags >── tags
                                 │
                            crawl_runs
```

## Async Strategy

All database I/O uses `asyncpg` + SQLAlchemy async sessions.
All scraper network calls use Playwright's async API.
Celery worker runs as separate process; scheduled by Celery Beat (6 AM IST daily).

## Deduplication

1. On each new article, `DeduplicationService` calls `ArticleRepository.find_similar()`.
2. Uses PostgreSQL `pg_trgm` similarity() function with configurable threshold (default 0.85).
3. Duplicates: original marked `is_active=TRUE`, duplicate `is_active=FALSE`.
4. UNIQUE constraint on `(publication_id, url)` enforces hard dedup at DB level.

## Retry / Resilience

`tenacity` decorates all scraper network calls:
- 3 retries max
- Exponential backoff: 2s → 4s → 8s
- Full stack trace stored in `crawl_runs.error_log` on failure
