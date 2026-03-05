"""
Editions API route controller.
SRP: ONLY handles HTTP request/response for edition endpoints.
"""
from typing import List
from fastapi import APIRouter
from core.dependencies import EditionRepo
from models.schemas import EditionOut

router = APIRouter(prefix="/editions", tags=["Editions"])


@router.get("", response_model=List[EditionOut], summary="List all active editions")
async def list_editions(repo: EditionRepo) -> List[EditionOut]:
    return await repo.get_all()
