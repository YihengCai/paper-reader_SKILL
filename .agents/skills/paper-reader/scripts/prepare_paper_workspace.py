#!/usr/bin/env python3

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import arxiv_api
import fetch_paper_pdf


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a timestamped paper workspace with paper.pdf, summary.md, and assets/."
    )
    parser.add_argument(
        "query",
        help="arXiv ID, arXiv URL, DOI-style arXiv identifier, paper title, or a local PDF path",
    )
    parser.add_argument(
        "--kind",
        choices=("auto", "id", "url", "title", "search"),
        default="auto",
        help="Interpretation of the positional query when it is not a local PDF path",
    )
    parser.add_argument(
        "--root-dir",
        default=".",
        help="Directory where the new paper workspace folder should be created",
    )
    parser.add_argument(
        "--summary-name",
        default="summary.md",
        help="Markdown summary filename inside the paper workspace",
    )
    parser.add_argument(
        "--assets-dir-name",
        default="assets",
        help="Assets subdirectory name inside the paper workspace",
    )
    parser.add_argument(
        "--pdf-name",
        default="paper.pdf",
        help="PDF filename inside the paper workspace",
    )
    parser.add_argument("--max-results", type=int, default=5, help="Maximum returned entries")
    parser.add_argument(
        "--sort-by",
        choices=("relevance", "lastUpdatedDate", "submittedDate"),
        default="relevance",
        help="arXiv API sortBy value for search/title queries",
    )
    parser.add_argument(
        "--sort-order",
        choices=("ascending", "descending"),
        default="descending",
        help="arXiv API sortOrder value for search/title queries",
    )
    parser.add_argument(
        "--no-relax",
        action="store_true",
        help="Do not fall back from exact-title search to all-fields phrase search",
    )
    parser.add_argument(
        "--user-agent",
        default=arxiv_api.DEFAULT_USER_AGENT,
        help="User-Agent header for API and PDF requests",
    )
    parser.add_argument("--timeout", type=int, default=30, help="Network timeout in seconds")
    parser.add_argument(
        "--cafile",
        help="Optional CA bundle path for TLS verification. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite summary.md if it already exists and re-download/re-copy the PDF",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of pretty-printed JSON",
    )
    return parser.parse_args()


def looks_like_local_pdf(query):
    candidate = Path(query).expanduser()
    return candidate.is_file() and candidate.suffix.lower() == ".pdf"


def sanitize_slug(value):
    return fetch_paper_pdf.sanitize_filename(value).replace("__", "_")


def timestamp_slug():
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def derive_folder_name(title, arxiv_id):
    title_slug = sanitize_slug(title or "paper")
    id_slug = sanitize_slug(arxiv_id or "no-arxiv")
    return f"{timestamp_slug()}_{title_slug}_{id_slug}"


def write_summary_stub(summary_path, title, pdf_name, assets_dir_name, arxiv_id=None, source_query=None):
    lines = [f"# {title or 'Paper Summary'}", ""]
    if arxiv_id:
        lines.append(f"- arXiv ID: `{arxiv_id}`")
    if source_query and source_query != title:
        lines.append(f"- Source Query: `{source_query}`")
    lines.extend(
        [
            f"- PDF: [{pdf_name}]({pdf_name})",
            f"- Assets: [{assets_dir_name}/]({assets_dir_name}/)",
            "",
            "## 一句话总结",
            "",
            "## 问题背景",
            "",
            "## 核心方法",
            "",
            "## 实验与结果",
            "",
            "## 局限与讨论",
            "",
            "## 读完这篇论文你应该记住的几个点",
            "",
            "<!-- Use relative image links like ![Figure](assets/figure-1.png) -->",
            "",
        ]
    )
    summary_path.write_text("\n".join(lines), encoding="utf-8")


