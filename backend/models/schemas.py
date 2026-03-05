"""
Pydantic response and request schemas for all FastAPI routes.
SRP: this module ONLY defines data transfer objects and validation shapes.
"""
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


# ── Shared Config ──────────────────────────────────────────────────────────────
class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Tag Schemas ────────────────────────────────────────────────────────────────
class TagOut(ORMBase):
    id: uuid.UUID
    name: str
    slug: str


# ── Section Schemas ────────────────────────────────────────────────────────────
class SectionOut(ORMBase):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str] = None


# ── Edition Schemas ────────────────────────────────────────────────────────────
class EditionOut(ORMBase):
    id: uuid.UUID
    display_name: str
    city_code: str
    is_active: bool


# ── Article Schemas ────────────────────────────────────────────────────────────
class ArticleOut(ORMBase):
    id: uuid.UUID
    title: str
    subtitle: Optional[str] = None
    byline: Optional[str] = None
    url: str
    summary: Optional[str] = None
    word_count_estimate: Optional[int] = None
    page_number: Optional[int] = None
    page_label: Optional[str] = None
    location: Optional[str] = None
    is_active: bool
    published_at: Optional[datetime] = None
    scraped_at: datetime
    edition: Optional[EditionOut] = None
    section: Optional[SectionOut] = None
    tags: List[TagOut] = Field(default_factory=list)


class ArticleListOut(ORMBase):
    total: int
    page: int
    size: int
    items: List[ArticleOut]


# ── Article Filters (Query Params) ─────────────────────────────────────────────
class ArticleFilters(BaseModel):
    edition_id: Optional[uuid.UUID] = None
    section_id: Optional[uuid.UUID] = None
    tag: Optional[str] = None
    date: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


# ── Crawl Run Schemas ──────────────────────────────────────────────────────────
class CrawlRunOut(ORMBase):
    id: uuid.UUID
    target_date: datetime
    started_at: datetime
    ended_at: Optional[datetime] = None
    status: str
    articles_scraped: int
    articles_inserted: int
    articles_deduplicated: int
    error_log: Optional[str] = None


# ── Scraped Article (Internal DTO) ─────────────────────────────────────────────
class ScrapedArticleDTO(BaseModel):
    """Internal data transfer object produced by the scraper."""
    title: str
    subtitle: Optional[str] = None
    byline: Optional[str] = None
    url: str
    page_number: Optional[int] = None
    page_label: Optional[str] = None
    location: Optional[str] = None
    raw_text: Optional[str] = None
    published_at: Optional[datetime] = None
