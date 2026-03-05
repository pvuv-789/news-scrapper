"""
Tags API route controller.
SRP: ONLY handles HTTP request/response for tag endpoints.
"""
from typing import List
import uuid
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from core.dependencies import ArticleRepo, DbSession
from models.db_models import Tag
from models.schemas import ArticleListOut, TagOut

router = APIRouter(prefix="/tags", tags=["Tags"])


@router.get("", response_model=List[TagOut], summary="List all tags")
async def list_tags(db: DbSession) -> List[TagOut]:
    result = await db.execute(select(Tag).order_by(Tag.name))
    return list(result.scalars().all())


@router.get("/{tag_slug}/articles", response_model=ArticleListOut, summary="Articles by tag slug")
async def articles_by_tag(
    tag_slug: str,
    repo: ArticleRepo,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> ArticleListOut:
    offset = (page - 1) * size
    items, total = await repo.get_filtered(tag=tag_slug, limit=size, offset=offset)
    return ArticleListOut(total=total, page=page, size=size, items=items)
