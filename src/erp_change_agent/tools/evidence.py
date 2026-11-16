"""The Agent's two read-only tools: search tenant evidence and read section IDs.

This module applies a model-selected action. The workflow owns the decision to
call a tool; this module enforces tenant scope and the evidence-size limit.
"""

from ..rag.corpus import MarkdownCorpus
from ..rag.retrieval import HybridRetriever
from ..schemas import Evidence, Section


def execute_evidence_action(state: dict, corpus: MarkdownCorpus, max_evidence_chars: int) -> dict:
    """Run search/read and return only the state fields changed by that action."""
    action = state["decision"]
    sections = corpus.load(state["tenant_id"])
    by_id = {s.section_id: s for s in sections}
    current = [Evidence(Section(**item["section"]), item["score"]) for item in state["evidence"]]
    have = {e.section.section_id for e in current}
    ids: list[str]
    if action["action"] == "search":
        query = action.get("query", "").strip()[:300]
        if not query:
            raise ValueError("Search query is required")
        ids = [e.section.section_id for e in HybridRetriever(sections).search(query, limit=8)]
    elif action["action"] == "read":
        ids = action.get("section_ids", [])[:8]
        if not ids or any(i not in by_id for i in ids):
            raise ValueError("Read requested unknown tenant section")
    else:
        raise ValueError("Unsupported tool action")
    size = sum(len(e.section.text) for e in current)
    added = []
    for section_id in ids:
        if section_id in have:
            continue
        section = by_id[section_id]
        if size + len(section.text) > max_evidence_chars:
            continue
        current.append(Evidence(section, 1.0))
        have.add(section_id)
        added.append(section_id)
        size += len(section.text)
    history = state.get("history", []) + [dict(action=action["action"], reason=action["reason"],
                                               section_ids=ids, added=added)]
    return {"evidence": [e.to_dict() for e in current], "history": history,
            "tool_actions": state.get("tool_actions", 0) + 1,
            "feedback": ["该次工具操作没有新增原文；请用现有证据起草或选择不同段落。"] if not added else []}
