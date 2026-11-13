from erp_change_agent.context import select_context


def test_short_corpus_reads_all_tenant_sections(corpus):
    sections = corpus.load("TENANT-XH")
    selection = select_context(sections, "将阈值改为5万元")
    assert selection.mode == "all_tenant_sections"
    assert selection.omitted_sections == 0
    assert {item.section.section_id for item in selection.evidence} == {item.section_id for item in sections}


def test_large_corpus_uses_bounded_retrieval(corpus):
    sections = corpus.load("TENANT-XH")
    selection = select_context(sections, "普通采购审批阈值", max_chars=500)
    assert selection.mode == "retrieved_sections"
    assert sum(len(item.section.text) for item in selection.evidence) <= 500
    assert selection.omitted_sections > 0
