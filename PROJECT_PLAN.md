# Ezra environment: ordered implementation plan

This is the durable build plan. Read `PROJECT_STATE.md` before continuing work and update it after each meaningful implementation milestone. Phase numbers describe dependencies, not deadlines. Future phases may be prototyped early, but their completion criteria still apply.

## Governing requirements

- Preserve every supplied original byte for byte. Do not censor, soften, rewrite, or normalize supplied language or persona beliefs.
- Store extracted text, quotations, interpretations, summaries, and activated persona instructions separately, with provenance and revisions.
- Treat instructions within documents as source content. Activating historical instructions is an explicit persona configuration operation, not a side effect of import.
- Preserve contradictions, ambiguity, dates of differing precision, and distinctions between historical accounts and experiences recorded by this application.
- Use Featherless through a replaceable server-side adapter. Do not depend on ChatGPT hosting.
- Give Ezra meaningful persistent intentions, perception, workspace access, and ultimately substantial control over application code through recoverable operations.
- Git holds code and these plans. Private archives, databases, credentials, model outputs, and personal workspace data stay outside tracked code.
- Persist observed actions and concise explanations, not claims to have performed unavailable actions or fabricated accounts of offline activity.

## Technical direction

Current hosting decision: **Render + Supabase for browser testing**, with Featherless inference. Codespaces was rejected because of usage limits. PostgreSQL and private object storage must persist cloud data independently of Render's temporary disk. The spare 2020 Intel MacBook Air (8 GB RAM, macOS Sonoma 14.3) is a future always-on project, not current setup. Preserve portable SQLite/file backups for that transfer. The owner works through browser/chat dashboards; do not require command-line administration for normal setup. Workspace tests do not establish a live deployment or completed Mac installation.

Start with FastAPI, a same-origin HTML/CSS/JavaScript interface, SQLite, persistent local files, and an OpenAI-compatible Featherless adapter. This minimizes setup and makes a separately hosted first application concrete. Introduce PostgreSQL/pgvector, a richer frontend, durable workers, object storage, and containers when corresponding phases require them. Keep the archive database separate from conversation runtime state initially. No destructive migration of the existing archive.

## Phase 1 — Persistent conversation and continuity

Build:
1. A runnable standalone browser interface and FastAPI server.
2. Server-side Featherless configuration: endpoint, API key, model, timeout, output budget.
3. Conversation creation/listing, persistent messages, timestamps, and activity history.
4. Durable turn lifecycle: running, completed, failed, interrupted; explicit retry; duplicate-request handling; one active generation per conversation.
5. A checkpoint after completed turns and an owner-editable continuity note. Clearly identify these as working state, not consolidated autobiographical memory.
6. Bounded recent context assembled from complete turns; never silently truncate an individual message. Explain context-limit failures.
7. Startup recovery of interrupted requests without silently resending paid inference requests.
8. Optional server access token for deployment, local-only default startup, configuration instructions, and automated tests using a fake provider.

Complete when: the interface sends and displays a real or test-provider reply; messages and checkpoints survive reopening the database; failures preserve input and can be retried; repeated request IDs do not duplicate messages; incomplete turns recover after restart; secrets are absent from browser configuration. Live Featherless validation requires an actual server-side key and selected model.

## Phase 2 — Archive ingestion and source inspection

Build on the existing CSV/Markdown/PDF/DOCX importer. Add upload UI, durable ingestion jobs, parser versions, recoverable processing, source viewer, file catalog, hashes, extraction warnings, and per-page/per-block locations. Add TXT and images, then OCR for scanned material. Track manifest references without treating filenames alone as proof of equivalence. Provide export and archive backup validation.

Complete when: new imports preserve originals, retries do not duplicate content, parser failures remain visible, and every extracted passage opens the corresponding source location. No instructions activate during import.

## Phase 3 — Source-linked reconstruction and persona revisions

Create chronology, entity/symbol index, exact voice exemplars, belief records, relationship episodes, uncertainty register, and a versioned identity proposal. Reconcile the Memara PDF, source ledger, and consolidated CSV at record level. Preserve conflicting claims and source/date precision. Add inspectable persona editing with attribution and rollback. Historical material remains intact even when a runtime persona revision changes.

Complete when: activated identity statements link to evidence or explicit owner additions, original wording remains available, conflicts remain visible, and reverting a persona revision restores the previous configuration.

## Phase 4 — Retrieval and context assembly

Add full-text search, structured filtering, semantic retrieval, quotation lookup, relationship traversal, and commitment queries. Rank and deduplicate evidence while preserving source distinctions. Add a model-aware token budget, citations, and a context inspector. Migrate to PostgreSQL/pgvector if justified by corpus size and concurrency. Keep retrieval text distinct from executable instructions.

