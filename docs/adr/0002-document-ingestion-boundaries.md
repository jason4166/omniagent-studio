# ADR 0002: Document ingestion and chunk identity boundaries

## Status

Accepted for the Day 10 local implementation.

## Context

OmniAgent Studio needs a small offline ingestion path for synthetic TXT, Markdown, and PDF files before embeddings or vector retrieval exist. The path must preserve source provenance, reject unsupported scanned PDFs honestly, produce reproducible chunks, and make repeated imports safe.

## Decision

### Pipeline boundaries

The pipeline is `raw bytes -> parser -> ParsedDocument/ParsedUnit -> chunker -> DocumentChunk -> future index`.

- Parsing decodes or extracts text and records parser metadata.
- Normalization canonicalizes line endings and trailing whitespace before character offsets are assigned.
- `ParsedUnit` is the semantic hierarchy: a TXT document, Markdown section, or PDF page.
- Chunking applies a fixed-size overlapping window inside each unit and never crosses a section or page boundary.
- Metadata locates each chunk by source, knowledge base, unit, page or section, and half-open character range.
- Indexing is not implemented on Day 10. Chunks are stored in an in-memory repository only.

### Identity and rebuild rules

- `checksum` is SHA-256 over the original bytes. It detects exact byte equality and is unaffected by parser behavior.
- `source_id` hashes knowledge-base ID, case-folded source name, and checksum. Repeating the same named source in the same KB is idempotent. Equal content under different names remains distinct because equal content does not prove file identity.
- `chunk_id` hashes source identity, checksum, chunking version, size, overlap, range, and chunk content.
- Reimport with the same source and configuration returns `duplicate` without adding records.
- Reimport with the same source and a changed chunk configuration preserves original bytes and parsed source, replaces chunks and metadata, generates new chunk IDs, and returns `rebuilt`.

### PDF library boundary

The implementation pins `pypdf==6.16.2` and records parser version `pypdf-6.16.2-v1`. It uses `PdfReader(BytesIO(raw_bytes), strict=False)` and `page.extract_text()` only. The current official pypdf documentation states that pypdf is not OCR software and cannot extract text from images. A PDF for which every page yields no extractable text returns `scanned_pdf_unsupported`; OCR is outside Day 10.

Official references checked on 2026-09-01:

- <https://pypdf.readthedocs.io/en/stable/user/extract-text.html>
- <https://pypdf.readthedocs.io/en/stable/user/installation.html>
- <https://pypi.org/project/pypdf/>

### API and error boundary

- `POST /api/knowledge-bases` creates a minimal knowledge base.
- `POST /api/knowledge-bases/{knowledge_base_id}/sources` reads at most 1 MiB plus one detection byte and returns source, status, checksum, chunk count, and a classified error when applicable.
- Accepted extension/MIME pairs are `.txt`/`text/plain`, `.md` or `.markdown`/`text/markdown`, and `.pdf`/`application/pdf`.
- Client filenames are reduced to their final component. Parser exceptions are mapped to fixed public messages; local paths and underlying exception text are not returned.

Result statuses are `imported`, `duplicate`, `rebuilt`, `rejected`, `unsupported`, and `failed`. Error categories cover missing filename, upload size, extension, MIME mismatch, invalid UTF-8, empty text, invalid PDF, and scanned PDF without a text layer.

### Fixtures and evidence

All Day 10 fixtures are authored synthetic content. The two PDFs are generated locally by `scripts/build_day10_pdf_fixtures.py`; one has two digital text pages and one contains only an image. No personal documents, real user data, private prompts, or unclear copyrighted material are included.

## Consequences

The design exposes parsing, normalization, hierarchy, overlap, hashing, and error mapping in ordinary Python. It does not add embeddings, a vector database, production retrieval, OCR, citations, reranking, LangGraph, or persistent object storage. The in-memory repository proves contracts and idempotency only.

## Architecture terms

- Content-addressed checksum: a digest derived from original bytes.
- Stable identity: an ID reproducible from canonical inputs rather than a random UUID.
- Idempotent import: repeating the same operation does not create duplicate state.
- Derived artifact: a chunk or metadata record that can be rebuilt from preserved source data and configuration.
- Semantic unit: a page or section boundary used before fixed-window chunking.
- Half-open range: `[start, end)`, including `start` and excluding `end`.
- Repository: the storage boundary for KBs, sources, original bytes, and chunks.
- Service: the orchestration boundary for validation, parsing, deduplication, rebuild, and persistence.

## Day 11 upload checklist

- Replace in-memory original-byte storage with a bounded object-storage adapter.
- Keep extension, MIME, and size validation before parsing.
- Add authenticated ownership and authorization for KB/source access.
- Add malware scanning and quarantine before accepted files become readable.
- Persist source/chunk transactions atomically and define rollback behavior.
- Keep raw uploads and extracted text out of logs.
- Add retention, deletion, audit, and observability policies using synthetic test data.
