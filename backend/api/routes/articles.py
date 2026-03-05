"""
Articles API route controller.
SRP: ONLY handles HTTP request/response for article endpoints.
"""
from fastapi import APIRouter, Query
from typing import Optional
import uuid

from core.dependencies import ArticleRepo
from models.schemas import ArticleFilters, ArticleListOut, ArticleOut

router = APIRouter(prefix="/articles", tags=["Articles"])


@router.get("", response_model=ArticleListOut, summary="List articles with filters")
async def list_articles(
    repo: ArticleRepo,
    edition_id: Optional[uuid.UUID] = Query(None, description="Filter by edition"),
    section_id: Optional[uuid.UUID] = Query(None, description="Filter by section"),
    tag: Optional[str] = Query(None, description="Filter by tag slug"),
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> ArticleListOut:
    from datetime import date as date_type
    parsed_date = None
    if date:
        try:
            parsed_date = date_type.fromisoformat(date)
        except ValueError:
            pass

    offset = (page - 1) * size
    items, total = await repo.get_filtered(
        edition_id=edition_id,
        section_id=section_id,
        tag=tag,
        published_date=parsed_date,
        limit=size,
        offset=offset,
    )
    return ArticleListOut(total=total, page=page, size=size, items=items)


@router.get("/{article_id}", response_model=ArticleOut, summary="Get article by ID")
async def get_article(article_id: uuid.UUID, repo: ArticleRepo) -> ArticleOut:
    from fastapi import HTTPException, status
    article = await repo.get_by_id(article_id)
    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return article
