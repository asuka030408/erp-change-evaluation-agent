"""The model's read tool must not cross the tenant evidence boundary."""

import pytest

from erp_change_agent.tools.evidence import execute_evidence_action


def test_read_tool_rejects_another_tenants_section(corpus):
    other_tenant_id = corpus.load("TENANT-TH")[0].section_id
    state = {
        "tenant_id": "TENANT-XH",
        "evidence": [],
        "decision": {"action": "read", "reason": "check source", "section_ids": [other_tenant_id]},
    }

    with pytest.raises(ValueError, match="unknown tenant section"):
        execute_evidence_action(state, corpus, 32000)

    assert state["evidence"] == []
