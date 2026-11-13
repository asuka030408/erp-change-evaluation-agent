"""Contract for model-directed assessment and citation review."""

from typing import Protocol

from ..models import Assessment, Evidence


class AssessmentEngine(Protocol):
    def decide(self, request: str, tenant_id: str, evidence: list[Evidence],
               catalog: list[dict], history: list[dict], approved_memory: list[dict],
               feedback: list[str], can_investigate: bool) -> dict: ...
    def check_support(self, assessment: Assessment, evidence: list[Evidence]) -> list[dict]: ...

class ResumeOnlyEngine:
    """Rebuild the graph solely to resume its already-paused review node."""

    def decide(self, *args, **kwargs) -> dict:
        raise RuntimeError("A saved review cannot start a new analysis")
