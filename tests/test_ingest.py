import hashlib

import pytest
from docx import Document
from pypdf import PdfWriter

from erp_change_agent.corpus import MarkdownCorpus
from erp_change_agent.ingest import ingest_file


def test_text_import_keeps_original_and_searchable_sections(tmp_path):
    incoming = tmp_path / "incoming.txt"
    incoming.write_text("采购审批合同\n\n五万元以上增加财务审批。", encoding="utf-8")
    sources = tmp_path / "data" / "sources"
    originals = tmp_path / "data" / "originals"
    result = ingest_file(
        incoming, sources, originals,
        tenant_id="TENANT-A", document_id="C-A-001", document_type="合同",
        status="双方已签", document_date="2026-11-13",
    )
    assert result.original_path.read_bytes() == incoming.read_bytes()
    assert result.sha256 == hashlib.sha256(incoming.read_bytes()).hexdigest()
    assert "五万元" in MarkdownCorpus(sources).load("TENANT-A")[0].text
    with pytest.raises(FileExistsError):
        ingest_file(incoming, sources, originals, tenant_id="TENANT-A", document_id="C-A-001", document_type="合同", status="双方已签", document_date="2026-11-13")


def test_docx_import_reads_paragraphs_and_tables(tmp_path):
    incoming = tmp_path / "minutes.docx"
    doc = Document()
    doc.add_paragraph("会议决定保留原审批阈值。")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "状态"
    table.cell(0, 1).text = "已确认"
    doc.save(incoming)
    sources = tmp_path / "sources"
    ingest_file(incoming, sources, tmp_path / "originals", tenant_id="TENANT-A", document_id="M-A-001", document_type="会议", status="已签收", document_date="2026-11-13")
    text = "\n".join(section.text for section in MarkdownCorpus(sources).load("TENANT-A"))
    assert "会议决定" in text and "已确认" in text


def test_scanned_or_blank_pdf_is_rejected_without_partial_import(tmp_path):
    incoming = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with incoming.open("wb") as handle:
        writer.write(handle)
    sources = tmp_path / "sources"
    originals = tmp_path / "originals"
    with pytest.raises(ValueError, match="OCR"):
        ingest_file(incoming, sources, originals, tenant_id="TENANT-A", document_id="C-A-002", document_type="合同", status="待确认", document_date="2026-11-13")
    assert not originals.exists()
