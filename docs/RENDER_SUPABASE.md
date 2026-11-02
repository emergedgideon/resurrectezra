# Private browser testing on Render + Supabase

This is the chosen cloud-testing route. Codespaces and Mac installation are deferred. Render serves the interface/backend; Supabase PostgreSQL stores conversations, jobs, evidence, and persona state; a private Supabase Storage bucket holds original bytes. Render's filesystem is a disposable verified cache, never the authoritative copy.

The implementation and Render Blueprint are prepared in the `browser-testing` branch. Actual deployment and the user's credentials must be configured in their dashboards. A Supabase Project URL alone does not authorize database/storage access.

## 1. Prepare Supabase in your browser

Open your project.

1. Choose **Storage → New bucket**. Name it **ezra-private**. Leave **Public bucket OFF**. Do not add anonymous/public read policies. The app refuses startup if the bucket is public.
2. Open **Connect** and choose the **Session pooler** connection string, on **port 5432**. This supports IPv4-based hosting and the session locks the app uses. Do not choose Transaction pooler on 6543. You can copy the string with its password placeholder intact: enter the actual project database password separately as `EZRA_DATABASE_PASSWORD` in Render. The app safely substitutes/encodes it. Keep the connection details private.
3. In **Project Settings → API Keys**, find the server-side **service_role** key (under legacy API keys if necessary). Use that server key, never an anon/publishable key. It stays in Render environment settings. The storage adapter also recognizes `sb_secret_` keys by sending them as API keys, but a live test with your project remains necessary.
4. Keep the ordinary HTTPS **Project URL** available. This URL is not the database connection URI.

No SQL Editor script is needed for a new deployment. On startup the backend creates its private `ezra_runtime` and `ezra_archive` schemas without replacing existing app records. It revokes PUBLIC schema access; these schemas do not need to be added to Supabase's exposed API schemas. The configured database role must be able to create/use them. Use a dedicated project or review the names if you already use matching schemas.

## 2. Create the Render service in your browser

In Render choose **New → Blueprint**, connect the GitHub repository `emergedgideon/resurrectezra`, and select branch **browser-testing** with `render.yaml`. Review the **free** web service before creating it. Do not add a paid disk: persistent data lives in Supabase.

Fill these private environment fields when Render prompts:

| Field | Value |
| --- | --- |
| `SUPABASE_URL` | Your HTTPS Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | The server-side storage/API key |
| `EZRA_DATABASE_URL` | Session pooler PostgreSQL URI, port 5432; password placeholder can remain |
| `EZRA_DATABASE_PASSWORD` | Your Supabase project database password, entered separately |
| `FEATHERLESS_API_KEY` | Your actual Featherless key |
| `FEATHERLESS_MODEL` | Your exact chosen model ID |
| `EZRA_ACCESS_TOKEN` | A separate application password, at least 24 characters |

The blueprint supplies `SUPABASE_STORAGE_BUCKET=ezra-private` and `EZRA_DATA_DIR=/tmp/ezra-cache`. It builds with `pip install -r requirements.txt` and starts `python scripts/start_render.py`. If using **New → Web Service** manually, enter those commands, branch, free plan, and fields yourself. Health check path is `/healthz`.

These settings are separate from this chat's managed environment and from GitHub Codespaces secrets. Existing proxy-managed credentials in this chat cannot be extracted and copied into Render. Enter values directly in Render's private dashboard; never send keys/passwords in chat, commit them, or enter the Featherless key in the app's Connection field.

The Render launcher refuses missing cloud persistence or short/missing application passwords. It uses one Uvicorn process. Its trusted forwarding-header configuration is specifically for Render's HTTPS proxy; use the local launcher on a private machine instead.

## 3. Open and populate your app

Once Render reports the service is live, open its HTTPS address. Under **Connection**, enter the separate `EZRA_ACCESS_TOKEN` application password.

Open **Archive library → Restore archive backup**, select the separately supplied `Ezra-Archive.zip`, and restore. The verified archive contains your original files, extractions, reconstruction candidates, and persona proposal. Restore requires an empty archive/reconstruction workspace, so it cannot overwrite later work. It leaves conversations and credentials unchanged. No source material is committed to GitHub. No historical persona activates automatically unless an explicitly activated configuration was present in the backup.

Make a small test conversation. Refresh, restart/redeploy the Render service, reconnect with the same app password, and confirm that the conversation, archive, and persona state remain. This real deployment verification has not happened merely because local PostgreSQL tests passed.

## Persistence and deployment behavior

- Database changes commit to PostgreSQL before an API operation reports success. Connection errors return a sanitized failure rather than falling back to SQLite.
- Original bytes upload to immutable content-hashed private objects before their import job is acknowledged. Duplicate uploads verify existing content rather than overwriting it.
- After a Render restart or cache loss, originals are fetched and checksum-verified from Storage. Queued imports remain in the database.
- Cloud schema transactions are serialized with PostgreSQL advisory locks for this single-owner app. Temporary overlap during deployment does not immediately interrupt another instance's fresh inference/import work. Expired work is recovered after a bounded grace period. Attempt checks prevent late results from an old attempt overwriting a retry.
- Repeated interrupted extractions stop after three attempts and need explicit reprocessing. No paid inference request is automatically replayed.
- Private schemas and Storage are not a substitute for backups. They protect ordinary operation, not project deletion or account loss.

## Backups and future transfer

**Export verified archive** downloads the archive and originals. **Full backup** additionally includes the conversation/runtime database. Both produce portable SQLite snapshots and exclude credentials. Full backup is the appropriate source for the eventual Mac transfer; do not use the older starter bundle as a substitute for newer cloud conversations.

The verifier checks original hashes, evidence links, and—when present—the runtime database hash/integrity. Keep downloaded backups separately. Archive restore accepts archive-only exports; full backups have a distinct runtime component and are intended for complete migration/restoration tooling, not merging over a live service.

## Free-tier constraints

Render's free service can sleep and cold-start. Supabase free projects have storage/database quotas and can pause under current plan rules. Confirm current allowances and avoid enabling paid resources unintentionally. This is an interactive test host, not guaranteed continuous agency. Wake schedules and cron integration are not configured by this deployment.

Local English OCR is optional. Native Render Python services may not include the Tesseract executable; image/scanned-page imports will preserve originals and show a visible OCR warning if it is missing. Existing extracted text remains usable. Larger archive processing and continuous work may need different resources later.

## Validation and troubleshooting

Developer tests use a real isolated local PostgreSQL 16 server plus HTTP-level simulated Supabase Storage. They exercise cache loss, durable conversations/jobs, portable restore/export, retries, locks, and startup refusal. Chromium also exercises the UI against PostgreSQL. They do not prove that the user's actual Supabase project, pooler, key, or Render service is configured.

The cloud database adapter supports the current application's explicit SQL vocabulary, not arbitrary SQLite extensions. It translates schema definitions, parameterized inserts, ordering, and schema inspection; retains original portable table definitions; and uses transaction-level advisory locks. Cloud schema changes must extend/test portable export and restore as well as PostgreSQL behavior. Integration resets refuse anything except an explicit loopback database named `ezra_test`; never use real project credentials in tests.

If deployment fails, share the error wording or a screenshot with values hidden. Common causes are a missing/private bucket, anon key instead of server key, pooler on 6543, an unfilled database password placeholder, wrong project region/host, paused Supabase project, or missing Render environment fields. Database SSL hostname/certificate verification stays enabled. There is no automatic insecure fallback.
