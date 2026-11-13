"""Local, no-login browser UI for a single trusted workstation.

This app is intentionally separate from the authenticated HTTP API. The CLI
binds it to loopback only; a per-process token protects state-changing calls
from unrelated browser pages. It never exposes a production ERP write action.
"""

import os
import secrets
from pathlib import Path
from typing import Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .analyzers.base import AssessmentEngine
from .application import AssessmentApplication


WEB_DIR = Path(__file__).parent / "web"


class NewAssessment(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    request: str = Field(min_length=1, max_length=10000)


class ReviewDecision(BaseModel):
    tenant_id: str
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=10000)


def choose_sources(project_root: Path, explicit: Path | None = None) -> tuple[Path, bool]:
    """Use formal sources when present; otherwise open the bundled demo corpus."""
    root = project_root.resolve(strict=True)
    demo = root / "materials" / "sources"
    if explicit is not None:
        chosen = explicit if explicit.is_absolute() else root / explicit
        return chosen.resolve(strict=True), chosen.resolve(strict=True) == demo.resolve()
    formal = root / "data" / "sources"
    if formal.is_dir() and any(p.is_dir() for p in formal.iterdir()):
        return formal.resolve(strict=True), False
    if demo.is_dir():
        return demo.resolve(strict=True), True
    return formal, False


def create_ui_app(
    project_root: Path,
    *,
    sources_root: Path | None = None,
    engine_factory: Callable[[], AssessmentEngine] | None = None,
) -> FastAPI:
    chosen, demo = choose_sources(project_root, sources_root)
    service = AssessmentApplication(project_root, chosen)
    page_token = secrets.token_urlsafe(32)
    app = FastAPI(title="ERP 变更评估 · 本机界面", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

    def local_write(x_local_ui_token: str | None = Header(default=None)) -> None:
        if not x_local_ui_token or not secrets.compare_digest(x_local_ui_token, page_token):
            raise HTTPException(status_code=403, detail="请从本机页面发起操作")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", media_type="text/html")

    @app.get("/ui/bootstrap")
    def bootstrap() -> dict:
        return {
            "tenants": service.corpus.tenants(),
            "mode": "demo" if demo else "formal",
            "source_path": str(service.sources_root),
            "model_ready": bool(os.getenv("DEEPSEEK_API_KEY")) or engine_factory is not None,
            "write_token": page_token,
        }

    @app.post("/ui/assessments", status_code=201, dependencies=[Depends(local_write)])
    def assess(body: NewAssessment) -> dict:
        if body.tenant_id not in service.corpus.tenants():
            raise HTTPException(status_code=422, detail="请选择已有资料的租户")
        try:
            engine = engine_factory() if engine_factory else None
            result = service.assess(body.tenant_id, body.request, engine=engine)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"run_id": result.run_id, "tenant_id": body.tenant_id,
                "report": result.report, "status": "awaiting_review",
                "model_usage": result.model_usage}

    @app.get("/ui/assessments/{run_id}")
    def get_assessment(run_id: str, tenant_id: str) -> dict:
        try:
            saved = service.get(run_id, tenant_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到该租户的报告") from exc
        state = saved["values"]
        return {"run_id": run_id, "tenant_id": tenant_id, "report": state.get("report"),
                "status": "awaiting_review" if saved["next"] else "reviewed",
                "review": state.get("review")}

    @app.post("/ui/assessments/{run_id}/review", dependencies=[Depends(local_write)])
    def review(run_id: str, body: ReviewDecision) -> dict:
        try:
            result = service.review(run_id, body.tenant_id, body.decision,
                                    body.reviewer, body.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到该租户的报告") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run_id": run_id, "review": result}

    return app
