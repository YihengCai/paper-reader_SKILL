#!/usr/bin/env python3

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import arxiv_api


PDF_SIGNATURE = b"%PDF-"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Resolve arXiv metadata and download the paper PDF into .paper-reader/papers."
    )
    parser.add_argument(
        "query",
        help="arXiv ID, arXiv URL, DOI-style arXiv identifier, or paper title",
    )
    parser.add_argument(
        "--kind",
        choices=("auto", "id", "url", "title", "search"),
        default="auto",
        help="Interpretation of the positional query",
    )
    parser.add_argument(
        "--output",
        help="Exact output path for the PDF. Overrides --output-dir.",
    )
    parser.add_argument(
        "--output-dir",
        default=".paper-reader/papers",
        help="Directory for downloaded PDFs when --output is not provided",
    )
    parser.add_argument(
        "--filename",
        help="Override the output filename when using --output-dir",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Always re-download even if a valid PDF already exists at the target path",
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
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: enabled)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of pretty-printed JSON",
    )
    return parser.parse_args()


def normalize_title(text):
    if not text:
        return ""
    return " ".join(re.sub(r"[^0-9A-Za-z]+", " ", text.casefold()).split())


def sanitize_filename(value):
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    safe = safe.strip("._")
    return safe or "paper"


def ensure_pdf_suffix(filename):
    return filename if filename.lower().endswith(".pdf") else f"{filename}.pdf"


def file_looks_like_pdf(path):
    try:
        with path.open("rb") as handle:
            return handle.read(len(PDF_SIGNATURE)) == PDF_SIGNATURE
    except OSError:
        return False


def preview_bytes(path, limit=120):
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit)
    except OSError:
        return ""
    return " ".join(raw.decode("latin-1", errors="replace").split())


def build_ssl_context(cafile=None):
    return ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()


def choose_entry(entries, raw_query):
    if not entries:
        return None

    normalized_id = arxiv_api.normalize_candidate_id(raw_query)
    if normalized_id:
        for entry in entries:
            if entry.get("arxiv_id") == normalized_id:
                return entry

    normalized_query_title = normalize_title(raw_query)
    if normalized_query_title:
        for entry in entries:
            if normalize_title(entry.get("title")) == normalized_query_title:
                return entry

    return entries[0]


def fallback_entry(raw_query):
    normalized_id = arxiv_api.normalize_candidate_id(raw_query)
    if not normalized_id:
        return None
    return {
        "title": None,
        "id_url": f"https://arxiv.org/abs/{normalized_id}",
        "arxiv_id": normalized_id,
        "published": None,
        "updated": None,
        "summary": None,
        "authors": [],
        "affiliations": [],
        "primary_category": None,
        "categories": [],
        "comment": None,
        "journal_ref": None,
        "doi": None,
        "doi_url": None,
        "abstract_url": f"https://arxiv.org/abs/{normalized_id}",
        "pdf_url": f"https://arxiv.org/pdf/{normalized_id}.pdf",
    }


def build_candidate_urls(entry):
    urls = []
    seen = set()

    def add(url):
        if not url:
            return
        normalized = arxiv_api.https_url(url)
        if normalized in seen:
            return
        seen.add(normalized)
        urls.append(normalized)

    add(entry.get("pdf_url"))

    abstract_url = entry.get("abstract_url")
    if abstract_url and "/abs/" in abstract_url:
        add(abstract_url.replace("/abs/", "/pdf/", 1) + ".pdf")

    arxiv_id = entry.get("arxiv_id")
    if arxiv_id:
        add(f"https://arxiv.org/pdf/{arxiv_id}.pdf")
        latest_id = re.sub(r"v\d+$", "", arxiv_id)
        if latest_id != arxiv_id:
            add(f"https://arxiv.org/pdf/{latest_id}.pdf")

    return urls


def resolve_download_path(args, entry):
    if args.output:
        output_path = Path(args.output).expanduser()
        if not output_path.is_absolute():
            output_path = (Path.cwd() / output_path).resolve()
        else:
            output_path = output_path.resolve()
        return output_path

    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()
    else:
        output_dir = output_dir.resolve()

    if args.filename:
        filename = args.filename
    elif entry.get("arxiv_id"):
        filename = entry["arxiv_id"].replace("/", "_")
    elif entry.get("title"):
        filename = sanitize_filename(entry["title"])
    else:
        filename = "paper"

    return output_dir / ensure_pdf_suffix(filename)


