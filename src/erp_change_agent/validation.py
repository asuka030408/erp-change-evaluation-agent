"""Fail closed on missing, cross-tenant, or invented citations."""

import re

from .models import Assessment, Evidence


class EvidenceValidationError(ValueError):
    pass


def deployment_scope_missing(request: str) -> bool:
    """Guard a generic deployment question against an inferred change target."""
    return bool(re.search(r"部署|上线|投产", request)) and not bool(re.search(
        r"阈值|金额|审批|采购|接口|字段|配置|流程|节点|角色|工单|变更单|试点|组织|子公司|紧急|补审|订单", request
    ))


def validate_assessment(assessment: Assessment, evidence: list[Evidence]) -> Assessment:
    allowed = {item.section.section_id: item.section for item in evidence}
    if not assessment.findings:
        raise EvidenceValidationError("Assessment contains no evidence-backed finding")
    for finding in assessment.findings:
        if finding.kind not in {"fact", "conflict", "impact", "risk", "uncertain"}:
            raise EvidenceValidationError(f"Unsupported finding type: {finding.kind}")
        if not finding.citations:
            raise EvidenceValidationError(f"Finding has no citation: {finding.claim}")
        for citation in finding.citations:
            if citation not in allowed:
                raise EvidenceValidationError(f"Citation not in retrieved evidence: {citation}")
            if allowed[citation].tenant_id != assessment.tenant_id:
                raise EvidenceValidationError(f"Cross-tenant citation: {citation}")
    return assessment
