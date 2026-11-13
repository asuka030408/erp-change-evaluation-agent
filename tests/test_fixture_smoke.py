import re
from pathlib import Path

from erp_change_agent.retrieval import HybridRetriever


def test_all_thirty_fixture_requests_retrieve_only_their_tenant(corpus):
    cases_path = Path(__file__).resolve().parents[1] / "materials" / "cases" / "测试需求与预期.md"
    rows = re.findall(r"^\| (\d{2}) \| (星河(?:总部|子公司)?|天衡)：(.+?) \|", cases_path.read_text(encoding="utf-8"), re.M)
    assert len(rows) == 30
    for case_id, customer, request in rows:
        tenant = "TENANT-XH" if customer.startswith("星河") else "TENANT-TH"
        full_request = f"{customer}：{request}"
        evidence = HybridRetriever(corpus.load(tenant)).search(full_request)
        assert evidence, case_id
        assert all(item.section.tenant_id == tenant for item in evidence), case_id
