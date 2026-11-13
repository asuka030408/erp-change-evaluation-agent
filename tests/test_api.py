from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from erp_change_agent.api import create_app
from erp_change_agent.auth import TokenStore
from erp_change_agent.models import Assessment, Finding


class FakeModel:
    def __init__(self):
        self.calls = 0
        self.last_usage = {"input_tokens": 1, "output_tokens": 1}

    def decide(self, request, tenant_id, evidence, catalog, history, approved_memory, feedback, can_investigate):
        self.calls += 1
        return {"action": "draft", "reason": "enough", "draft": {
            "preliminary_decision": "需人工审阅",
            "findings": [{"claim": "待核对依据", "citations": [evidence[0].section.section_id], "kind": "uncertain"}],
            "questions": [], "approvals_needed": ["项目负责人"], "limitations": []}}

    def check_support(self, assessment, evidence):
        return [{"supported": True, "reason": "test"} for _ in assessment.findings]


def _setup(tmp_path):
    root = Path(__file__).resolve().parents[1]
    fake = FakeModel()
    sources = tmp_path / "data" / "sources"
    shutil.copytree(root / "materials" / "sources", sources)
    app = create_app(tmp_path, sources_root=sources, engine_factory=lambda: fake)
    store = TokenStore(tmp_path / ".data" / "api_tokens.sqlite")
    try:
        analyst = store.issue("TENANT-XH", "analyst", "分析员")
        reviewer = store.issue("TENANT-XH", "reviewer", "审核员")
        other = store.issue("TENANT-TH", "analyst", "其他客户分析员")
    finally:
        store.close()
    return TestClient(app), fake, analyst, reviewer, other


def test_api_binds_tenant_to_token_and_enforces_review_role(tmp_path):
    client, fake, analyst, reviewer, other = _setup(tmp_path)
    assert client.post("/assessments", json={"request": "调整审批阈值"}).status_code == 401
    response = client.post("/assessments", json={"request": "调整审批阈值"}, headers={"X-ERP-Token": analyst})
    assert response.status_code == 201, response.text
    assert fake.calls == 1
    run_id = response.json()["run_id"]
    assert client.get(f"/assessments/{run_id}", headers={"X-ERP-Token": other}).status_code == 404
    assert client.get(f"/assessments/{run_id}/audit", headers={"X-ERP-Token": other}).status_code == 404
    assert client.post(f"/assessments/{run_id}/review", json={"decision": "approve"},
                       headers={"X-ERP-Token": analyst}).status_code == 403
    reviewed = client.post(f"/assessments/{run_id}/review", json={"decision": "approve"},
                           headers={"X-ERP-Token": reviewer})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review"]["reviewer"] == "审核员"
    assert fake.calls == 1


def test_api_upload_scopes_document_to_authenticated_tenant(tmp_path):
    client, _, analyst, reviewer, other = _setup(tmp_path)
    form = {"document_id": "CONTRACT-API-001", "document_type": "合同",
            "status": "双方已签署", "document_date": "2026-11-13"}
    files = {"file": ("contract.txt", "采购审批须经财务复核。".encode("utf-8"), "text/plain")}
    assert client.post("/documents", data=form, files=files,
                       headers={"X-ERP-Token": reviewer}).status_code == 403
    uploaded = client.post("/documents", data=form, files=files,
                           headers={"X-ERP-Token": analyst})
    assert uploaded.status_code == 201, uploaded.text
    assert (tmp_path / "data" / "sources" / "TENANT-XH" / "合同" / "CONTRACT-API-001.md").exists()
    assert not (tmp_path / "data" / "sources" / "TENANT-TH" / "合同" / "CONTRACT-API-001.md").exists()