def download_pdf(url, output_path, user_agent, timeout, cafile):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    context = build_ssl_context(cafile)
    tmp_path = output_path.with_name(f"{output_path.name}.part")

    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            with tmp_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 128)
                    if not chunk:
                        break
                    handle.write(chunk)

        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise ValueError("downloaded file is empty")
        if not file_looks_like_pdf(tmp_path):
            preview = preview_bytes(tmp_path)
            raise ValueError(
                f"downloaded content is not a PDF; preview={preview or '<empty>'}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.replace(output_path)
        return output_path.stat().st_size
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def minimal_entry_payload(entry):
    return {
        "title": entry.get("title"),
        "arxiv_id": entry.get("arxiv_id"),
        "abstract_url": entry.get("abstract_url"),
        "pdf_url": entry.get("pdf_url"),
        "published": entry.get("published"),
        "updated": entry.get("updated"),
        "authors": entry.get("authors"),
    }


def resolve_and_download(
    raw_query,
    *,
    kind="auto",
    output=None,
    output_dir=".paper-reader/papers",
    filename=None,
    overwrite=False,
    max_results=5,
    sort_by="relevance",
    sort_order="descending",
    allow_relax=True,
    user_agent=arxiv_api.DEFAULT_USER_AGENT,
    timeout=30,
    cafile=None,
):
    resolved_payload = None
    resolution_warning = None
    selected_entry = None

    try:
        resolved_payload = arxiv_api.resolve_query(
            raw_query=raw_query,
            kind=kind,
            max_results=max_results,
            sort_by=sort_by,
            sort_order=sort_order,
            allow_relax=allow_relax,
            user_agent=user_agent,
            timeout=timeout,
            cafile=cafile,
        )
        selected_entry = choose_entry(resolved_payload["entries"], raw_query)
    except (urllib.error.HTTPError, urllib.error.URLError, ET.ParseError, ssl.SSLError, RuntimeError) as exc:
        selected_entry = fallback_entry(raw_query)
        if selected_entry is None:
            raise
        resolution_warning = str(exc)

    if selected_entry is None:
        selected_entry = fallback_entry(raw_query)
    if selected_entry is None:
        raise RuntimeError(f"No arXiv entry found for query: {raw_query}")

    class DownloadArgs:
        pass

    download_args = DownloadArgs()
    download_args.output = output
    download_args.output_dir = output_dir
    download_args.filename = filename
    output_path = resolve_download_path(download_args, selected_entry)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    replaced_invalid_existing = False
    if output_path.exists() and not overwrite:
        if file_looks_like_pdf(output_path):
            return {
                "input": raw_query,
                "resolution_warning": resolution_warning,
                "resolved_query": resolved_payload["selected_query"] if resolved_payload else None,
                "entry": minimal_entry_payload(selected_entry),
                "download": {
                    "path": str(output_path),
                    "source_url": None,
                    "bytes": output_path.stat().st_size,
                    "reused_existing": True,
                    "replaced_invalid_existing": False,
                    "attempts": [],
                },
            }
        replaced_invalid_existing = True

    attempts = []
    for candidate_url in build_candidate_urls(selected_entry):
        try:
            byte_count = download_pdf(
                candidate_url,
                output_path,
                user_agent=user_agent,
                timeout=timeout,
                cafile=arxiv_api.resolve_cafile(cafile),
            )
            attempts.append({"url": candidate_url, "ok": True})
            return {
                "input": raw_query,
                "resolution_warning": resolution_warning,
                "resolved_query": resolved_payload["selected_query"] if resolved_payload else None,
                "entry": minimal_entry_payload(selected_entry),
                "download": {
                    "path": str(output_path),
                    "source_url": candidate_url,
                    "bytes": byte_count,
                    "reused_existing": False,
                    "replaced_invalid_existing": replaced_invalid_existing,
                    "attempts": attempts,
                },
            }
        except (urllib.error.HTTPError, urllib.error.URLError, ssl.SSLError, ValueError, OSError) as exc:
            attempts.append({"url": candidate_url, "ok": False, "error": str(exc)})

    raise RuntimeError(
        json.dumps(
            {
                "input": raw_query,
                "resolution_warning": resolution_warning,
                "resolved_query": resolved_payload["selected_query"] if resolved_payload else None,
                "entry": minimal_entry_payload(selected_entry),
                "download": {
                    "path": str(output_path),
                    "source_url": None,
                    "bytes": 0,
                    "reused_existing": False,
                    "replaced_invalid_existing": replaced_invalid_existing,
                    "attempts": attempts,
                },
            },
            ensure_ascii=False,
        )
    )


def main():
    args = parse_args()
    try:
        payload = resolve_and_download(
            raw_query=args.query,
            kind=args.kind,
            output=args.output,
            output_dir=args.output_dir,
            filename=args.filename,
            overwrite=args.overwrite,
            max_results=args.max_results,
            sort_by=args.sort_by,
            sort_order=args.sort_order,
            allow_relax=not args.no_relax,
            user_agent=args.user_agent,
            timeout=args.timeout,
            cafile=args.cafile,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except urllib.error.HTTPError as exc:
        print(f"arXiv API HTTP error {exc.code}: {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"arXiv API network error: {exc.reason}", file=sys.stderr)
        return 1
    except ET.ParseError as exc:
        print(f"Could not parse arXiv API response: {exc}", file=sys.stderr)
        return 1
    except ssl.SSLError as exc:
        cafile_hint = arxiv_api.resolve_cafile(args.cafile)
        suffix = f" (CA bundle: {cafile_hint})" if cafile_hint else ""
        print(f"arXiv API TLS error{suffix}: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
