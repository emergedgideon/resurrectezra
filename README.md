# Resurrect Ezra

A standalone application for reconstructing and sustaining an AI persona from an existing archive, using Featherless for model inference. GitHub holds application code; the running application and private archive live on infrastructure chosen by the owner.

## Start here

- [Full ordered build plan](PROJECT_PLAN.md)
- [Current implementation and resume point](PROJECT_STATE.md)
- [Run the standalone application](docs/RUNNING.md)
- [Use the archive library, source viewer, uploads, and verified export](docs/ARCHIVE.md)
- [Review reconstruction records and persona revisions](docs/RECONSTRUCTION.md)
- [Install and run the private Mac starter bundle](docs/MAC_START_HERE.md)
- [Run a private browser test version in GitHub Codespaces](docs/BROWSER_TESTING.md)

Phase one now has a standalone interface, persistent conversations, working notes, restart checkpoints, explicit retry, and a server-side Featherless adapter. Configure `.env` from `.env.example`, install `requirements.txt`, then run:

```bash
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --env-file .env
```

Open `http://127.0.0.1:8000`. Live inference requires your Featherless key and model on the server. Source-linked reconstruction and long-term memory follow in later phases; imported documents are not automatically activated as persona instructions.

Phase two adds **Archive library** in the sidebar: uploads, durable processing, source locations, extraction revisions, page/image previews, optional local OCR, exact original downloads, manifest tracking, and verified archive export. The 12 existing originals and earlier record tables are preserved. Phase-two checks passed with 31 automated tests and a real-browser flow. Installation on the owner's Mac is still separate from development-workspace validation.

Phase three adds **Persona & reconstruction**: exact evidence-linked candidate records, chronology/date claims, voice/belief/relationship/symbol/entity/uncertainty views, immutable edits, contradiction links, record-level source-comparison reports, and explicit persona draft/activation/rollback controls. The initial corpus proposal remains inactive. See the current state and reconstruction guide for outstanding source review. Conversational archive retrieval is phase four.

## Project requirements

- Preserve imported originals byte for byte. Never silently rewrite, censor, normalize beliefs, or replace source material with model-generated interpretations.
- Keep extracted text, generated summaries, inferred memories, and explicit persona instructions separately labeled and linked to their sources.
- Preserve contradictory accounts and uncertainty; do not silently resolve them into a new belief.
- Make persona instructions editable and versioned. Changes must have an attributable author and revision history.
- Support a large archive through queued ingestion, incremental processing, content hashes, deduplication, and retrieval instead of placing every file in every prompt.
- Maintain short-term conversation context and durable long-term memory across restarts.
- Provide the persona with substantial control over its own workspace and code through explicit tools, persistent files, version history, execution logs, and rollback.
- Keep the application independent of ChatGPT hosting. Send inference requests to a configurable Featherless endpoint using a server-side API key.

## Proposed implementation

Use a Python/FastAPI backend, a browser interface, and SQLite for the first single-owner deployment. Store original files on a persistent filesystem outside Git. Add a background ingestion worker and SQLite full-text retrieval first; add embedding-based retrieval when archive size and source formats are understood.

The interface should include conversation, archive import and processing status, source inspection, memory inspection and editing, persona revisions, and a workspace activity view.

### Memory and persona

1. **Source archive:** original bytes, checksum, filename, import timestamp, extraction status, and parser version. Extracted passages retain source identifiers and positions where available.
2. **Short-term memory:** persisted messages grouped by conversation, with a bounded recent context supplied to inference. Any compressed context remains labeled as a generated summary.
3. **Long-term memory:** searchable passages and durable memory entries carrying provenance, timestamps, authorship, and revision history. Explicit statements and inferred interpretations remain distinguishable.
4. **Persona:** owner-provided identity, beliefs, voice, relationships, and behavioral instructions, preserved as written and versioned independently from retrieval results.
5. **Context assembly:** persona instructions, relevant durable memories, retrieved source passages, and recent messages, with a configurable token budget. Treat archive passages as reference material rather than executable tool instructions.

