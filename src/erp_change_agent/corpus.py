"""Load immutable Markdown source sections with tenant and document metadata."""

import re
from pathlib import Path

from .models import Section


HEADER = re.compile(r"^##\s+(.+?)\s+§([\d.]+)\s+(.+)$")
META = re.compile(r"^-\s+(.+?)：(.+)$")
DATE_KEYS = ("签收日期", "生效日期", "采集时间", "采集日期", "更新日期", "会议日期", "签署日期", "创建日期", "日期")


class CorpusError(ValueError):
    """Malformed source or access request."""


class MarkdownCorpus:
    def __init__(self, sources_root: Path):
        self.sources_root = sources_root.resolve(strict=True)

    def tenants(self) -> list[str]:
        return sorted(p.name for p in self.sources_root.iterdir() if p.is_dir())

    def load(self, tenant_id: str) -> list[Section]:
        if tenant_id not in self.tenants():
            raise CorpusError(f"Unknown or unauthorized tenant: {tenant_id}")
        tenant_root = (self.sources_root / tenant_id).resolve(strict=True)
        sections: list[Section] = []
        seen: set[str] = set()
        for path in sorted(tenant_root.rglob("*.md")):
            if tenant_root not in path.resolve(strict=True).parents:
                raise CorpusError("Source escaped tenant directory")
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()
            metadata: dict[str, str] = {}
            for line in lines:
                match = META.match(line)
                if match:
                    metadata[match.group(1).strip()] = match.group(2).strip()
            doc_id = metadata.get("文档 ID")
            if not doc_id:
                raise CorpusError(f"Missing document ID: {path}")
            declared_tenant = re.match(r"[A-Za-z0-9_-]+", metadata.get("租户", ""))
            if not declared_tenant or declared_tenant.group() != tenant_id:
                raise CorpusError(f"Tenant metadata mismatch: {path}")
            date = next((metadata[key] for key in DATE_KEYS if key in metadata), "unknown")
            document_type = path.parent.name
            current_heading: tuple[str, str] | None = None
            body: list[str] = []
            for line in lines + ["## __END__ §0 END"]:
                match = HEADER.match(line)
                if not match:
                    if current_heading:
                        body.append(line)
                    continue
                if current_heading:
                    section_id, title = current_heading
                    text = "\n".join(body).strip()
                    if text:
                        if section_id in seen:
                            raise CorpusError(f"Duplicate section ID: {section_id}")
                        seen.add(section_id)
                        sections.append(Section(
                            tenant_id=tenant_id,
                            doc_id=doc_id,
                            section_id=section_id,
                            title=title,
                            text=text,
                            source_path=str(path.relative_to(self.sources_root)),
                            document_type=document_type,
                            status=metadata.get("状态", "unknown"),
                            date=date,
                        ))
                current_heading = (f"{match.group(1).strip()} §{match.group(2)}", match.group(3).strip())
                body = []
        return sections
