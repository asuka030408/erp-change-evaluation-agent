"""Trusted local administration and assessment entry point."""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from .application import AssessmentApplication
from .auth import TokenStore
from .memory import ProjectMemory
from .retrieval import HybridRetriever


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="erp-change", description="ERP change impact assessment agent")
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--sources-root", type=Path)
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("tenants")

    ingest = commands.add_parser("ingest")
    ingest.add_argument("--file", type=Path, required=True)
    ingest.add_argument("--tenant", required=True)
    ingest.add_argument("--doc-id", required=True)
    ingest.add_argument("--type", choices=["合同", "会议", "工单", "配置", "接口", "消息", "其他"], required=True)
    ingest.add_argument("--status", required=True)
    ingest.add_argument("--date", required=True)
    ingest.add_argument("--supersedes")

    search = commands.add_parser("search")
    search.add_argument("--tenant", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)

    assess = commands.add_parser("assess")
    assess.add_argument("--tenant", required=True)
    assess.add_argument("--request", required=True)
    assess.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"))
    assess.add_argument("--ask-api-key", action="store_true")

    show = commands.add_parser("show")
    show.add_argument("--run-id", required=True)
    review = commands.add_parser("review")
    review.add_argument("--run-id", required=True)
    review.add_argument("--decision", choices=["approve", "reject"], required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note", default="")
    audit = commands.add_parser("audit")
    audit.add_argument("--run-id", required=True)

    issue = commands.add_parser("issue-token", help="Create a tenant-bound API token; print it once")
    issue.add_argument("--tenant", required=True)
    issue.add_argument("--role", choices=["analyst", "reviewer", "admin"], required=True)
    issue.add_argument("--name", required=True)
    commands.add_parser("revoke-token", help="Revoke an API token entered without shell history")
    serve = commands.add_parser("serve", help="Start local HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    ui = commands.add_parser("ui", help="Open the no-login local browser UI")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true")
    ui.add_argument("--key-file", type=Path, help="Read the DeepSeek key from a local text file")
    ui.add_argument("--ask-api-key", action="store_true")

    propose = commands.add_parser("memory-propose")
    propose.add_argument("--tenant", required=True)
    propose.add_argument("--claim", required=True)
    propose.add_argument("--citation", action="append", required=True)
    propose.add_argument("--supersedes-id", type=int)
    memory_review = commands.add_parser("memory-review")
    memory_review.add_argument("--tenant", required=True)
    memory_review.add_argument("--fact-id", type=int, required=True)
    memory_review.add_argument("--decision", choices=["approved", "rejected"], required=True)
    memory_review.add_argument("--reviewer", required=True)
    memory_review.add_argument("--note", default="")
    memory_list = commands.add_parser("memory-list")
    memory_list.add_argument("--tenant", required=True)
    return p


def _run(args: argparse.Namespace) -> None:
    root = args.project_root.resolve(strict=True)
    if args.command == "ui":
        import threading
        import webbrowser
        import uvicorn
        from .ui import create_ui_app

        if args.key_file:
            key = args.key_file.read_text(encoding="utf-8-sig").strip()
            if not key:
                raise ValueError("API key file is empty")
            os.environ["DEEPSEEK_API_KEY"] = key
        elif args.ask_api_key:
            os.environ["DEEPSEEK_API_KEY"] = getpass.getpass("DeepSeek API key: ")
        address = f"http://127.0.0.1:{args.port}/"
        app = create_ui_app(root, sources_root=args.sources_root)
        print(f"本机工作台：{address}")
        if not args.no_browser:
            timer = threading.Timer(1.2, lambda: webbrowser.open(address))
            timer.daemon = True
            timer.start()
        uvicorn.run(app, host="127.0.0.1", port=args.port)
        return
    sources_root = args.sources_root or root / "data" / "sources"
    if not sources_root.is_absolute():
        sources_root = root / sources_root
    service = AssessmentApplication(root, sources_root)
    corpus = service.corpus

    if args.command == "ingest":
        result = service.ingest(
            args.file, tenant_id=args.tenant, document_id=args.doc_id,
            document_type=args.type, status=args.status, document_date=args.date,
            supersedes=args.supersedes,
        )
        print(f"Imported {result.document_id}: {result.sections} sections")
        print(f"Original: {result.original_path}")
        print(f"Search text: {result.normalized_path}")
    elif args.command == "tenants":
        print("\n".join(corpus.tenants()))
    elif args.command == "search":
        for item in HybridRetriever(corpus.load(args.tenant)).search(args.query, limit=args.limit):
            section = item.section
            print(f"{item.score:.3f}\t{section.section_id}\t{section.status}\t{section.source_path}")
    elif args.command == "assess":
        if args.ask_api_key:
            os.environ["DEEPSEEK_API_KEY"] = getpass.getpass("DeepSeek API key: ")
        result = service.assess(args.tenant, args.request, model=args.model)
        print(f"Run ID: {result.run_id}", file=sys.stderr)
        print(result.report)
        print(f"\nReport saved: {result.report_path}")
        if result.model_usage:
            print(f"Model usage: {json.dumps(result.model_usage, ensure_ascii=False)}")
        print(f"Review command: erp-change review --run-id {result.run_id} --decision approve --reviewer NAME")
    elif args.command == "show":
        result = service.get(args.run_id)
        state = result["values"]
        print(state.get("report", "No report yet"))
        print(f"\nWorkflow next: {result['next'] or 'complete'}")
        if state.get("review"):
            print(f"Review: {json.dumps(state['review'], ensure_ascii=False)}")
    elif args.command == "review":
        review = service.review(args.run_id, service.get(args.run_id)["values"]["tenant_id"],
                                args.decision, args.reviewer, args.note)
        print(f"Run {args.run_id}: report review {review['decision']} by {review['reviewer']}")
        print("Report review does not authorize production changes.")
    elif args.command == "audit":
        print(json.dumps(service.audit_events(args.run_id), ensure_ascii=False, indent=2))
    elif args.command in {"issue-token", "revoke-token"}:
        store = TokenStore(service.data_dir / "api_tokens.sqlite")
        try:
            if args.command == "issue-token":
                print(store.issue(args.tenant, args.role, args.name))
            else:
                print("Revoked" if store.revoke(getpass.getpass("API token: ")) else "Token not found")
        finally:
            store.close()
    elif args.command == "serve":
        import uvicorn
        from .api import create_app

        uvicorn.run(create_app(root, sources_root=sources_root), host=args.host, port=args.port)
    elif args.command.startswith("memory-"):
        memory = ProjectMemory(service.data_dir / "memory.sqlite")
        try:
            valid_ids = {section.section_id for section in corpus.load(args.tenant)}
            if args.command == "memory-propose":
                if not set(args.citation) <= valid_ids:
                    raise ValueError("Citation missing or outside tenant corpus")
                fact_id = memory.propose(args.tenant, args.claim, args.citation, args.supersedes_id)
                print(f"Candidate fact {fact_id} saved; human approval required.")
            elif args.command == "memory-review":
                memory.review(args.fact_id, args.tenant, args.decision, args.reviewer, args.note)
                print(f"Fact {args.fact_id}: {args.decision}")
            else:
                print(json.dumps(memory.list(args.tenant), ensure_ascii=False, indent=2))
        finally:
            memory.close()


def main() -> None:
    try:
        _run(parser().parse_args())
    except (ValueError, RuntimeError, FileNotFoundError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
