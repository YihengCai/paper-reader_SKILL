#!/usr/bin/env python3

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


API_URL = "https://export.arxiv.org/api/query"
DEFAULT_USER_AGENT = "paper-reader/0.1 (+Codex local skill; respect 1req-per-3s)"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}

NEW_STYLE_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
OLD_STYLE_ID_RE = re.compile(r"^[A-Za-z-]+(?:\.[A-Za-z-]+)?/\d{7}(v\d+)?$")
DOI_STYLE_ID_RE = re.compile(r"^10\.48550/arXiv\.(.+)$", re.IGNORECASE)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Resolve arXiv IDs, URLs, titles, or raw API queries into structured JSON."
    )
    parser.add_argument("query", help="arXiv ID, arXiv URL, paper title, or raw API search query")
    parser.add_argument(
        "--kind",
        choices=("auto", "id", "url", "title", "search"),
        default="auto",
        help="Interpretation of the positional query",
    )
    parser.add_argument("--start", type=int, default=0, help="API result offset")
    parser.add_argument("--max-results", type=int, default=5, help="Maximum returned entries")
    parser.add_argument(
        "--sort-by",
        choices=("relevance", "lastUpdatedDate", "submittedDate"),
        default="relevance",
        help="arXiv API sortBy value",
    )
    parser.add_argument(
        "--sort-order",
        choices=("ascending", "descending"),
        default="descending",
        help="arXiv API sortOrder value",
    )
    parser.add_argument(
        "--no-relax",
        action="store_true",
        help="Do not fall back from title-only search to all-fields phrase search",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header for the request",
    )
    parser.add_argument("--timeout", type=int, default=20, help="Network timeout in seconds")
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


def normalize_whitespace(text):
    return " ".join(text.split()) if text else ""


def existing_file(path):
    return bool(path) and os.path.isfile(path)


def is_arxiv_id(value):
    return bool(NEW_STYLE_ID_RE.fullmatch(value) or OLD_STYLE_ID_RE.fullmatch(value))


def extract_id_from_url(value):
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    host = parsed.netloc.lower()
    if host not in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
        return None

    path = parsed.path.strip("/")
    if path.startswith("abs/"):
        return path[4:] or None
    if path.startswith("pdf/"):
        path = path[4:]
        if path.endswith(".pdf"):
            path = path[:-4]
        return path or None
    return None


def normalize_candidate_id(value):
    value = value.strip()
    doi_match = DOI_STYLE_ID_RE.fullmatch(value)
    if doi_match:
        value = doi_match.group(1)

    url_id = extract_id_from_url(value)
    if url_id:
        value = url_id

    return value if is_arxiv_id(value) else None


def build_attempts(raw_query, kind, allow_relax):
    normalized_id = None
    if kind in ("auto", "id", "url"):
        normalized_id = normalize_candidate_id(raw_query)

    detected_kind = kind
    if kind == "auto":
        if normalized_id:
            detected_kind = "id"
        elif extract_id_from_url(raw_query):
            detected_kind = "url"
        else:
            detected_kind = "title"

    attempts = []
    if detected_kind in ("id", "url"):
        if not normalized_id:
            raise ValueError(f"Could not extract a valid arXiv identifier from: {raw_query}")
        attempts.append(
            {
                "label": "id_list",
                "resolved_kind": "id",
                "params": {"id_list": normalized_id},
            }
        )
    elif detected_kind == "search":
        attempts.append(
            {
                "label": "raw-search-query",
                "resolved_kind": "search",
                "params": {"search_query": raw_query},
            }
        )
    else:
        exact_title = f'ti:"{raw_query}"'
        attempts.append(
            {
                "label": "title-exact",
                "resolved_kind": "title",
                "params": {"search_query": exact_title},
            }
        )
        if allow_relax:
            relaxed = f'all:"{raw_query}"'
            attempts.append(
                {
                    "label": "title-relaxed-all-fields",
                    "resolved_kind": "title",
                    "params": {"search_query": relaxed},
                }
            )

    return detected_kind, attempts


