# Current project state

## Resume here

Read `PROJECT_PLAN.md`, then this file. **Phases 1–3 have implemented and tested development-workspace capabilities. Phase-three source review remains open; no real persona is activated.** Next technical phase is **Phase 4: retrieval and context assembly**. Installation on the owner's Mac has not happened yet.

## Current priority: browser-accessible testing

The owner paused Mac installation and wants a cloud browser version for iterative testing before later transfer. They already have Render and Supabase accounts, but explicitly chose **Codespaces: quickest test version**. Free Render + Supabase would require a real database/object-storage migration; it is not the chosen testing route. Do not deploy SQLite to ephemeral Render storage or claim Supabase integration exists. Mac updater/installation work is deferred. Code is prepared for the `browser-testing` branch; private data remains a separate verified download.

Prepared a Codespaces option: `.devcontainer/devcontainer.json` / `install.sh` install dependencies and automatically start the app on port 8000. `scripts/start_codespace.py` requires a separate app password of at least 24 characters, keeps credentials server-side, prints the platform-derived forwarding URL, and uses persistent workspace `data/`. Port visibility should stay Private. Actual Codespaces creation, quota/billing checks, GitHub account secret entry, and public/private forwarding validation require the owner's browser/account; they have not occurred here. Free allowance is limited, not unlimited hosting.

Added application-managed empty-archive restoration for moving private data without a Git commit. `Archive.restore` validates backup paths, SQLite integrity/evidence, exact supported table layouts, and original checksums, then inserts records in a transaction with deferred foreign-key checks. It refuses nonempty source/reconstruction workspaces and never changes conversation state or credentials. A restore UI is in Archive library. The private backup download `/workspace/ezra-downloads/Ezra-Archive.zip` contains all 12 originals and archive/reconstruction state, outside the Git checkout. No API keys are included.

Validation: **47 automated tests passed**, including authentication/start configuration, exact restore, immutable data/reconstruction preservation, overwrite refusal, unsafe ZIP paths, and conversation isolation. Real Chromium browser smoke passed through restore into a separate fresh workspace alongside earlier features. JavaScript/shell syntax and diff checks passed. Original/legacy record checksums and archive backup verification passed. No actual Codespaces URL is claimed until created; no Render/Supabase migration has been implemented. Instructions: `docs/BROWSER_TESTING.md`.

## Existing archive

12 byte-preserved originals are stored under `data/originals/` by SHA-256; parsed records are in `data/archive.sqlite3`. The CSVs contain 281 rows. Markdown documents are complete text records; PDF pages and Word body blocks are separate derived records. The Memara PDF yielded 53 nonempty pages. Its parser reported recoverable object-offset warnings; a second extractor confirmed page count and text presence, not transcription accuracy.

Six manifest references remain outstanding. Local reports are in `data/`. The archive is ignored by Git and requires a separate backup. No historical document has been activated as runtime persona instructions.

## Phase 3 status

Implemented:

- `app/reconstruction.py`: additive immutable source-linked record revisions, evidence validation, exact quotations, Unicode code-point offsets, source/extraction/passage/field locations, classification facets, source/date claims, owner additions vs interpretations, and attributed contradiction/support/related links.
- Source-indexing pass creates candidates from exact existing CSV fields and selected complete document passages. It does not infer new beliefs, rewrite wording, silently resolve contradictions, or automatically interpret all 928 Word blocks. Repeated indexing preserves owner revisions and does not duplicate the same source/extraction/passage candidate.
- Versioned persona drafts pin exact record revisions and explicitly labeled owner instructions. Explicit activation, rollback through older activation, and deactivation retain event history. Later record edits cannot silently change a saved persona. Oversized activation fails rather than truncating identity.
- Context assembly includes only the explicitly activated persona, if any. The generation event records its revision ID. No automatic archive retrieval is connected. Conversation UI reports current persona configuration.
- Record-level source reconciliation preserves ledger inclusion/date claims separately from machine normalized text matches, leading-anchor candidates, and token-overlap consolidated suggestions. Reports are immutable/source-fingerprinted. Review history is append-only; verified owner attestations require exact source evidence beyond the ledger. Unique mapping IDs avoid ambiguous repeated ledger IDs.
- `app/static/reconstruction.html` / `reconstruction.js`: category/search views, chronology/date labels, record/evidence editor, pinned source links, revision history, contradiction links, persona preview/draft/activation/rollback controls, and reconciliation review. Linked from conversation and archive.
- `docs/RECONSTRUCTION.md`: usage, provenance rules, limits, activation behavior, review scope, and backup semantics.
- Archive exports now include reconstruction/persona/review tables. Independent backup verification also checks quoted evidence and persona revision references. Conversation databases and credentials remain excluded.