def prepare_from_local_pdf(args):
    source_pdf = Path(args.query).expanduser().resolve()
    title = source_pdf.stem
    arxiv_id = arxiv_api.normalize_candidate_id(source_pdf.stem)
    workspace_name = derive_folder_name(title, arxiv_id)
    root_dir = Path(args.root_dir).expanduser().resolve()
    workspace_dir = root_dir / workspace_name
    assets_dir = workspace_dir / args.assets_dir_name
    summary_path = workspace_dir / args.summary_name
    pdf_path = workspace_dir / args.pdf_name

    workspace_dir.mkdir(parents=True, exist_ok=False)
    assets_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, pdf_path)
    write_summary_stub(
        summary_path,
        title=title,
        pdf_name=pdf_path.name,
        assets_dir_name=assets_dir.name,
        arxiv_id=arxiv_id,
        source_query=args.query,
    )
    return {
        "input": args.query,
        "entry": {
            "title": title,
            "arxiv_id": arxiv_id,
            "abstract_url": None,
            "pdf_url": None,
        },
        "workspace": {
            "directory": str(workspace_dir),
            "summary_markdown": str(summary_path),
            "assets_directory": str(assets_dir),
            "pdf_path": str(pdf_path),
            "created_from_local_pdf": True,
        },
    }


def resolve_entry_from_query(args):
    resolved_payload = arxiv_api.resolve_query(
        raw_query=args.query,
        kind=args.kind,
        max_results=args.max_results,
        sort_by=args.sort_by,
        sort_order=args.sort_order,
        allow_relax=not args.no_relax,
        user_agent=args.user_agent,
        timeout=args.timeout,
        cafile=args.cafile,
    )
    entry = fetch_paper_pdf.choose_entry(resolved_payload["entries"], args.query)
    if entry is None:
        entry = fetch_paper_pdf.fallback_entry(args.query)
    if entry is None:
        raise RuntimeError(f"No arXiv entry found for query: {args.query}")
    return resolved_payload, entry


def prepare_from_arxiv(args):
    root_dir = Path(args.root_dir).expanduser().resolve()
    _, entry = resolve_entry_from_query(args)
    workspace_name = derive_folder_name(entry.get("title"), entry.get("arxiv_id"))
    workspace_dir = root_dir / workspace_name
    assets_dir = workspace_dir / args.assets_dir_name
    summary_path = workspace_dir / args.summary_name
    pdf_path = workspace_dir / args.pdf_name

    workspace_dir.mkdir(parents=True, exist_ok=False)
    assets_dir.mkdir(parents=True, exist_ok=True)

    resolved = fetch_paper_pdf.resolve_and_download(
        raw_query=args.query,
        kind=args.kind,
        output=str(pdf_path),
        output_dir=str(workspace_dir),
        filename=pdf_path.name,
        overwrite=args.overwrite,
        max_results=args.max_results,
        sort_by=args.sort_by,
        sort_order=args.sort_order,
        allow_relax=not args.no_relax,
        user_agent=args.user_agent,
        timeout=args.timeout,
        cafile=args.cafile,
    )
    write_summary_stub(
        summary_path,
        title=entry.get("title") or "Paper Summary",
        pdf_name=pdf_path.name,
        assets_dir_name=assets_dir.name,
        arxiv_id=entry.get("arxiv_id"),
        source_query=args.query,
    )
    resolved["workspace"] = {
        "directory": str(workspace_dir),
        "summary_markdown": str(summary_path),
        "assets_directory": str(assets_dir),
        "pdf_path": str(pdf_path),
        "created_from_local_pdf": False,
    }
    return resolved


def main():
    args = parse_args()
    if "/" in args.summary_name or "/" in args.assets_dir_name or "/" in args.pdf_name:
        raise SystemExit("summary-name, assets-dir-name, and pdf-name must be plain names")

    try:
        if looks_like_local_pdf(args.query):
            payload = prepare_from_local_pdf(args)
        else:
            payload = prepare_from_arxiv(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
