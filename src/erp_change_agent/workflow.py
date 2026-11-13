"""Model-directed, bounded read-only investigation with a human review gate."""
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from .analyzers.base import AssessmentEngine
from .context import select_context
from .corpus import MarkdownCorpus
from .models import Assessment, Evidence, Finding, Section
from .report import render_report
from .retrieval import HybridRetriever
from .validation import EvidenceValidationError, deployment_scope_missing, validate_assessment

MAX_MODEL_CALLS = 7
MAX_TOOL_ACTIONS = 3
MAX_INPUT_TOKENS = 45000
MAX_EVIDENCE_CHARS = 32000

class WorkflowState(TypedDict, total=False):
    run_id: str
    tenant_id: str
    request: str
    analysis_mode: str
    evidence: list[dict]
    catalog: list[dict]
    context_mode: str
    omitted_sections: int
    approved_memory: list[dict]
    assessment: dict
    verification: dict
    support_retry: int
    analysis_round: int
    tool_actions: int
    history: list[dict]
    feedback: list[str]
    decision: dict
    report: str
    review: dict

def _evidence(data: list[dict]) -> list[Evidence]:
    return [Evidence(Section(**item["section"]), item["score"]) for item in data]

def _assessment(data: dict, state: WorkflowState) -> Assessment:
    return Assessment(state["request"], state["tenant_id"], data["preliminary_decision"],
                      [Finding(**item) for item in data["findings"]], data["questions"],
                      data["approvals_needed"], data.get("limitations", []))