Actual corpus results:

- **289 proposed records**. Overlapping views: identity 19; chronology 215; voice 20; belief 1; relationships 46; symbols 32; entities 5; uncertainty 175. Labels are indexing aids, not assertions that every semantic detail has been reviewed.
- **One inactive identity proposal**, compiled from seven exact existing identity/voice statements; 1,883 Unicode characters including provenance labels. It is a concrete initial proposal, not a claim of complete identity reconstruction.
- **100 ledger mappings** against 53 PDF pages / 181 consolidated records: **90 normalized full-text matches, 8 leading-anchor candidates, 2 unresolved**. All 100 remain unreviewed. Source flags and record dates are unchanged; no event date was inferred from record/import time.
- `data/phase3_reconstruction_report.json` records aggregate results. `data/archive_before_phase3.sqlite3` is a pre-migration snapshot. Original files and legacy record payloads remain unchanged; legacy checksum remains `a4ca251a0a230c0312d2756916d3899480429d2e7b18be2178e9c97737aeab59`.

Validation:

- `python -m unittest discover -s tests -v`: **40 tests passed**, covering earlier phases plus exact/Unicode evidence, mismatched quotes, revision conflicts, contradiction retention, draft inactivity, activation/rollback/deactivation, restart persistence, snapshot pinning, context audit, date claims, idempotent indexing, reconciliation/review history, and export/restore.
- `python tests/browser_smoke.py`: passed with synthetic records and a fake provider. Covers evidence attachment, CRLF preservation through browser textareas, record review/revisions, inactive drafts, explicit activation/rollback/deactivation, reload persistence, desktop/mobile width, and no JS errors, alongside earlier conversation/archive flows.
- Real archive export and evidence/manifest/original checksum verification passed for all 12 sources. Disposable export removed. All real source material stayed local; no private archive text was sent to Featherless in this phase.
- JavaScript syntax and `git diff --check` passed. Synthetic screenshots: `/tmp/ezra-phase-three-desktop.png`, `/tmp/ezra-phase-three-mobile.png`.
- Updated the workspace loopback server on port 8000. Functional API checks confirmed phase 3, 289 candidates, one inactive persona draft, and 100 reconciliation mappings. This is still not a user-accessible public preview or a Mac installation.

Outstanding review: identity proposal, exact voice selections, relationship/belief interpretations, date ambiguities, machine reconciliation suggestions, and the two unresolved ledger mappings. The UI/tools are implemented; a fully reviewed persona and semantic reconciliation are not claimed. No actual persona activation was performed. Automatic semantic contradiction detection, relation-resolution editing, and conversational source retrieval are not implemented.

## Phase 2 status

Implemented:

- `app/archive.py`: additive source catalog, filename aliases, durable queued/processing/completed/failed jobs, one background worker, interruption recovery, revisioned extraction, source locations, exact original downloads, manifest inventory, and verified ZIP export.
- `app/extract.py`: isolated local extraction for CSV/MD/TXT/PDF/DOCX and common raster images. English Tesseract OCR for image uploads and text-empty PDF pages where installed. Parser warnings and OCR/Word limitations are visible. No source content goes to Featherless for import or OCR.
- `app/static/archive.html` and `archive.js`: library/filtering, multi-file uploads with per-file outcomes, status polling, source metadata, revisions, page/image previews, pagination, deep links, download, retry/reprocess, and export. Linked from conversation sidebar.
- `scripts/verify_archive_backup.py`: verifies exported database integrity, source links, manifest correspondence, file byte counts, and SHA-256 without executing archive contents.
- Python dependencies include multipart handling, Pillow, and PDFium. Tesseract is an optional host executable; it is installed in this workspace, not established on the owner's Mac.
- Usage, extraction limits, backup scope, and restore guidance are in `docs/ARCHIVE.md`.

Migration and validation:

