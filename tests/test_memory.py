import pytest

from erp_change_agent.memory import ProjectMemory


def test_memory_requires_human_promotion_and_tenant_match(tmp_path):
    memory = ProjectMemory(tmp_path / "memory.sqlite")
    try:
        fact_id = memory.propose("TENANT-XH", "10 万元以下两级审批", ["C-XH-001 §2.2"])
        assert memory.list("TENANT-XH")[0]["status"] == "candidate"
        with pytest.raises(ValueError):
            memory.review(fact_id, "TENANT-TH", "approved", "审阅人", "")
        memory.review(fact_id, "TENANT-XH", "approved", "审阅人", "核对合同")
        assert memory.list("TENANT-XH")[0]["status"] == "approved"
        assert len(memory.current_approved("TENANT-XH")) == 1
        replacement = memory.propose("TENANT-XH", "新批准规则", ["M-XH-042 §1"], supersedes_id=fact_id)
        memory.review(replacement, "TENANT-XH", "approved", "审阅人", "新决议")
        assert [item["id"] for item in memory.current_approved("TENANT-XH")] == [replacement]
        with pytest.raises(ValueError):
            memory.review(fact_id, "TENANT-XH", "approved", "审阅人", "重复")
    finally:
        memory.close()
