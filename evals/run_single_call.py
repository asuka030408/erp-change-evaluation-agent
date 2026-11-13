"""Run explicitly selected held-out cases through the bounded Agent.

Requires DEEPSEEK_API_KEY in the current process. Expected answers are never
sent to the model. Results stay under the project's .data/evals directory.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from erp_change_agent.application import AssessmentApplication


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = {"04"}


def cases() -> dict[str, tuple[str, str]]:
    table = ROOT / "materials" / "cases" / "测试需求与预期.md"
    found = {}
    for line in table.read_text(encoding="utf-8").splitlines():
        fields = [field.strip() for field in line.split("|")]
        if len(fields) < 5 or fields[1] not in {f"{n:02d}" for n in range(1, 31)}:
            continue
        case_id, request = fields[1], fields[2]
        tenant = "TENANT-TH" if request.startswith("天衡") else "TENANT-XH"
        found[case_id] = (tenant, request)
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--all", action="store_true", help="Run all 30 paid evaluation cases")
    parser.add_argument("--model", default="deepseek-flash")
    args = parser.parse_args()
    known = cases()
    selected = set(known) if args.all else set(args.case_ids or DEFAULT_CASES)
    unknown = selected - known.keys()
    if unknown:
        raise SystemExit(f"Unknown case IDs: {sorted(unknown)}")

    application = AssessmentApplication(ROOT, ROOT / "materials" / "sources")
    results = []
    output_dir = ROOT / ".data" / "evals"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"agent_eval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    totals = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    for case_id in sorted(selected):
        if totals["input_tokens"] >= 500000 or totals["output_tokens"] >= 150000 or totals["calls"] >= 120:
            print("Evaluation stopped at aggregate token/call budget", flush=True)
            break
        tenant_id, request = known[case_id]
        try:
            result = application.assess(tenant_id, request, model=args.model)
            row = {
                "case_id": case_id,
                "tenant_id": tenant_id,
                "request": request,
                "run_id": result.run_id,
                "report_path": str(result.report_path),
                "usage": result.model_usage,
            }
            print(f"{case_id}: {result.run_id} {result.model_usage}", flush=True)
        except Exception as exc:
            row = {"case_id": case_id, "tenant_id": tenant_id, "request": request,
                   "error_type": type(exc).__name__, "error": str(exc)}
            print(f"{case_id}: ERROR {type(exc).__name__}: {exc}", flush=True)
        results.append(row)
        for key in totals:
            totals[key] += row.get("usage", {}).get(key, 0)
        output.write_text(json.dumps({"results": results, "totals": totals}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