def resolve_cafile(explicit_cafile=None):
    candidates = []
    if explicit_cafile:
        candidates.append(explicit_cafile)

    env_cafile = os.environ.get("SSL_CERT_FILE")
    if env_cafile:
        candidates.append(env_cafile)

    verify_paths = ssl.get_default_verify_paths()
    candidates.extend(
        [
            verify_paths.cafile,
            verify_paths.openssl_cafile,
            "/etc/ssl/cert.pem",
        ]
    )

    try:
        import certifi  # type: ignore

        candidates.append(certifi.where())
    except ImportError:
        pass

    seen = set()
    for path in candidates:
        if not path:
            continue
        normalized = os.path.abspath(os.path.expanduser(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if existing_file(normalized):
            return normalized
    return None


def fetch_feed(params, user_agent, timeout, cafile=None):
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    context = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return url, response.read()


def text_or_none(node, path):
    child = node.find(path, ATOM_NS)
    if child is None or child.text is None:
        return None
    return normalize_whitespace(child.text)


def https_url(value):
    if not value:
        return None
    if value.startswith("http://"):
        return "https://" + value[len("http://") :]
    return value


def parse_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)

    feed = {
        "title": text_or_none(root, "atom:title"),
        "id": text_or_none(root, "atom:id"),
        "updated": text_or_none(root, "atom:updated"),
        "total_results": int(text_or_none(root, "opensearch:totalResults") or 0),
        "start_index": int(text_or_none(root, "opensearch:startIndex") or 0),
        "items_per_page": int(text_or_none(root, "opensearch:itemsPerPage") or 0),
    }

    entries = []
    for entry in root.findall("atom:entry", ATOM_NS):
        entry_id_url = text_or_none(entry, "atom:id")
        title = text_or_none(entry, "atom:title")
        summary = text_or_none(entry, "atom:summary")

        authors = []
        affiliations = []
        for author in entry.findall("atom:author", ATOM_NS):
            name = text_or_none(author, "atom:name")
            if name:
                authors.append(name)
            affiliation = text_or_none(author, "arxiv:affiliation")
            if affiliation:
                affiliations.append({"author": name, "affiliation": affiliation})

        categories = []
        for category in entry.findall("atom:category", ATOM_NS):
            term = category.attrib.get("term")
            if term:
                categories.append(term)

        abstract_url = None
        pdf_url = None
        doi_url = None
        for link in entry.findall("atom:link", ATOM_NS):
            rel = link.attrib.get("rel")
            title_attr = link.attrib.get("title")
            href = https_url(link.attrib.get("href"))
            if rel == "alternate":
                abstract_url = href
            elif rel == "related" and title_attr == "pdf":
                pdf_url = href
            elif rel == "related" and title_attr == "doi":
                doi_url = href

        arxiv_id = None
        if entry_id_url and "/abs/" in entry_id_url:
            arxiv_id = entry_id_url.split("/abs/", 1)[1]

        parsed_entry = {
            "title": title,
            "id_url": https_url(entry_id_url),
            "arxiv_id": arxiv_id,
            "published": text_or_none(entry, "atom:published"),
            "updated": text_or_none(entry, "atom:updated"),
            "summary": summary,
            "authors": authors,
            "affiliations": affiliations,
            "primary_category": (
                entry.find("arxiv:primary_category", ATOM_NS).attrib.get("term")
                if entry.find("arxiv:primary_category", ATOM_NS) is not None
                else None
            ),
            "categories": categories,
            "comment": text_or_none(entry, "arxiv:comment"),
            "journal_ref": text_or_none(entry, "arxiv:journal_ref"),
            "doi": text_or_none(entry, "arxiv:doi"),
            "doi_url": doi_url,
            "abstract_url": abstract_url,
            "pdf_url": pdf_url,
        }
        entries.append(parsed_entry)

    if len(entries) == 1 and entries[0]["title"] == "Error":
        raise RuntimeError(entries[0]["summary"] or "arXiv API returned an error feed")

    return feed, entries


def resolve_query(
    raw_query,
    *,
    kind="auto",
    start=0,
    max_results=5,
    sort_by="relevance",
    sort_order="descending",
    allow_relax=True,
    user_agent=DEFAULT_USER_AGENT,
    timeout=20,
    cafile=None,
):
    requested_cafile = None
    if cafile:
        requested_cafile = os.path.abspath(os.path.expanduser(cafile))
        if not existing_file(requested_cafile):
            raise FileNotFoundError(f"CA bundle not found: {requested_cafile}")

    resolved_cafile = resolve_cafile(requested_cafile)
    detected_kind, attempts = build_attempts(
        raw_query=raw_query,
        kind=kind,
        allow_relax=allow_relax,
    )

    api_attempts = []
    selected = None
    last_feed = None
    last_entries = []

    for attempt in attempts:
        params = dict(attempt["params"])
        params.setdefault("start", start)
        params.setdefault("max_results", max_results)
        if "search_query" in params:
            params.setdefault("sortBy", sort_by)
            params.setdefault("sortOrder", sort_order)

        query_url, xml_bytes = fetch_feed(
            params=params,
            user_agent=user_agent,
            timeout=timeout,
            cafile=resolved_cafile,
        )
        feed, entries = parse_feed(xml_bytes)

        api_attempts.append(
            {
                "label": attempt["label"],
                "resolved_kind": attempt["resolved_kind"],
                "params": params,
                "query_url": query_url,
                "total_results": feed["total_results"],
                "returned_entries": len(entries),
            }
        )
        last_feed = feed
        last_entries = entries

        if entries or attempt is attempts[-1]:
            selected = {
                "label": attempt["label"],
                "resolved_kind": attempt["resolved_kind"],
                "params": params,
                "query_url": query_url,
            }
            break

    return {
        "input": raw_query,
        "detected_kind": detected_kind,
        "tls_cafile": resolved_cafile,
        "selected_query": selected,
        "attempts": api_attempts,
        "feed": last_feed,
        "entries": last_entries,
    }


def main():
    args = parse_args()
    try:
        payload = resolve_query(
            raw_query=args.query,
            kind=args.kind,
            start=args.start,
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
        cafile_hint = f" (CA bundle: {resolve_cafile(args.cafile)})" if resolve_cafile(args.cafile) else ""
        print(f"arXiv API TLS error{cafile_hint}: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
