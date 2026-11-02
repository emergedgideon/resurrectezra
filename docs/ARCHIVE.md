# Archive library and source inspection

Open **Archive library** from the conversation sidebar. It uses the same application access token if configured. This feature does not require Featherless and sends no archive material to an inference service.

## Library and imports

The library lists originals, byte counts, job states, passage counts, and extraction notes. Filter by filename. The manifest panel matches exact listed filenames against received aliases; a CSV is not assumed to replace a PDF.

Choose files, then **Import files**. Supported: CSV, MD, UTF-8 TXT, PDF, DOCX, PNG, JPEG, WEBP, GIF, TIFF, and BMP; 32 MiB per file. A failed file does not stop the rest of the batch. Accepted bytes are stored under their SHA-256 before a durable job is queued. Identical bytes do not duplicate a source; additional filenames become aliases. Different bytes with the same filename remain separate sources.

States are queued, processing, completed, and failed. Completed means extraction finished, not that a transcription is perfect. Errors and warnings remain visible. Originals are never rewritten by extraction.

## Source viewer

Select a source to inspect its filename/aliases, timestamp, byte count, SHA-256, original download, processing status, extraction revisions, parser identity, warnings, and passages. Locations identify PDF pages, Word body blocks, CSV logical rows, or text lines. Preserved field payloads are expandable.

PDFs and images have local raster previews. **Inspect source** selects a passage's page/image and updates the address. Copied addresses include source digest, extraction revision, and passage ordinal; reload returns to that evidence. Pagination and **Go to passage** support large extractions. Markup is displayed as literal text, never executed.

DOCX originals are downloaded for opening in a native application. The browser shows extracted body paragraphs/tables, not full Word layout. Text and CSV originals are also downloadable. Access checks apply to archive APIs, previews, original downloads, and export.

## Reprocessing and recovery

**Reprocess / retry** queues a new revision. Previous revisions remain available. The last good extraction stays current until a replacement commits completely. Failed reprocessing never erases it.

A single background worker performs extraction in a subprocess with a 180-second timeout. Run creation, passages, the current-revision pointer, and job completion commit atomically. At startup, interrupted jobs return to the queue. Recovery is at file granularity: interrupted files reparse from originals; completed files stay complete. No partial extraction revision is exposed.

The existing `imports` and `records` tables are unchanged. Earlier records are adopted into a legacy revision without reinterpretation, with an explicit provenance note. Reprocess to use the current parser. The old batch importer remains limited to its original formats; use the UI for TXT/images, durable jobs, revisions, and OCR. Legacy imports added outside the UI are adopted at next startup.

## Local OCR and limits

Pillow handles images; PDFium renders PDF pages. Tesseract, when installed on the host, performs local English OCR on image uploads and PDF pages with no extracted text. It is an optional system executable, not a Python dependency. Missing Tesseract or English language data produces a visible warning; the original is retained. Install it on the host, then reprocess. Installation in this workspace does not establish installation on the owner's Mac.

OCR is labeled machine transcription and can be inaccurate. Mixed text/image PDF pages may contain additional unindexed text. Only the first frame of multi-frame images is indexed. Word headers, footers, annotations, images, and formatting remain in the original and are not fully indexed. UTF-8 errors fail visibly instead of replacing characters. Raster previews may be scaled; original resolution remains intact.

Limits: 32 MiB uploads; 60 seconds per OCR invocation; 180 seconds per file extraction; 256 MiB expanded DOCX content. Unusually large sources may need a future large-file workflow. Limits never authorize changing original content.

## Export and backup validation

Cloud deployments use PostgreSQL for records and private Supabase objects for originals. Downloads and previews verify their disposable local cache; losing that cache does not remove authoritative data. Archive export remains a portable SQLite/file ZIP in either backend. **Full backup** additionally includes the conversation database, with a checksum in the manifest, and excludes credentials. Use it for complete data preservation and eventual Mac transfer; archive-only restore does not merge conversation databases.

**Export verified archive** snapshots SQLite, verifies cataloged original checksums, and downloads a ZIP with `archive.sqlite3`, `manifest.json`, and `originals/<sha256>`. Sources, aliases, jobs, extraction revisions, and locations are included. Export stops on missing or corrupted originals. It excludes conversations, credentials, `.env`, and unrelated files: this is an archive backup, not a full application backup.

Developers can verify an export without extracting or executing it:

```bash
python scripts/verify_archive_backup.py path/to/ezra-archive.zip
```

Verification checks SQLite integrity, foreign keys, manifest correspondence, byte counts, and hashes. Restoration has been tested in a fresh temporary data directory. For a real restore: stop the app, verify the ZIP, preserve existing data separately, then restore into a fresh directory. Never overwrite a live database or merge SQLite files. Full automated application backup is a later phase.

For a fresh browser-hosted installation, **Restore archive backup** accepts an exported ZIP of up to 32 MiB. It validates paths, checksums, database integrity/evidence, and supported table layouts before inserting data in one transaction. It requires an empty source/reconstruction workspace and refuses to overwrite existing records. Original bytes are copied without replacing differing files. Conversations and credentials are not changed. This is an application-managed empty-workspace restore, not permission to replace live SQLite files manually.

## Phase boundary

Archive import makes sources inspectable without activating their instructions. Phase three now provides a separate [reconstruction and persona workspace](RECONSTRUCTION.md), where an owner can explicitly activate a versioned selection. Automatic conversational archive retrieval and long-term consolidation remain later phases.