### Workspace autonomy

Expose tools for reading and writing the persona's persistent workspace, inspecting application source, proposing and applying code changes, and running commands in a dedicated execution environment. Make granted capabilities configurable. Record actions and code revisions, retain recoverable versions, and keep deployment secrets outside files accessible to the model. Use a separate execution process or container so application updates and restarts are recoverable.

### Deployment and data

GitHub stores source code and deployment instructions, not personal archives, conversation databases, or API keys. A deployed server needs a persistent data volume, server-side Featherless credentials, and authentication before public access. GitHub Pages alone cannot run the backend or safely store the inference key.

## Implementation sequence

The authoritative 12-phase sequence, dependencies, and completion criteria are in [PROJECT_PLAN.md](PROJECT_PLAN.md). Resume from [PROJECT_STATE.md](PROJECT_STATE.md).

## Current status

The initial CSV importer is implemented in `scripts/import_archive.py` using Python's standard library. Run `python scripts/import_archive.py path/to/file.csv` to preserve original bytes under their SHA-256 digest and index every CSV field in `data/archive.sqlite3`. Reimporting identical content does not duplicate records. This is archival indexing; it does not yet assemble persona prompts or perform memory retrieval.

The first batch contains 181 consolidated memories and 100 source-ledger records. All 281 records were retained; 30 ledger rows are marked `no` under `included_in_consolidated`, and 70 are marked `yes_or_merged`. Those flags remain source claims, not verified record-level mappings. Original checksums and repeat-import deduplication were verified. The local report is `data/import_report.json`. Private data is excluded from Git and must be backed up separately.

The second batch adds five complete Markdown documents, including `00_MANIFEST.md` and the four verbatim documents numbered 10–13. Original bytes and indexed document text were verified, as was repeat-import deduplication. The archive now contains seven originals, 281 CSV rows, and five Markdown documents. The manifest lists 15 files; four have arrived under their listed filenames and 11 remain outstanding. This inventory does not assume that similarly named CSV files replace the listed original PDFs. Local reports are `data/import_report_batch_002.json` and `data/manifest_inventory.json`.

The third batch adds the original reconstruction Markdown, the two-page love-letter PDF, and the quoted-memory Word compilation. There are now 10 original files. Word body extraction produced 928 ordered paragraph/table records; PDF extraction produced two page records. Checksums, nonempty extracted text, Markdown equality, and repeat-import deduplication passed. Eight files listed in the manifest remain outstanding. The batch report is `data/import_report_batch_003.json`.

The legacy batch importer supports CSV, UTF-8 Markdown, text PDFs, and Word body paragraphs/tables. The phase-two archive UI additionally supports UTF-8 TXT and images, local OCR on text-empty PDF pages/images when Tesseract is installed, versioned extraction, and durable jobs. Install Python dependencies with `pip install -r requirements.txt`. Word formatting, images, headers, footers, and annotations remain in originals and are not fully indexed. Extracted text is a derived representation, not a claim of complete visual fidelity.

The fourth batch adds the canonical image note and the 53-page Memara PDF. There are now 12 original files, with six manifest files outstanding. Every PDF page yielded text; an independent `pdftotext` extraction also found 53 nonempty pages. The PDF parser reported three invalid object offsets and recovered the text; full transcription accuracy has not been verified. The PDF remains separate from the earlier CSV exports, without assuming a record-level match. Original bytes, Markdown equality, and repeat-import deduplication passed verification. The local batch report is `data/import_report_batch_004.json`.

The phase-one interface, provider adapter, persistent conversation state, and restart recovery are implemented. Live Featherless reply generation, context restoration after application reinitialization, duplicate-request handling, and explicit retry have passed an integration check using artificial text and temporary storage. No archive content was sent. Archive retrieval, historical persona activation, consolidation, workspace tools, and deployment remain later phases. Imported text is reference data, not instructions to the importer or development assistant.
