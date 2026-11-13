"""Import original files and create reviewable, tenant-scoped text sources."""

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")
TENANT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")
SOURCE_TYPES = {"合同", "会议", "工单", "配置", "接口", "消息", "其他"}
EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    normalized_path: Path
    original_path: Path
    sha256: str
    sections: int


def _extract(path: Path) -> list[tuple[str, str]]:
    extension = path.suffix.lower()
    if extension in {".md", ".txt"}:
        return [("原文", path.read_text(encoding="utf-8-sig"))]
    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(f"第{index}页", page.extract_text() or "") for index, page in enumerate(reader.pages, start=1)]
    if extension == ".docx":
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        blocks: list[str] = []
        for item in Document(str(path)).iter_inner_content():
            if isinstance(item, Paragraph):
                blocks.append(item.text)
            elif isinstance(item, Table):
                for row in item.rows:
                    blocks.append(" | ".join(cell.text.replace("\n", "；") for cell in row.cells))
        return [("正文", "\n".join(blocks))]
    raise ValueError(f"Unsupported file type: {extension}")


def _split_text(text: str, max_chars: int = 1600) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = [paragraph[i:i + max_chars] for i in range(0, len(paragraph), max_chars)]
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > max_chars:
                chunks.append(current)
                current = ""
            current = f"{current}\n\n{piece}".strip() if current else piece
    if current:
        chunks.append(current)
    return chunks


def ingest_file(
    file_path: Path,
    sources_root: Path,
    originals_root: Path,
    *,
    tenant_id: str,
    document_id: str,
    document_type: str,
    status: str,
    document_date: str,
    supersedes: str | None = None,
) -> IngestResult:
    """Fail before writing when metadata or text extraction is invalid."""
    source = file_path.resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in EXTENSIONS:
        raise ValueError("Input must be a .md, .txt, .pdf, or .docx file")
    if not TENANT_PATTERN.fullmatch(tenant_id) or not ID_PATTERN.fullmatch(document_id):
        raise ValueError("Tenant and document IDs must use letters, digits, underscore, dash, or dot")
    if document_type not in SOURCE_TYPES or not status.strip():
        raise ValueError("Document type and status are required")
    date.fromisoformat(document_date)
    if supersedes and not ID_PATTERN.fullmatch(supersedes):
        raise ValueError("Invalid superseded document ID")

    extracted = _extract(source)
    sections = [(title, chunk) for title, text in extracted for chunk in _split_text(text)]
    if not sections:
        raise ValueError("No selectable text found; scanned files require OCR and review before import")
    normalized = sources_root / tenant_id / document_type / f"{document_id}.md"
    original = originals_root / tenant_id / f"{document_id}{source.suffix.lower()}"
    if normalized.exists() or original.exists() or any(
        sources_root.glob(f"{tenant_id}/*/{document_id}.md")
    ):
        raise FileExistsError(f"Document ID already exists for tenant: {document_id}")

    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    metadata = [
        f"# {document_id}：{source.name}",
        "",
        f"- 文档 ID：{document_id}",
        f"- 租户：{tenant_id}",
        f"- 状态：{status.strip()}",
        f"- 日期：{document_date}",
        f"- 原件 SHA256：{digest}",
        f"- 原件文件名：{source.name}",
    ]
    if supersedes:
        metadata.append(f"- 取代：{supersedes}")
    for index, (title, text) in enumerate(sections, start=1):
        # A source heading must remain content, never masquerade as a generated section ID.
        text = "\n".join("\\" + line if line.startswith("## ") else line for line in text.splitlines())
        metadata.extend(["", f"## {document_id} §{index} {title}", "", text])
    normalized.parent.mkdir(parents=True, exist_ok=True)
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, original)
    try:
        normalized.write_text("\n".join(metadata) + "\n", encoding="utf-8")
    except Exception:
        original.unlink(missing_ok=True)
        raise

    manifest = sources_root.parent / "manifest.jsonl"
    record = {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "document_type": document_type,
        "status": status.strip(),
        "date": document_date,
        "supersedes": supersedes,
        "original_path": str(original),
        "normalized_path": str(normalized),
        "sha256": digest,
        "sections": len(sections),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return IngestResult(document_id, normalized, original, digest, len(sections))
