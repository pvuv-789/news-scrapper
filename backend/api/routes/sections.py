"""
Sections API route controller.
SRP: ONLY handles HTTP request/response for section endpoints.
"""
from typing import List
from fastapi import APIRouter
from sqlalchemy import select
from core.dependencies import DbSession
from models.db_models import Section
from models.schemas import SectionOut

router = APIRouter(prefix="/sections", tags=["Sections"])


@router.get("", response_model=List[SectionOut], summary="List all sections")
async def list_sections(db: DbSession) -> List[SectionOut]:
    result = await db.execute(select(Section).order_by(Section.name))
    return list(result.scalars().all())
