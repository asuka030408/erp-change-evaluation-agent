from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from erp_change_agent.models import Assessment, Finding
from erp_change_agent.workflow import build_graph


class FakeModelEngine:
    """Test double for model calls; never used by the CLI."""

    def __init__(self, invent_first_citation: bool = False):
        self.calls: list[str] = []
        self.invent_first_citation = invent_first_citation

    def decide(self, request, tenant_id, evidence, catalog, history, approved_memory, feedback, can_investigate):
        self.calls.append("decide")
        section_id = "INVENTED §1" if self.invent_first_citation and len(self.calls) == 1 else evidence[0].section.section_id
        return {"action": "draft", "reason": "enough", "draft": {
            "preliminary_decision": "待人工确认",
            "findings": [{"claim": "证据需要人工核对。", "citations": [section_id], "kind": "uncertain"}],
            "questions": [], "approvals_needed": ["业务负责人审阅报告"], "limitations": feedback}}

    def check_support(self, assessment, evidence):
        return [{"supported": True, "reason": "test"} for _ in assessment.findings]

def test_model_steps_and_human_pause(corpus, tmp_path):
    engine = FakeModelEngine()
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(corpus, engine, saver)
        config = {"configurable": {"thread_id": "model-test-1"}}
        graph.invoke({
            "run_id": "model-test-1",
            "tenant_id": "TENANT-XH",
            "request": "普通采购阈值调整",
            "analysis_mode": "DeepSeek:test-double",
        }, config)
        paused = graph.get_state(config)
        assert paused.next == ("human_review",)
        assert paused.values["analysis_round"] == 1
        assert paused.values["context_mode"] == "all_tenant_sections"
        assert engine.calls == ["decide"]
        assert "DeepSeek:test-double" in paused.values["report"]
        result = graph.invoke(Command(resume={"decision": "approve", "reviewer": "测试审阅人"}), config)
        assert result["review"]["decision"] == "approve"
        assert graph.get_state(config).next == ()


def test_invalid_citation_triggers_one_model_retry(corpus, tmp_path):
    engine = FakeModelEngine(invent_first_citation=True)
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(corpus, engine, saver)
        config = {"configurable": {"thread_id": "model-test-2"}}
        graph.invoke({
            "run_id": "model-test-2",
            "tenant_id": "TENANT-XH",
            "request": "采购审批调整",
            "analysis_mode": "DeepSeek:test-double",
        }, config)
        paused = graph.get_state(config)
        assert paused.values["analysis_round"] == 2
        assert engine.calls == ["decide", "decide"]


def test_model_can_search_then_read_before_draft(corpus, tmp_path):
    class Investigating(FakeModelEngine):
        def decide(self, request, tenant_id, evidence, catalog, history, approved_memory, feedback, can_investigate):
            if not history:
                self.calls.append("search")
                return {"action": "search", "reason": "check newer decision", "query": "正式决议"}
            if len(history) == 1:
                self.calls.append("read")
                return {"action": "read", "reason": "read contract", "section_ids": [catalog[0]["section_id"]]}
            return super().decide(request, tenant_id, evidence, catalog, history, approved_memory, feedback, can_investigate)

    engine = Investigating()
    with SqliteSaver.from_conn_string(str(tmp_path / "loop.sqlite")) as saver:
        graph = build_graph(corpus, engine, saver)
        config = {"configurable": {"thread_id": "loop"}}
        graph.invoke({"run_id": "loop", "tenant_id": "TENANT-XH", "request": "调整采购审批"}, config)
        state = graph.get_state(config)
        assert state.next == ("human_review",)
        assert state.values["tool_actions"] == 2
        assert len(state.values["history"]) == 2
        assert engine.calls == ["search", "read", "decide"]


def test_unsupported_claim_is_revised_or_marked_uncertain(corpus, tmp_path):
    class Unsupported(FakeModelEngine):
        def check_support(self, assessment, evidence):
            return [{"supported": False, "reason": "原文不支持"}]

    engine = Unsupported()
    with SqliteSaver.from_conn_string(str(tmp_path / "support.sqlite")) as saver:
        graph = build_graph(corpus, engine, saver)
        config = {"configurable": {"thread_id": "support"}}
        graph.invoke({"run_id": "support", "tenant_id": "TENANT-XH", "request": "调整采购审批"}, config)
        state = graph.get_state(config)
        assert state.next == ("human_review",)
        assert state.values["analysis_round"] == 2
        assert "未确认" in state.values["report"]
        assert "原文不支持" in state.values["report"]


def test_unsupported_preliminary_decision_is_not_asserted(corpus, tmp_path):
    class WrongScope(FakeModelEngine):
        def decide(self, request, tenant_id, evidence, catalog, history, approved_memory, feedback, can_investigate):
            result = super().decide(request, tenant_id, evidence, catalog, history,
                                    approved_memory, feedback, can_investigate)
            result["draft"]["preliminary_decision"] = "本次将阈值降为 50,000 元。"
            return result

        def check_support(self, assessment, evidence):
            return {"decision_aligned": True, "decision_reason": "test engine misses scope error",
                    "checks": [{"supported": True, "reason": "test"} for _ in assessment.findings]}

    engine = WrongScope()
    with SqliteSaver.from_conn_string(str(tmp_path / "scope.sqlite")) as saver:
        graph = build_graph(corpus, engine, saver)
        config = {"configurable": {"thread_id": "scope"}}
        graph.invoke({"run_id": "scope", "tenant_id": "TENANT-XH",
                      "request": "业务负责人同意了，现在就能部署吗？"}, config)
        state = graph.get_state(config)
        assert state.next == ("human_review",)
        assert "本次拟部署的具体变更对象和范围未确认" in state.values["report"]
        assert "本次将阈值降为" not in state.values["report"]