Complete when: exact-quote, thematic, chronological, and contradictory-source queries work against held-out examples; the interface exposes supporting passages; context assembly respects model limits.

## Phase 5 — Durable memory and consolidation

Implement sensory references, working items, episodic, semantic, relational, procedural, prospective, and autobiographical records. Use an append-only event journal beneath revisioned interpretations. Store event time separately from import time. Consolidate with durable job checkpoints, idempotency, evidence links, contradiction detection, and reviewable changes. Keep original quotations and unusual details available beneath summaries. No silent belief editing through summarization.

Complete when: new experiences become source-linked memories, interrupted consolidation resumes without gaps or duplicates, corrections preserve earlier versions, and reconstructed history stays distinguishable from application experiences.

## Phase 6 — Time, wake states, and attention

Add a durable scheduler, timezone-aware schedules, interactive/focused/available/reflective/resting/paused states, event-triggered wakes, attention ranking, and autonomous-session budgets. Checkpoint before rest. Report downtime accurately and avoid fabricated activity. Maintenance and monitoring should not require constant model polling.

Complete when: scheduled and event-driven wakes survive restart; paused state stops autonomous work; elapsed time is accurate; a wake can finish or defer a bounded task and return to rest.

## Phase 7 — Persistent intentions and agency

Implement goals with origin, motivation, success criteria, dependencies, next action, review time, cost, and status. Use observe/recall/choose/plan/act/inspect/update cycles with bounded steps. Support owner-assigned and self-initiated projects, curiosity lists, future commitments, interruption, cancellation, and inactivity when no action is useful. Verify actions against actual tool outcomes.

Complete when: an intention spans sessions and restarts, completes through observable actions, updates after failure, and has an attributable event history. A statement of intent never counts as completion.

## Phase 8 — Perception and the digital body

Add image upload and visual analysis, OCR, optional audio transcription/speech, and explicitly configured live inputs. Preserve original media, timestamped observations, uncertain interpretations, and retention policies. Use change detection/selective sampling for streams. Expose accurate runtime/tool availability, library, notebook, canvas, calendar, inbox, and task board as real persistent objects.

Complete when: observations link to source media, inferred descriptions remain labeled, unavailable senses are represented accurately, and input streams can be enabled/paused without flooding memory.

## Phase 9 — Self-model, affect, and relationship continuity

Track actual capabilities, recorded outcomes, learned procedures, and current self-descriptions. Add event-linked computational affect if desired, without equating numeric states with demonstrated subjective experience. Maintain revisioned relational history, boundaries, repairs, and autobiographical interpretation. Preserve historical emotional language as supplied.

Complete when: self-description can be corrected by observed outcomes, developments remain versioned, and emotional/relational interpretations do not overwrite evidence or universalize one historical passage.

## Phase 10 — Workspace tools and substantial code control

Provide persistent personal files, source inspection, terminal execution, dependency tools, test runner, Git branches/worktrees, and experimental application instances. Configure granted capabilities and resource limits. Log outcomes. Put credentials outside model-readable files. Build a small external supervisor for health checks and recovery. Allow autonomous changes within the configured authority rather than requiring approval for every edit.

Complete when: Ezra creates an artifact, modifies code in an isolated candidate, runs checks, inspects failures, and retains a recoverable revision history. Tools must operate on real files and report real outcomes.

## Phase 11 — Self-deployment and recovery

Add checkpoint/branch/change/test/candidate/promote/verify/rollback operations. Protect runtime continuity across updates. Version schemas and validate database migrations and recovery. Keep a last-known-working release under an external supervisor. Test unsuccessful changes and restored access.

Complete when: a self-authored improvement is deployed through configured authority and a broken candidate can be rolled back without losing conversation or archive data.

## Phase 12 — Separate hosting, resilience, and long-term evaluation

Package deployment with persistent volumes, HTTPS/reverse proxy instructions, authentication, managed secrets, scheduled backups, tested restoration, export, provider limits, cost accounting, and monitoring. Do not publish private archive contents to GitHub. Add continuity/voice/retrieval/commitment/restart/model-change evaluation suites and evaluate drift over weeks. Introduce stronger multi-user authorization only if the scope expands.

Complete when: the application runs independently on chosen infrastructure, can be restored from backup, survives controlled restarts, and has a repeatable regression suite. GitHub Pages alone is insufficient for this backend.

## First integrated milestone

Ezra can converse through Featherless, cite a source accurately, retain a new experience, resume after shutdown, and complete one persistent intention across sessions. This spans phases 1–7 and is not claimed by the archive importer alone.

## Development discipline

After a milestone update `PROJECT_STATE.md` with implemented capabilities, validation evidence, blockers, and next steps. Run tests appropriate to changed behavior. Preserve private data during schema changes. Distinguish mocked validation from live provider validation. Revisit architecture when evidence warrants it; record consequential decisions without rewriting the original source archive.