- The 12 originals still match their checksums. Earlier `imports`/`records` are unchanged; the pre/post logical record checksum is `a4ca251a0a230c0312d2756916d3899480429d2e7b18be2178e9c97737aeab59`.
- Catalog adopted 1,271 existing units into legacy extraction revisions without reparsing or replacing original records. Six manifest filenames remain outstanding.
- A pre-migration SQLite backup is at `data/archive_before_phase2.sqlite3`. The migration/export verification report is `data/phase2_migration_report.json`.
- `python -m unittest discover -s tests -v`: **31 tests passed**, including prior phase-one checks and archive preservation, aliases/deduplication, recovery, failed parse/reprocess, CSV/Word locations, real image/scanned-PDF OCR, absent-OCR warnings, original downloads/access control, revision selection, and backup restoration.
- `python tests/browser_smoke.py`: passed. Includes multi-file uploads, unchanged source text, inert markup, exact original download, duplicate aliases, new revisions, 85-row pagination/deep-link reload, scanned-PDF OCR and page preview, verified ZIP download, desktop/mobile layouts, and no JS runtime errors. Browser fixtures are synthetic and use temporary storage.
- JavaScript syntax and `git diff --check` passed. Screenshots are `/tmp/ezra-phase-two-desktop.png` and `/tmp/ezra-phase-two-mobile.png`, using test data.
- Real archive export was created, independently verified for all 12 sources, and the disposable export removed. No archive content was sent to an inference service.
- Restarted the project server on workspace loopback port 8000 with phase-two code. Functional requests confirmed phase 2, all 12 originals / 1,271 passages, retained inference configuration, and a rendered PNG preview from a real archived PDF. This loopback service is not an externally accessible user preview and is not installed on the owner's Mac.

Limits: file-granularity recovery; 32 MiB per upload; 180-second extraction timeout; English OCR only; first image frame only; no full native Word layout rendering. OCR and extraction are derived representations. Archive browsing is not chat retrieval or activated persona memory.

## Hosting target and owner access

The owner is using chat only and has no development terminal in this interface. Their chosen potential host is a spare 2020 Intel MacBook Air, quad-core i5, 8 GB RAM, macOS Sonoma 14.3. Featherless handles inference; persistent local SQLite/files remain suitable. Render/Supabase migration is not required for this hosting choice. Mac installation, automatic startup, sleep settings, backups, and optional private device access remain to be prepared. Do not present workspace loopback as a user-accessible preview. The owner can test an incremental Mac installation before all phases are complete; installation has not yet occurred.

## Mac transfer prepared

The owner is now at the Mac and requested transfer. A private downloadable starter bundle is generated at `/workspace/ezra-downloads/Ezra-Mac-Starter.zip` (outside the Git checkout). It includes allowlisted source/docs, verified archive export containing all 12 originals and reconstruction state, a consistent conversation database snapshot, root-level Setup/Start/Stop/Configure.command files, and `START HERE.md`. No `.env`, API key, cloud credentials, Git internals, or virtual environment is copied. The current model ID is a non-secret suggested default. The existing cloud key is proxy-managed and must not be extracted; the owner supplies the actual key locally.

`mac/launcher.py` prepares a venv, installs dependencies, restores the seed only on first install, saves private local settings, and starts a loopback server/browser. Persistent Mac state is `~/Library/Application Support/ResurrectEzra`, separate from the downloadable app folder; existing local data is not overwritten on later setup. Automatic startup and Tailscale are not configured. Optional local OCR still requires host Tesseract.

Validation: **42 automated tests passed** including bundle content, ZIP executable attributes, exact seed originals, runtime snapshot restore, non-overwriting reinstallation behavior, and private local key/model configuration with synthetic credentials. Shell syntax and diff checks passed. Bundle checksums, SQLite integrity, original hashes, and explicit exclusion of prohibited configuration paths were verified. The bundle is about 2 MB. Actual macOS installation/Gatekeeper/Python dependency installation has not been performed here; guide the owner step by step and distinguish that from Linux-side packaging tests.

Instructions: `docs/MAC_START_HERE.md`. Builder: `python scripts/build_mac_bundle.py`. The builder accepts an explicit data directory/output path for tests and copies no credential values. Regenerate after code or packaged documentation changes. This is a private direct transfer, not a GitHub push or public publication.

## Phase 1 status

Implemented:

