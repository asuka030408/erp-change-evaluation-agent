"""Tenant-bound HTTP adapter for document import, assessment, and report review."""

import tempfile
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .analyzers.base import AssessmentEngine
from .application import AssessmentApplication
from .auth import Identity, TokenStore
from .ingest import EXTENSIONS


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class AssessmentRequest(BaseModel):
    request: str = Field(min_length=1, max_length=10000)


class ReviewRequest(BaseModel):
    decision: str
    note: str = Field(default="", max_length=10000)


def create_app(
    project_root: Path,
    *,
    sources_root: Path | None = None,
    engine_factory: Callable[[], AssessmentEngine] | None = None,
) -> FastAPI:
    service = AssessmentApplication(project_root, sources_root)
    token_db = service.data_dir / "api_tokens.sqlite"
    app = FastAPI(title="ERP Change Assessment", version="0.1.0")

    def identity(x_erp_token: str | None = Header(default=None)) -> Identity:
        if not x_erp_token:
            raise HTTPException(status_code=401, detail="Missing API token")
        store = TokenStore(token_db)
        try:
            found = store.authenticate(x_erp_token)
        finally:
            store.close()
        if found is None:
            raise HTTPException(status_code=401, detail="Invalid API token")
        return found

    def require_role(identity: Identity, allowed: set[str]) -> None:
        if identity.role not in allowed:
            raise HTTPException(status_code=403, detail="Role not authorized")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/documents", status_code=201)
    def upload_document(
        file: UploadFile = File(...),
        document_id: str = Form(...),
        document_type: str = Form(...),
        status: str = Form(...),
        document_date: str = Form(...),
        supersedes: str | None = Form(default=None),
        actor: Identity = Depends(identity),
    ) -> dict:
        require_role(actor, {"analyst", "admin"})
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in EXTENSIONS:
            raise HTTPException(status_code=422, detail="Unsupported document extension")
        upload_dir = service.data_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=upload_dir, suffix=suffix, delete=False) as temp:
                temp_path = Path(temp.name)
                size = 0
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="Document exceeds 10 MB")
                    temp.write(chunk)
            try:
                result = service.ingest(
                    temp_path,
                    tenant_id=actor.tenant_id,
                    document_id=document_id,
                    document_type=document_type,
                    status=status,
                    document_date=document_date,
                    supersedes=supersedes,
                )
            except (ValueError, FileExistsError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {
                "document_id": result.document_id,
                "sections": result.sections,
                "sha256": result.sha256,
            }
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            file.file.close()

    @app.post("/assessments", status_code=201)
    def assess(body: AssessmentRequest, actor: Identity = Depends(identity)) -> dict:
        require_role(actor, {"analyst", "admin"})
        try:
            engine = engine_factory() if engine_factory else None
            result = service.assess(actor.tenant_id, body.request, engine=engine)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "run_id": result.run_id,
            "status": "awaiting_review",
            "report": result.report,
            "model_usage": result.model_usage,
        }

    @app.get("/assessments/{run_id}")
    def get_assessment(run_id: str, actor: Identity = Depends(identity)) -> dict:
        try:
            result = service.get(run_id, actor.tenant_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Assessment not found") from exc
        state = result["values"]
        return {
            "run_id": run_id,
            "status": "awaiting_review" if result["next"] else "reviewed",
            "report": state.get("report"),
            "review": state.get("review"),
        }

    @app.post("/assessments/{run_id}/review")
    def review(run_id: str, body: ReviewRequest, actor: Identity = Depends(identity)) -> dict:
        require_role(actor, {"reviewer", "admin"})
        if body.decision not in {"approve", "reject"}:
            raise HTTPException(status_code=422, detail="Decision must be approve or reject")
        try:
            result = service.review(run_id, actor.tenant_id, body.decision, actor.name, body.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Assessment not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run_id": run_id, "review": result}

    @app.get("/assessments/{run_id}/audit")
    def audit(run_id: str, actor: Identity = Depends(identity)) -> dict:
        try:
            events = service.audit_events(run_id, actor.tenant_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Assessment not found") from exc
        return {"run_id": run_id, "events": events}

    return app
