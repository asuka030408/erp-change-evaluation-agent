"""Offline coverage summary; expected answers never enter Agent context."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = re.compile(r"(?:C|CO|M|CFG|IF|T|MSG)-(?:XH|TH)-[A-Z0-9-]+ §[0-9.]+")

def main() -> None:
    expected = {}
    for line in (ROOT / "materials/cases/测试需求与预期.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 4 and re.fullmatch(r"\d\d", cells[1]):
            tenant = "TH" if cells[2].startswith("天衡") else "XH"
            expected[cells[1]] = {ref for ref in REF.findall(cells[3]) if f"-{tenant}-" in ref}
    records = {}
    for path in sorted((ROOT / ".data/evals").glob("agent_eval_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("results", data if isinstance(data, list) else []):
            if row.get("report_path"):
                records[row["case_id"]] = row
    lines = ["# 虚构材料评测：离线证据覆盖", "",
             "只检查报告是否引用人工预期中明确列出的段落；不代表语义正确或通过人工评测。", "",
             "| 案例 | 运行 | 预期段落覆盖 | 缺少段落 |", "| --- | --- | --- | --- |"]
    complete = partial = 0
    for case_id in sorted(expected):
        row = records.get(case_id)
        if not row:
            lines.append(f"| {case_id} | 未完成 | — | — |")
            continue
        report = Path(row["report_path"]).read_text(encoding="utf-8")
        cited = set(REF.findall(report))
        wanted = expected[case_id]
        missing = wanted - cited
        if missing:
            partial += 1
        else:
            complete += 1
        lines.append(f"| {case_id} | {row['run_id']} | {len(wanted)-len(missing)}/{len(wanted)} | {', '.join(sorted(missing)) or '—'} |")
    lines.extend(["", f"已生成报告：{len(records)}/30；关键段落全覆盖：{complete}；部分覆盖：{partial}。", ""])
    output = ROOT / ".data/evals/coverage_summary.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)

if __name__ == "__main__":
    main()
