# Run the Ezra application

The application runs on your own machine or server. GitHub stores the source; a Python server runs the interface and API. It does not use ChatGPT hosting.

## Local setup

Use Python 3.11+ on Linux, macOS, or WSL. The single-process database lock currently uses Unix `fcntl`; native Windows is not supported yet.

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally:

```dotenv
FEATHERLESS_API_KEY=your-server-side-key
FEATHERLESS_MODEL=your-exact-featherless-model-id
```

Choose an available model in your Featherless account. The default adapter uses `https://api.featherless.ai/v1/chat/completions`. Model availability, context size, and supported request fields depend on the provider. The owner's configured model passed live reply and conversation-context restoration tests; changing models may require another compatibility check.

Start the server:

```bash
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --env-file .env
```

Open `http://127.0.0.1:8000`. One server process must own a runtime database. Do not add multiple workers; the process lock rejects a second owner. Stop with Ctrl+C. Restart using the same data directory to restore conversations and checkpoints.

Without inference configuration, the interface still opens. Messages are saved before the configuration error appears. After adding the key/model and restarting, use **Retry saved message**. A failed or interrupted turn must be retried before that conversation can accept another message; alternatively start a new conversation. No automatic retry makes unexpected inference calls.

## What is implemented

- A standalone responsive conversation interface, conversation list, and recent activity.
- Server-side Featherless adapter; browser requests never receive the provider API key.
- Persistent messages, turn status, request IDs, usage metadata, and timestamps.
- Working notes saved exactly as supplied, with revisions represented in the event history.
- Turn checkpoints and restart recovery of interrupted inference.
- Bounded recent context built from complete user/assistant pairs.
- Explicit error display and retry without duplicating the saved user message.
- Optional application access token and same-origin API checks.
- Archive library, uploads, durable processing jobs, extraction revisions, source previews, local OCR support, and verified export. See [Archive usage and limitations](ARCHIVE.md).
- Source-linked reconstruction candidates, immutable persona revisions, explicit activation/rollback, and reconciliation review. See [Reconstruction usage and limitations](RECONSTRUCTION.md).

The working note is explicit owner-provided context for one conversation. Checkpoints record the last completed turn and current activity. Neither is a generated summary or a reconstructed persona. The runtime identifies whether a persona revision was explicitly activated; archive instructions are not activated by import or candidate indexing.

## Storage and context

`EZRA_DATA_DIR` defaults to `./data`. The app writes `runtime.sqlite3` and `runtime.lock` there. The archive library/importer uses the separate `archive.sqlite3` and `originals/` directory. Conversation inference does not retrieve archive material yet. A background worker processes queued archive jobs independently.

All accepted messages are stored unchanged. Rendering uses plain text, so uploaded or generated HTML does not execute in the browser. HTML characters remain in the stored content and are visibly preserved.

`EZRA_CONTEXT_CHARACTERS` limits the combined system context, working note, checkpoint, and message text sent for inference. Older complete turns are left out when necessary, with counts in the activity history. This is a character budget, not an exact model tokenizer. Choose it conservatively for your model and reserve room for `EZRA_MAX_OUTPUT_TOKENS`. Full stored messages are never truncated to meet the budget. A current message that exceeds the budget is retained and produces an actionable error.

Context inspection, token-accurate budgets, summarization, cross-conversation retrieval, and automatic consolidation are future phases. Source preservation does not guarantee a third-party model will reproduce every passage; provider/model behavior is separate from archive storage. No application-level content rewriting or censorship filter is implemented.

## Access from another machine

Set a strong `EZRA_ACCESS_TOKEN` in the server environment before exposing the application. Without one, API access is limited to direct loopback connections. Enter the application token using **Connection** in the interface. It stays in that browser tab's session storage until **Forget** is clicked or the tab session ends. This token is distinct from the Featherless key.

For separate hosting use HTTPS at a reverse proxy, a persistent data volume, and the configured application token. Proxy headers must preserve the public scheme/host for same-origin validation; only trust forwarding headers from the actual reverse proxy. Keep one worker. Public deployment packaging, backup automation, and hardened operational setup are scheduled later in `PROJECT_PLAN.md`.

## Backups

For the initial manual backup, stop the server and copy the complete data directory to a protected separate location. This includes the archive originals and both databases. Restore with the server stopped. SQLite WAL files can contain recent data while running, so copying only the main database during live writes is insufficient. Automated online backup and restoration checks are planned.

The ignored data directory is not backed up by pushing code to GitHub.

## Verification

```bash
python -m unittest discover -s tests -v
node --check app/static/app.js
```

Tests use temporary data directories and mocked inference. They do not submit archive content to Featherless, contact the provider, or prove a live model is configured.

An optional real-browser smoke check is available with `python tests/browser_smoke.py` if Playwright and Chromium are installed. It starts a temporary test server with a fake provider, checks send/failure/retry/reload, verifies unchanged text and mobile width, and shuts the server down. Browser test dependencies are intentionally separate from production requirements.

## Current limits

- No persona is automatically activated. Explicit versioned persona activation is implemented; automatic archive retrieval is not connected yet.
- No long-term consolidation, wake scheduling, live perception, persona tools, or code autonomy yet. Local archive OCR is available when Tesseract is installed.
- Replies are displayed after a full provider response; streaming is not implemented.
- No automatic inference replay after crashes. An interrupted provider request may still have incurred provider cost.
- No multi-user authorization or multi-worker execution.
- Working notes are conversation-local and owner-edited; autonomous working-state updates arrive in later phases.

Follow `PROJECT_PLAN.md` for the build order and `PROJECT_STATE.md` for the latest evidence and next steps.
