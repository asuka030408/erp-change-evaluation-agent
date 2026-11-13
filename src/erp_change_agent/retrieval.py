"""Tenant-scoped hybrid lexical retrieval with source-type coverage.

The two local signals are Chinese word BM25 and character n-gram cosine. The
character channel is a vector index, but not a semantic embedding model.
"""

import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import jieba

from .models import Evidence, Section


_PUNCT = re.compile(r"[\W_]+", re.UNICODE)
_IMPORTANT_TYPES = ("合同", "会议", "配置", "接口", "工单")
_STOP = {"请", "把", "的", "了", "是", "吗", "能", "否", "我们", "这个", "一下", "现在", "以后", "需要", "怎么", "什么"}

_cache_dir = Path(os.environ.get("ERP_CHANGE_CACHE_DIR", Path.cwd() / ".data" / "jieba"))
_cache_dir.mkdir(parents=True, exist_ok=True)
jieba.dt.tmp_dir = str(_cache_dir)


def words(text: str) -> list[str]:
    return [w.lower() for w in jieba.lcut(text) if w.strip() and w not in _STOP and (len(w) > 1 or w.isdigit())]


def grams(text: str) -> Counter[str]:
    compact = _PUNCT.sub("", text.lower())
    return Counter(compact[i:i + 2] for i in range(max(0, len(compact) - 1)))


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(term, 0) for term, value in a.items())
    length_a = math.sqrt(sum(value * value for value in a.values()))
    length_b = math.sqrt(sum(value * value for value in b.values()))
    return dot / (length_a * length_b)


class HybridRetriever:
    def __init__(self, sections: list[Section]):
        self.sections = sections
        self.tokens = [words(s.title + " " + s.text) for s in sections]
        self.vectors = [grams(s.title + " " + s.text) for s in sections]
        self.lengths = [len(tokens) for tokens in self.tokens]
        self.avg_len = sum(self.lengths) / len(self.lengths) if self.lengths else 1
        self.doc_freq: Counter[str] = Counter()
        for tokens in self.tokens:
            self.doc_freq.update(set(tokens))

    def _bm25(self, query: list[str], index: int) -> float:
        counts = Counter(self.tokens[index])
        n = len(self.sections)
        score = 0.0
        for term in set(query):
            freq = counts.get(term, 0)
            if not freq:
                continue
            df = self.doc_freq[term]
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            score += idf * freq * 2.2 / (freq + 1.2 * (0.25 + 0.75 * self.lengths[index] / self.avg_len))
        return score

    def search(self, query: str, *, limit: int = 24) -> list[Evidence]:
        if not self.sections:
            return []
        # Expansion is limited to domain vocabulary; source status never becomes an instruction.
        expanded = query + " 采购申请 审批 合同 正式决定 当前配置 变更 影响"
        query_words = words(expanded)
        query_vector = grams(query)
        bm25 = [self._bm25(query_words, i) for i in range(len(self.sections))]
        max_bm25 = max(bm25) or 1.0
        scored = [
            Evidence(section, round(0.65 * bm25[i] / max_bm25 + 0.35 * cosine(query_vector, self.vectors[i]), 5))
            for i, section in enumerate(self.sections)
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        selected: list[Evidence] = []
        used: set[str] = set()
        # Keep the best section from each important source type before filling by score.
        grouped: dict[str, list[Evidence]] = defaultdict(list)
        for item in scored:
            grouped[item.section.document_type].append(item)
        for source_type in _IMPORTANT_TYPES:
            if grouped[source_type]:
                item = grouped[source_type][0]
                selected.append(item)
                used.add(item.section.section_id)
        for item in scored:
            if len(selected) >= limit:
                break
            if item.section.section_id not in used:
                selected.append(item)
                used.add(item.section.section_id)
        return selected[:limit]
