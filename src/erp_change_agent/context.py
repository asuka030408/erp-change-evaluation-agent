"""Choose a bounded evidence set without an extra model call.

For a small tenant corpus, read every section. When the corpus grows, use the
retriever and keep complete sections within a conservative character budget.
"""

from dataclasses import dataclass

from .models import Evidence, Section
from .retrieval import HybridRetriever


@dataclass(frozen=True)
class ContextSelection:
    evidence: list[Evidence]
    mode: str
    omitted_sections: int


def select_context(
    sections: list[Section], request: str, *, max_chars: int = 24000, max_sections: int = 64,
) -> ContextSelection:
    if not sections:
        raise ValueError("No tenant-scoped evidence found")
    if any(len(section.text) > max_chars for section in sections):
        raise ValueError("A source section exceeds the context budget; split it before assessment")
    if len(sections) <= max_sections and sum(len(section.text) for section in sections) <= max_chars:
        return ContextSelection([Evidence(section, 1.0) for section in sections], "all_tenant_sections", 0)
    ranked = HybridRetriever(sections).search(request, limit=min(max_sections, len(sections)))
    chosen: list[Evidence] = []
    used_chars = 0
    for item in ranked:
        size = len(item.section.text)
        if used_chars + size <= max_chars:
            chosen.append(item)
            used_chars += size
    if not chosen:
        raise ValueError("No evidence fits the context budget")
    return ContextSelection(chosen, "retrieved_sections", len(sections) - len(chosen))
