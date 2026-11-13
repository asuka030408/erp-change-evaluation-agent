from erp_change_agent.retrieval import HybridRetriever


def test_corpus_is_tenant_scoped_and_excludes_answers(corpus):
    xh = corpus.load("TENANT-XH")
    th = corpus.load("TENANT-TH")
    assert xh and th
    assert all(section.tenant_id == "TENANT-XH" for section in xh)
    assert all(section.tenant_id == "TENANT-TH" for section in th)
    assert not {section.doc_id for section in xh} & {section.doc_id for section in th}
    assert all("cases" not in section.source_path for section in xh + th)
    assert len({section.section_id for section in xh + th}) == len(xh + th)


def test_threshold_retrieval_finds_formal_decision_and_contract(corpus):
    results = HybridRetriever(corpus.load("TENANT-XH")).search("普通采购三级审批阈值改为50000元今晚部署")
    ids = {item.section.section_id for item in results}
    assert "M-XH-091 §1" in ids
    assert "C-XH-001 §3.3" in ids
    assert all(item.section.tenant_id == "TENANT-XH" for item in results)
