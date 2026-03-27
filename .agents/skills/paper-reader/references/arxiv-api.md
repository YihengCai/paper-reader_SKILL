# arXiv API Notes

Use the official metadata API endpoint:

```text
https://export.arxiv.org/api/query
```

## Query parameters
- `search_query`: free-form API query.
- `id_list`: exact arXiv identifiers. Prefer this over `search_query=id:...`.
- `start`: zero-based offset.
- `max_results`: number of returned entries. Requests above `30000` fail.
- `sortBy`: `relevance`, `lastUpdatedDate`, or `submittedDate`.
- `sortOrder`: `ascending` or `descending`.

## Query patterns
- Exact arXiv paper: `id_list=2401.12345`
- Specific version: `id_list=2401.12345v1`
- Exact title phrase: `search_query=ti:"Attention Is All You Need"`
- Fallback broader phrase: `search_query=all:"Attention Is All You Need"`
- Author filter: `search_query=au:del_maestro`
- Boolean composition: `au:del_maestro AND ti:checkerboard`

## Search field prefixes
- `ti`: title
- `au`: author
- `abs`: abstract
- `co`: comment
- `jr`: journal reference
- `cat`: subject category
- `rn`: report number
- `all`: all searchable fields

Use double quotes for phrases. Use `AND`, `OR`, and `ANDNOT` for Boolean logic.

## Response shape
The API returns Atom XML. Relevant feed fields:
- `opensearch:totalResults`
- `opensearch:startIndex`
- `opensearch:itemsPerPage`

Relevant entry fields:
- `title`
- `id`
- `published`
- `updated`
- `summary`
- `author`
- `category`
- `arxiv:primary_category`
- `arxiv:comment`
- `arxiv:journal_ref`
- `arxiv:doi`
- `link rel="alternate"` for the abstract page
- `link title="pdf"` for the PDF

## Limits
- Respect arXiv's legacy API rate limit: at most one request every three seconds.
- Keep to a single connection at a time.
- Refine searches instead of pulling very large result sets.

## Workflow guidance
- For exact IDs or canonical URLs, use `id_list`.
- For title-only input, try `ti:"..."` first, then relax to `all:"..."` if needed.
- When multiple candidates remain, show the top few results and state which one you selected.
- Metadata lookups are fine to store and transform. Do not mirror PDFs unless the user explicitly asks and licensing allows it.
