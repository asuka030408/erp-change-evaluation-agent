from pathlib import Path

import pytest

from erp_change_agent.corpus import MarkdownCorpus


@pytest.fixture
def corpus() -> MarkdownCorpus:
    return MarkdownCorpus(Path(__file__).resolve().parents[1] / "materials" / "sources")
