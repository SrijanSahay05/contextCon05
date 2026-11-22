from fastapi import FastAPI

from app.core.config import get_settings
from app.errors import register_error_handlers
from app.routes import (
    candidates,
    dd,
    documents,
    funds,
    gmail,
    investors,
    memos,
    outreach,
    runs,
    scoring_profiles,
    searches,
    sources,
    theses,
    watch,
    webhooks,
)
from app.routes.health import router as health_router

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)
register_error_handlers(app)

app.include_router(health_router)
for module in (
    investors, funds, theses, scoring_profiles, searches, candidates, outreach, memos, dd,
    documents, sources, runs, watch, webhooks, gmail,
):
    app.include_router(module.router)