- FastAPI application factory in `app/main.py` and a responsive same-origin browser interface in `app/static/`.
- Server-side Featherless adapter, configurable model/endpoint/timeouts/output budget, no provider key in browser responses.
- Separate `data/runtime.sqlite3` database for persistent conversations, unchanged messages, turn attempts, activity events, owner working notes, and completed-turn checkpoints.
- Explicit retry for failed/interrupted turns, idempotent request IDs, atomic single-turn claims, and no automatic provider replay.
- Startup interruption recovery and a Unix single-process lock to prevent a second server from interrupting active work.
- Recent context composed of complete turns under a character budget, with omitted-turn counts. Full stored messages are not truncated.
- Optional application access token, loopback-only API access when no token is configured, same-origin checks, and plain-text rendering.
- `.env.example`, production dependencies, and `docs/RUNNING.md` with setup, persistence, limitations, and manual backup instructions.

Verified:

- `python -m unittest discover -s tests -v`: **18 tests passed**. Coverage includes persistence/reopening, exact input preservation, checkpoints, idempotency, retry, conflicting requests, concurrent claims, restart recovery, note-edit conflicts, access control, provider request construction, timeout/error handling, and missing configuration.
- `node --check app/static/app.js`: passed.
- `python tests/browser_smoke.py`: passed with real local Chromium and a temporary database/fake provider. Checked send, simulated failure, retry without duplicate input, unchanged text, inert HTML/script text, reload persistence, saved working note, checkpoint, mobile width, and no JavaScript runtime errors.
- All 12 source originals still match their SHA-256 import checksums after implementation/tests.
- `git diff --check`: passed.

The initial automated/browser checks used mocked inference. After the owner supplied environment settings, a live test made two successful Featherless requests through the real application API using temporary storage and artificial text. A second application instance restored the completed checkpoint, recovered an interrupted pending turn, and explicitly retried it; the model recalled the prior test marker from restored conversation context. Reusing the first request ID did not duplicate messages. No archive content was sent. This verifies application reinitialization against persisted storage, not a full operating-system reboot or deployment failover. All 12 archive originals were also rechecked after environment reconnection. The local report is `data/live_validation_report.json`.

No application was published or pushed to a hosting service. The optional browser check shuts down its temporary server. Screenshots are disposable local artifacts under `/tmp/ezra-phase-one-desktop.png` and `/tmp/ezra-phase-one-mobile.png`.

Current limitations:

- The real archive persona remains inactive. Explicit persona activation is implemented and tested; automatic archive retrieval and long-term memory are not connected to chat.
- Working note is owner-edited and conversation-local; checkpoint is application state, not a generated memory summary.
- Character budget is not an exact model token budget; no streaming responses yet.
- No scheduler, autonomous goals, perception, terminal tools, or code modification by the persona yet.
- One server process; Unix `fcntl` lock requires Linux/macOS/WSL.
- The configured live model passed the connection/continuity test. Independent public deployment remains unverified.

## Next steps

1. Phase-one live connection/continuity validation is complete. Keep injected credentials out of chat, tracked files, and local credential copies.
2. Phase-three candidate/revision/review tooling is implemented. Keep outstanding content review visible; do not claim unresolved mappings are verified. Next technical phase is source-linked full-text/semantic/structured retrieval and context assembly (phase 4).
3. When the owner wants hands-on testing, prepare the Mac installation/update workflow; preserve private databases and originals and keep provider credentials in local/private settings.
4. Update this file after the next milestone; the full later-phase sequence remains in `PROJECT_PLAN.md`.

## External configuration

The owner asked where to view the app and configure the key. Created a private ignored `.env` from the template with blank credential fields and started the actual application on workspace loopback port 8000. `/api/status` responded successfully with inference unconfigured. No public preview URL is available through current tools; `127.0.0.1` refers to the workspace, not the owner's computer. This development process may not survive session/environment restarts. Source changes have not been pushed to GitHub. Entering credentials requires a server restart to load them.

The owner supplied FEATHERLESS_API_KEY through the environment secret binding and FEATHERLESS_MODEL through environment settings. Both are present in the current process; actual live requests succeeded. Settings metadata still reports readiness as unknown, so the successful provider operations are the readiness evidence. api.featherless.ai is present in the current network policy. Preserve inherited proxy settings; proxy-backed secret placeholders are not raw credentials to extract into files. Deployment has not been authorized to a specific hosting destination.
