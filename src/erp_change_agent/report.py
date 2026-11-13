"""Render reviewable Markdown from validated structured data."""

from .models import Assessment, Evidence


def render_report(assessment: Assessment, evidence: list[Evidence], run_id: str, analysis_mode: str = "unknown") -> str:
    by_id = {item.section.section_id: item.section for item in evidence}
    labels = {"fact": "事实", "conflict": "冲突", "impact": "影响", "risk": "风险", "uncertain": "未确认"}
    lines = [
        "# ERP 变更影响评估（草稿）", "",
        f"- 任务 ID：`{run_id}`",
        f"- 租户：`{assessment.tenant_id}`",
        f"- 分析方式：`{analysis_mode}`",
        f"- 客户需求：{assessment.request}",
        "- 状态：等待人工审阅；本报告不构成合同批准或上线许可", "",
        "## 初步判断", "", assessment.preliminary_decision, "",
        "## 证据与影响", "",
    ]
    for finding in assessment.findings:
        citations = "；".join(
            f"`{ref}`（{by_id[ref].document_type}；{by_id[ref].date}；{by_id[ref].status}；{by_id[ref].source_path}）"
            for ref in finding.citations
        )
        lines.append(f"- **{labels[finding.kind]}**：{finding.claim} 依据：{citations}")
    lines.extend(["", "## 待确认问题", ""])
    lines.extend(f"- {item}" for item in assessment.questions or ["暂无；人工审阅时仍需确认需求范围。"])
    lines.extend(["", "## 所需人工确认", ""])
    lines.extend(f"- {item}" for item in assessment.approvals_needed or ["业务负责人审阅本报告。"])
    lines.extend(["", "## 局限", ""])
    lines.extend(f"- {item}" for item in assessment.limitations or ["无额外说明。"])
    lines.append("")
    return "\n".join(lines)