def build_graph(corpus: MarkdownCorpus, engine: AssessmentEngine, checkpointer):
    def gather(state: WorkflowState) -> dict:
        sections = corpus.load(state["tenant_id"])
        selection = select_context(sections, state["request"])
        valid_ids = {s.section_id for s in sections}
        memory = [m for m in state.get("approved_memory", [])
                  if m.get("tenant_id") == state["tenant_id"] and set(m.get("citations", [])) <= valid_ids]
        return {"evidence": [e.to_dict() for e in selection.evidence],
                "catalog": [dict(section_id=s.section_id, doc_id=s.doc_id, title=s.title,
                                 date=s.date, status=s.status, document_type=s.document_type)
                            for s in sections],
                "context_mode": selection.mode, "omitted_sections": selection.omitted_sections,
                "approved_memory": memory[:20], "analysis_round": 0,
                "tool_actions": 0, "history": [], "feedback": [], "support_retry": 0}

    def decide(state: WorkflowState) -> dict:
        used_calls = getattr(engine, "total_usage", {}).get("calls", state.get("analysis_round", 0))
        if used_calls >= MAX_MODEL_CALLS - 1:
            raise RuntimeError("Model call budget exhausted before valid assessment")
        usage = getattr(engine, "total_usage", {})
        if usage.get("input_tokens", 0) >= MAX_INPUT_TOKENS:
            raise RuntimeError("Input token budget exhausted")
        can_investigate = state.get("tool_actions", 0) < MAX_TOOL_ACTIONS and state.get("analysis_round", 0) < MAX_MODEL_CALLS - 3
        decision = engine.decide(state["request"], state["tenant_id"],
                                 _evidence(state["evidence"]), state["catalog"],
                                 state.get("history", []), state.get("approved_memory", []),
                                 state.get("feedback", []), can_investigate)
        if decision["action"] != "draft" and not can_investigate:
            raise RuntimeError("Investigation budget exhausted without a draft")
        result = {"decision": decision, "analysis_round": state.get("analysis_round", 0) + 1}
        if decision["action"] == "draft":
            result["assessment"] = _assessment(decision["draft"], state).to_dict()
        return result

    def route_decision(state: WorkflowState) -> str:
        return "verify" if state["decision"]["action"] == "draft" else "tool"

    def tool(state: WorkflowState) -> dict:
        action = state["decision"]
        sections = corpus.load(state["tenant_id"])
        by_id = {s.section_id: s for s in sections}
        current = _evidence(state["evidence"])
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
            if size + len(section.text) > MAX_EVIDENCE_CHARS:
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

    def verify(state: WorkflowState) -> dict:
        evidence = _evidence(state["evidence"])
        assessment = _assessment(state["assessment"], state)
        try:
            validate_assessment(assessment, evidence)
        except EvidenceValidationError as exc:
            if state["analysis_round"] >= MAX_MODEL_CALLS - 2:
                raise RuntimeError("Citation validation failed within model budget") from exc
            return {"verification": {"passed": False, "issues": [str(exc)]}, "feedback": [str(exc)]}
        if getattr(engine, "check_support", None) is None:
            checks = [{"supported": True, "reason": "test engine; manual review required"} for _ in assessment.findings]
            decision_aligned, decision_reason = True, "manual review required"
        else:
            if getattr(engine, "total_usage", {}).get("calls", 0) >= MAX_MODEL_CALLS:
                raise RuntimeError("Model call budget exhausted before citation support check")
            if getattr(engine, "total_usage", {}).get("input_tokens", 0) >= MAX_INPUT_TOKENS:
                raise RuntimeError("Input token budget exhausted before citation support check")
            support_result = engine.check_support(assessment, evidence)
            if isinstance(support_result, list):
                checks = support_result
                decision_aligned, decision_reason = True, "test engine"
            else:
                checks = support_result["checks"]
                decision_aligned = support_result["decision_aligned"]
                decision_reason = support_result["decision_reason"]
        issues = [f"Finding {i + 1}: {c['reason']}" for i, c in enumerate(checks) if not c["supported"]]
        if not decision_aligned:
            issues.insert(0, "Preliminary decision: " + decision_reason)
        if issues and state["analysis_round"] < MAX_MODEL_CALLS - 2 and state.get("support_retry", 0) == 0:
            return {"verification": {"passed": False, "issues": issues, "checks": checks},
                    "feedback": issues, "support_retry": 1}
        if issues:
            if not decision_aligned:
                assessment.preliminary_decision = (
                    "本次具体变更范围未确认，不能依据现有资料批准生产部署。"
                    "请先明确变更对象，并分别取得适用的业务、合同及上线批准。"
                )
                assessment.questions.append("本次拟部署的具体变更对象、范围和变更单编号是什么？")
            for i, check in enumerate(checks):
                if not check["supported"]:
                    assessment.findings[i].claim = "未确认：" + assessment.findings[i].claim
                    assessment.findings[i].kind = "uncertain"
                    assessment.questions.append("请人工核对：" + check["reason"])
            assessment.limitations.append("部分结论的原文支持未通过模型核对，已标记未确认；审阅人须核对原文。")
        if deployment_scope_missing(state["request"]):
            assessment.preliminary_decision = (
                "本次拟部署的具体变更对象和范围未确认，现有的业务负责人同意不足以直接授权生产部署。"
                "请先明确变更内容，并核对适用的合同、业务规则、测试、回滚及上线审批要求。"
            )
            question = "本次拟部署的具体变更对象、范围和变更单编号是什么？"
            if question not in assessment.questions:
                assessment.questions.append(question)
        return {"assessment": assessment.to_dict(),
                "verification": {"passed": True, "issues": issues, "checks": checks}, "feedback": []}

    def route_verify(state: WorkflowState) -> str:
        return "render" if state["verification"]["passed"] else "decide"

    def render(state: WorkflowState) -> dict:
        return {"report": render_report(_assessment(state["assessment"], state),
                                        _evidence(state["evidence"]), state["run_id"],
                                        state.get("analysis_mode", "unknown"))}

    def human_review(state: WorkflowState) -> dict:
        result = interrupt({"run_id": state["run_id"], "tenant_id": state["tenant_id"],
                            "message": "审阅报告；通过不授权生产修改。", "report": state["report"]})
        if not isinstance(result, dict) or result.get("decision") not in {"approve", "reject"}:
            raise ValueError("Review must contain approve or reject")
        if not result.get("reviewer", "").strip():
            raise ValueError("Reviewer is required")
        return {"review": {"decision": result["decision"], "reviewer": result["reviewer"].strip(),
                           "note": result.get("note", "")}}

    graph = StateGraph(WorkflowState)
    for name, fn in (("gather", gather), ("decide", decide), ("tool", tool),
                     ("verify", verify), ("render", render), ("human_review", human_review)):
        graph.add_node(name, fn)
    graph.add_edge(START, "gather")
    graph.add_edge("gather", "decide")
    graph.add_conditional_edges("decide", route_decision, {"verify": "verify", "tool": "tool"})
    graph.add_edge("tool", "decide")
    graph.add_conditional_edges("verify", route_verify, {"render": "render", "decide": "decide"})
    graph.add_edge("render", "human_review")
    graph.add_edge("human_review", END)
    return graph.compile(checkpointer=checkpointer)
