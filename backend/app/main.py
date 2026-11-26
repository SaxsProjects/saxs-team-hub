"""SaxsProjects Team Hub API."""

import hmac
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .jobs import run_daily
from .pdf import load_signature
from .routers import auth, avatars, finance, me, offers, overview, pages, people, projects, task_orders

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    settings.check_production_ready()
    if settings.signature_configured:
        load_signature()  # fail at startup, not on the first signed document, if the image is unusable

    app = FastAPI(
        title=f"{settings.company_name} Team Hub API",
        version="1.0.0",
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,  # the sign-in renewal cookie (see app/sessions.py)
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        is_pdf = response.headers.get("content-type", "").startswith("application/pdf")
        if not request.url.path.startswith("/docs") and not is_pdf:
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response

    for module in (auth, people, offers, projects, task_orders, finance, me, overview, avatars):
        app.include_router(module.router)
    app.include_router(offers.public)
    app.include_router(pages.router)

    @app.get("/api/health", tags=["system"])
    def health(db: Session = Depends(get_db)):
        try:
            db.execute(text("SELECT 1"))
            database = True
        except Exception:  # noqa: BLE001 - report, don't crash the probe
            database = False
        body = {
            "ok": database,
            "database": database,
            "email": settings.email_configured,
            "signature": settings.signature_configured,
        }
        # 503 when the database is unreachable, so the host's health check notices and restarts.
        return JSONResponse(body, status_code=200 if database else 503)

    @app.post("/api/jobs/daily", tags=["system"])
    def daily_jobs(x_jobs_token: str = Header(default=""), db: Session = Depends(get_db)):
        if not settings.jobs_token or not hmac.compare_digest(x_jobs_token, settings.jobs_token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid jobs token")
        return run_daily(db)

    return app


app = create_app()
