"""命令行和 HTTP API 共用的业务入口。

阅读顺序：先看 assess() 如何启动一次评估，再看 get()/review() 如何接回同一次评估。
真正的调查循环在 workflow.py；本文件负责准备资料、保存结果和审计。
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .analyzers.base import AssessmentEngine, ResumeOnlyEngine
from .analyzers.deepseek import DeepSeekEngine
from .audit import AuditLog, report_hash
from .corpus import MarkdownCorpus
from .ingest import IngestResult, ingest_file
from .memory import ProjectMemory
from .workflow import build_graph


@dataclass(frozen=True)
class AssessmentResult:
    """一次评估返回给调用方的结果；不表示报告已获人工批准。"""

    # run_id 是这次任务的唯一编号，之后查看、审阅和查审计都用它。
    run_id: str
    # report 是报告正文；report_path 是同一份报告在磁盘上的位置。
    report: str
    report_path: Path
    # model_usage 记录本次模型的调用次数和 token 用量。
    model_usage: dict


class AssessmentApplication:
    def __init__(self, project_root: Path, sources_root: Path | None = None):
        """确定项目目录、证据资料目录和运行数据目录。"""
        # project_root 是整个项目的根目录，例如 E:\Codex\erp-change-evaluation。
        self.project_root = project_root.resolve(strict=True)
        # sources_root 存放可分析的原文；不传时使用正式资料 data/sources。
        # 测试时可以明确传入 materials/sources，避免混用正式资料与测试资料。
        self.sources_root = (sources_root or self.project_root / "data" / "sources").resolve()
        self.sources_root.mkdir(parents=True, exist_ok=True)
        # .data 存放报告、工作流进度、Memory 和审计，不是合同等原始证据。
        self.data_dir = self.project_root / ".data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def corpus(self) -> MarkdownCorpus:
        """给文档读取器指定当前证据目录；读取时仍必须提供租户 ID。"""
        return MarkdownCorpus(self.sources_root)

    def ingest(self, file_path: Path, *, tenant_id: str, document_id: str, document_type: str,
               status: str, document_date: str, supersedes: str | None = None) -> IngestResult:
        """导入一份文件：保存原件，并生成带段落 ID 的可分析文本。"""
        return ingest_file(
            file_path, self.sources_root, self.sources_root.parent / "originals",
            tenant_id=tenant_id, document_id=document_id, document_type=document_type,
            status=status, document_date=document_date, supersedes=supersedes,
        )

    def assess(self, tenant_id: str, request: str, *, model: str = "deepseek-flash",
               engine: AssessmentEngine | None = None) -> AssessmentResult:
        """运行一次评估，直到报告写好并暂停在人工审阅处。"""
        # tenant_id 是客户/租户编号；request 是客户提出的这一次变更需求。
        # model 是 DeepSeek 模型名；engine 可由测试传入替身，避免付费调用。
        if not request.strip():
            raise ValueError("Request is required")
        # 先确认该租户有资料；没有资料就不要创建模型或开始评估。
        self.corpus.load(tenant_id)
        engine = engine or DeepSeekEngine(model)
        # Memory 是人工审核过的项目事实，不是合同原文；只取当前租户已批准的事实。
        memory = ProjectMemory(self.data_dir / "memory.sqlite")
        try:
            approved_memory = memory.current_approved(tenant_id)
        finally:
            memory.close()
        # run_id 把这次报告、工作流进度和审计记录关联起来。
        run_id = uuid.uuid4().hex[:12]
        log = AuditLog(self.data_dir / "audit.sqlite")
        try:
            log.append(run_id, tenant_id, "assessment_started", {"model": model, "request": request})
            # saver 把 LangGraph 的每一步保存到 SQLite，人工审阅时才能接着运行。
            with SqliteSaver.from_conn_string(str(self.data_dir / "checkpoints.sqlite")) as saver:
                # graph 是 workflow.py 定义的调查流程；config 指定这次任务的进度编号。
                graph = build_graph(self.corpus, engine, saver)
                config = {"configurable": {"thread_id": run_id}}
                try:
                    # 把需求、租户和已批准 Memory 作为初始状态交给工作流。
                    # graph.invoke 会运行到 human_review 暂停；这里不直接批准报告。
                    graph.invoke({
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "request": request,
                        "analysis_mode": f"DeepSeek:{model}",
                        "approved_memory": approved_memory,
                    }, config)
                except Exception as exc:
                    # 失败只记录异常类型；不把密钥或完整异常内容写进审计库。
                    log.append(run_id, tenant_id, "assessment_failed", {"error_type": type(exc).__name__})
                    raise
                # snapshot 是暂停时保存的工作流状态；values 有报告和证据，next 是下一节点。
                snapshot = graph.get_state(config)
                report = snapshot.values.get("report")
                if not report or snapshot.next != ("human_review",):
                    raise RuntimeError("Assessment did not pause at human review")
                # 报告按租户分目录保存；仍是待人工审阅的草稿。
                reports = self.data_dir / "reports" / tenant_id
                reports.mkdir(parents=True, exist_ok=True)
                report_path = reports / f"{run_id}.md"
                report_path.write_text(report, encoding="utf-8")
                # usage 优先取整次任务的合计用量；测试引擎可能只提供最近一次用量。
                usage = getattr(engine, "total_usage", getattr(engine, "last_usage", {}))
                # 审计记录报告摘要、所用证据、调查动作和引文核对结果。
                log.append(run_id, tenant_id, "report_ready", {
                    "report_sha256": report_hash(report),
                    "evidence_section_ids": [item["section"]["section_id"] for item in snapshot.values["evidence"]],
                    "context_mode": snapshot.values.get("context_mode"),
                    "omitted_sections": snapshot.values.get("omitted_sections", 0),
                    "investigation": snapshot.values.get("history", []),
                    "citation_checks": snapshot.values.get("verification", {}).get("checks", []),
                    "model_usage": usage,
                })
                return AssessmentResult(run_id, report, report_path, usage)
        finally:
            log.close()

    def get(self, run_id: str, tenant_id: str | None = None) -> dict:
        """按任务编号读取保存的状态；传入 tenant_id 时同时检查租户归属。"""
        with SqliteSaver.from_conn_string(str(self.data_dir / "checkpoints.sqlite")) as saver:
            # 这里只读旧任务，所以使用不会重新分析的 ResumeOnlyEngine。
            graph = build_graph(self.corpus, ResumeOnlyEngine(), saver)
            snapshot = graph.get_state({"configurable": {"thread_id": run_id}})
            if not snapshot.values:
                raise KeyError("Unknown run ID")
            if tenant_id is not None and snapshot.values.get("tenant_id") != tenant_id:
                raise KeyError("Unknown run ID")
            return {"values": snapshot.values, "next": list(snapshot.next)}

    def review(self, run_id: str, tenant_id: str, decision: str, reviewer: str, note: str = "") -> dict:
        """恢复暂停的报告审阅；approve 仅表示报告通过，不授权生产修改。"""
        with SqliteSaver.from_conn_string(str(self.data_dir / "checkpoints.sqlite")) as saver:
            graph = build_graph(self.corpus, ResumeOnlyEngine(), saver)
            config = {"configurable": {"thread_id": run_id}}
            snapshot = graph.get_state(config)
            if not snapshot.values or snapshot.values.get("tenant_id") != tenant_id:
                raise KeyError("Unknown run ID")
            if snapshot.next != ("human_review",):
                raise ValueError("This run is not awaiting review")
            # Command(resume=...) 把人工决定送回暂停点，不会重新调用分析模型。
            result = graph.invoke(Command(resume={"decision": decision, "reviewer": reviewer, "note": note}), config)
        log = AuditLog(self.data_dir / "audit.sqlite")
        try:
            log.append(run_id, tenant_id, "report_reviewed", result["review"])
        finally:
            log.close()
        return result["review"]

    def audit_events(self, run_id: str, tenant_id: str | None = None) -> list[dict]:
        """读取某次任务的审计事件；API 调用时先核对租户。"""
        if tenant_id is not None:
            self.get(run_id, tenant_id)
        log = AuditLog(self.data_dir / "audit.sqlite")
        try:
            return log.events(run_id)
        finally:
            log.close()
