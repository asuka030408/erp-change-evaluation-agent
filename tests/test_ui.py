from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from erp_change_agent.ui import create_ui_app


class FakeEngine:
    """Exercise the real local UI and workflow without a paid model request."""

    def __init__(self):
        self.total_usage = {"input_tokens": 1, "output_tokens": 1, "calls": 1}

    def decide(self, request, tenant_id, evidence, catalog, history, approved_memory,
               feedback, can_investigate):
        return {"action": "draft", "reason": "enough", "draft": {
            "preliminary_decision": "待人工审阅",
            "findings": [{"claim": "需核对合同", "citations": [evidence[0].section.section_id],
                          "kind": "uncertain"}],
            "questions": [], "approvals_needed": ["业务负责人"], "limitations": [],
        }}

    def check_support(self, assessment, evidence):
        return {"decision_aligned": True, "decision_reason": "test",
                "checks": [{"supported": True, "reason": "test"} for _ in assessment.findings]}


def test_local_ui_opens_without_login_and_runs_review(tmp_path):
    source = Path(__file__).resolve().parents[1] / "materials" / "sources"
    demo = tmp_path / "materials" / "sources"
    shutil.copytree(source, demo)
    client = TestClient(create_ui_app(tmp_path, sources_root=demo, engine_factory=FakeEngine))
    assert client.get("/").status_code == 200
    assert "ERP 变更评估工作台" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200

    bootstrap = client.get("/ui/bootstrap").json()
    assert bootstrap["mode"] == "demo"
    assert bootstrap["tenants"] == ["TENANT-TH", "TENANT-XH"]
    body = {"tenant_id": "TENANT-XH", "request": "评估采购审批规则"}
    assert client.post("/ui/assessments", json=body).status_code == 403
    headers = {"X-Local-UI-Token": bootstrap["write_token"]}
    response = client.post("/ui/assessments", json=body, headers=headers)
    assert response.status_code == 201, response.text
    run_id = response.json()["run_id"]
    assert response.json()["status"] == "awaiting_review"
    assert client.get(f"/ui/assessments/{run_id}", params={"tenant_id": "TENANT-TH"}).status_code == 404

    review = {"tenant_id": "TENANT-XH", "decision": "approve", "reviewer": "本机审阅人"}
    assert client.post(f"/ui/assessments/{run_id}/review", json=review).status_code == 403
    reviewed = client.post(f"/ui/assessments/{run_id}/review", json=review, headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    saved = client.get(f"/ui/assessments/{run_id}", params={"tenant_id": "TENANT-XH"}).json()
    assert saved["status"] == "reviewed"
    assert saved["review"]["reviewer"] == "本机审阅人"
    assert (tmp_path / ".data" / "reports" / "TENANT-XH" / f"{run_id}.md").exists()
