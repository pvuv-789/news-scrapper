"""
SQLAlchemy ORM models.
Maps to the PostgreSQL schema defined in the BRD.
SRP: this module ONLY defines DB table structure — no business logic.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Publications ───────────────────────────────────────────────────────────────
class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    paper_type: Mapped[str] = mapped_column(String(100), nullable=False)  # 'epaper', 'web'
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    editions: Mapped[list["Edition"]] = relationship("Edition", back_populates="publication")
    articles: Mapped[list["Article"]] = relationship("Article", back_populates="publication")
    crawl_runs: Mapped[list["CrawlRun"]] = relationship("CrawlRun", back_populates="publication")


# ── Editions ───────────────────────────────────────────────────────────────────
class Edition(Base):
    __tablename__ = "editions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publications.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    city_code: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    publication: Mapped["Publication"] = relationship("Publication", back_populates="editions")
    articles: Mapped[list["Article"]] = relationship("Article", back_populates="edition")

    __table_args__ = (
        UniqueConstraint("publication_id", "city_code", name="uq_edition_pub_city"),
    )


# ── Sections ───────────────────────────────────────────────────────────────────
class Section(Base):
    __tablename__ = "sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    articles: Mapped[list["Article"]] = relationship("Article", back_populates="section")


# ── Articles ───────────────────────────────────────────────────────────────────
class Article(Base):
    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publications.id", ondelete="CASCADE"), nullable=False
    )
    edition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editions.id", ondelete="SET NULL"), nullable=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
    )

    # Content
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    byline: Mapped[str | None] = mapped_column(String(512), nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Page metadata
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Status flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id", ondelete="SET NULL"), nullable=True
    )

    # Timestamps
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    # Relationships
    publication: Mapped["Publication"] = relationship("Publication", back_populates="articles")
    edition: Mapped["Edition | None"] = relationship("Edition", back_populates="articles")
    section: Mapped["Section | None"] = relationship("Section", back_populates="articles")
    tags: Mapped[list["Tag"]] = relationship(
        "Tag", secondary="article_tags", back_populates="articles"
    )
    duplicate_of: Mapped["Article | None"] = relationship("Article", remote_side="Article.id")

    __table_args__ = (
        UniqueConstraint("publication_id", "url", name="uq_article_pub_url"),
        Index("ix_article_published_at", "published_at"),
        Index("ix_article_edition_id", "edition_id"),
        Index("ix_article_section_id", "section_id"),
        Index("ix_article_is_active", "is_active"),
    )


# ── Tags ───────────────────────────────────────────────────────────────────────
class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    articles: Mapped[list["Article"]] = relationship(
        "Article", secondary="article_tags", back_populates="tags"
    )


# ── Article Tags (Join Table) ──────────────────────────────────────────────────
class ArticleTag(Base):
    __tablename__ = "article_tags"

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


# ── Crawl Runs ─────────────────────────────────────────────────────────────────
class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publications.id", ondelete="CASCADE"), nullable=False
    )

    target_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="running"
    )  # running | success | failed
    articles_scraped: Mapped[int] = mapped_column(Integer, default=0)
    articles_inserted: Mapped[int] = mapped_column(Integer, default=0)
    articles_deduplicated: Mapped[int] = mapped_column(Integer, default=0)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    publication: Mapped["Publication"] = relationship("Publication", back_populates="crawl_runs")

    __table_args__ = (Index("ix_crawl_run_publication_id", "publication_id"),)
