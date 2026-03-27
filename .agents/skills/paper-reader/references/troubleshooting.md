# Troubleshooting

Use this reference only when the normal `paper-reader` workflow fails.

## arXiv API TLS failures on macOS Python

- Symptom: `arxiv_api.py` fails with `CERTIFICATE_VERIFY_FAILED`.
- Common cause: the active `python3` points at a Python.org framework build whose default OpenSSL CA path does not exist.
- Current script behavior: `scripts/arxiv_api.py` now auto-detects a usable CA bundle and falls back to `/etc/ssl/cert.pem` when needed.
- Manual override: pass `--cafile /etc/ssl/cert.pem` or set `SSL_CERT_FILE=/etc/ssl/cert.pem`.
- Quick diagnosis:

```bash
python3 -c 'import ssl; print(ssl.get_default_verify_paths())'
ls -l /etc/ssl/cert.pem
```

## Network sandbox vs. local network

- Symptom: `nodename nor servname provided, or not known`.
- Likely cause inside Codex: network sandboxing blocked the request before DNS resolution.
- Distinguish it from a local network issue by checking whether `curl` can reach arXiv when network access is allowed.
- For a full paper-reading task, do not stop at this error and do not fall back to a chat-only answer. Continue with an allowed network path if available, then still create the paper workspace and write `summary.md`.

## PDF download failures

- Preferred full workflow: `scripts/prepare_paper_workspace.py`. It creates the timestamped paper folder, downloads `paper.pdf`, creates `summary.md`, and prepares `assets/`.
- For full reads, `scripts/arxiv_api.py` is no longer the first command. It is only a metadata helper and troubleshooting tool.
- If you only need the PDF itself, use `scripts/fetch_paper_pdf.py`, not ad-hoc `curl`.
- `fetch_paper_pdf.py` resolves arXiv IDs and titles through `arxiv_api.py`, reuses valid cached PDFs, and rejects HTML/error pages that were saved with a `.pdf` suffix.
- If a script reports `downloaded content is not a PDF`, inspect the preview in stderr; arXiv or an intermediate proxy likely returned HTML instead of the binary PDF.
- If the API lookup fails but the input is an exact arXiv ID or URL, `fetch_paper_pdf.py` can still fall back to direct PDF URLs. For title-only queries, you need API access.
- TLS fixes are the same as for `arxiv_api.py`: try `--cafile /etc/ssl/cert.pem` if Python cannot verify arXiv's certificate.
- Example:

```bash
python3 .agents/skills/paper-reader/scripts/prepare_paper_workspace.py "2401.12345" --cafile /etc/ssl/cert.pem
```

## PDF rendering tools

- Best renderer for this skill: Poppler, specifically `pdftocairo` or `pdftoppm`.
- Why: `scripts/render_pdf_pages.py` supports arbitrary pages with Poppler and only falls back to `qlmanage` on macOS.
- Limitation of fallback: `qlmanage` can only render the first page in this workflow, so it is not sufficient for most figure/table extraction tasks.
- Install on macOS with Homebrew:

```bash
brew install poppler
```

## Figure and Table Cropping

- `scripts/render_pdf_pages.py` accepts `--crop left,top,right,bottom`.
- Accepted units:
  - Fractions from `0` to `1`
  - Percentages like `8%,16%,92%,57%`
  - Pixels
- The crop is applied after rendering and produces `*-crop.png` files by default.
- On macOS, cropping uses `/usr/bin/sips`.
- Example:

```bash
python3 .agents/skills/paper-reader/scripts/render_pdf_pages.py paper.pdf --pages 5 --crop 8%,16%,92%,57%
```
