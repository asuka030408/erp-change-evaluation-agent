"""Data contracts shared by the corpus, retrieval, analysis, and workflow modules."""

from dataclasses import asdict, dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Section:
    tenant_id: str
    doc_id: str
    section_id: str
    title: str
    text: str
    source_path: str
    document_type: str
    status: str
    date: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    section: Section
    score: float

    def to_dict(self) -> dict:
        return {"section": self.section.to_dict(), "score": self.score}


@dataclass
class Finding:
    claim: str
    citations: list[str] = field(default_factory=list)
    kind: Literal["fact", "conflict", "impact", "risk", "uncertain"] = "fact"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Assessment:
    request: str
    tenant_id: str
    preliminary_decision: str
    findings: list[Finding]
    questions: list[str]
    approvals_needed: list[str]
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
