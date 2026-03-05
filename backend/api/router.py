"""
Central API router — aggregates all sub-routers under /api prefix.
DRY: One place to register all routes.
"""
from fastapi import APIRouter

from api.routes.articles import router as articles_router
from api.routes.editions import router as editions_router
from api.routes.scrape import router as scrape_router
from api.routes.sections import router as sections_router
from api.routes.tags import router as tags_router

api_router = APIRouter(prefix="/api")

api_router.include_router(articles_router)
api_router.include_router(editions_router)
api_router.include_router(sections_router)
api_router.include_router(tags_router)
api_router.include_router(scrape_router)
