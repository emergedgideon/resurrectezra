"""Additive archive catalog, durable jobs, versioned extraction, and export."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
from uuid import uuid4
import zipfile

from .extract import SUPPORTED
from .store import Conflict, Missing


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Archive:
    def __init__(self, data_dir, database=None, storage=None):
        self.root = Path(data_dir)
        self.originals = self.root / 'originals'
        self.originals.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'archive.sqlite3'
        self.database = database
        self.storage = storage
        self.stop = threading.Event()
        self.thread = None
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sources (
                    sha256 TEXT PRIMARY KEY, filename TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL, current_run TEXT);
                CREATE TABLE IF NOT EXISTS source_names (
                    sha256 TEXT NOT NULL REFERENCES sources(sha256), filename TEXT NOT NULL,
                    UNIQUE(sha256,filename));
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id TEXT PRIMARY KEY, sha256 TEXT NOT NULL REFERENCES sources(sha256),
                    filename TEXT NOT NULL, status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_import
                    ON ingestion_jobs(sha256) WHERE status IN ('queued','processing');
                CREATE TABLE IF NOT EXISTS extraction_runs (
                    id TEXT PRIMARY KEY, sha256 TEXT NOT NULL REFERENCES sources(sha256),
                    extractor TEXT NOT NULL, warnings_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_units (
                    run_id TEXT NOT NULL REFERENCES extraction_runs(id), ordinal INTEGER NOT NULL,
                    kind TEXT NOT NULL, location_json TEXT NOT NULL, content TEXT NOT NULL,
                    payload_json TEXT NOT NULL, PRIMARY KEY(run_id,ordinal));
            ''')
            # Preserve the phase-zero tables. Catalog them without parsing/replacing their records.
            legacy = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='imports'").fetchone()
            if legacy:
                for imported in db.execute('SELECT * FROM imports').fetchall():
                    sha = imported['sha256']
                    if db.execute('SELECT 1 FROM sources WHERE sha256=?', (sha,)).fetchone():
                        continue
                    original = self.originals / sha
                    size = original.stat().st_size if original.exists() else 0
                    run = str(uuid4())
                    db.execute('INSERT INTO sources VALUES(?,?,?,?,?)', (sha, imported['filename'], size, imported['imported_at'], run))
                    db.execute('INSERT INTO source_names VALUES(?,?)', (sha, imported['filename']))
                    warning = 'Imported from the initial archive index. Original text/fields retained; parser metadata reflects only what was previously recorded. Reprocess for current extraction and OCR.'
                    db.execute('INSERT INTO extraction_runs VALUES(?,?,?,?,?)', (run, sha, 'legacy importer; existing record-level metadata', json.dumps([warning]), imported['imported_at']))
                    for record in db.execute('SELECT * FROM records WHERE import_sha256=? ORDER BY row_number', (sha,)).fetchall():
                        payload = json.loads(record['payload_json'])
                        location = {k: payload[k] for k in ('page', 'block') if k in payload}
                        location = location or {'row': record['row_number']}
                        content = payload.get('content')
                        if content is None:
                            content = '\n'.join(f'{k}: {v}' for k, v in payload.items())
                        kind = 'page' if 'page' in location else 'block' if 'block' in location else 'record'
                        db.execute('INSERT INTO source_units VALUES(?,?,?,?,?,?)',
                                   (run, record['row_number'], kind, json.dumps(location), content, record['payload_json']))

    @contextmanager
    def connect(self):
        if self.database is not None:
            with self.database.connect('archive') as db:
                yield db
            return
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def catalog(self):
        with self.connect() as db:
            sources = [dict(r) for r in db.execute('SELECT * FROM sources ORDER BY created_at DESC,filename')]
            for source in sources:
                sha = source['sha256']
                source['names'] = [r[0] for r in db.execute('SELECT filename FROM source_names WHERE sha256=? ORDER BY filename', (sha,))]
                job = db.execute('SELECT * FROM ingestion_jobs WHERE sha256=? ORDER BY rowid DESC LIMIT 1', (sha,)).fetchone()
                source['job'] = dict(job) if job else None
                source['status'] = job['status'] if job else 'completed'
                source['unit_count'] = db.execute('SELECT count(*) FROM source_units WHERE run_id=?', (source['current_run'],)).fetchone()[0]
                run = db.execute('SELECT * FROM extraction_runs WHERE id=?', (source['current_run'],)).fetchone()
                source['warnings'] = json.loads(run['warnings_json']) if run else []
            return sources

    def source(self, sha):
        with self.connect() as db:
            row = db.execute('SELECT * FROM sources WHERE sha256=?', (sha,)).fetchone()
            if row is None:
                raise Missing('Archive source not found.')
            return dict(row)

    def original(self, sha):
        source = self.source(sha)
        path = self.originals / source['sha256']
        if self.storage is not None:
            self.storage.cache(source['sha256'], path)
        if not path.is_file():
            raise Missing('Original file is missing from storage. Restore it from backup.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise Conflict('Original checksum verification failed. Restore it from backup before use.')
        return source, path

    def stage(self, filename, stream, max_bytes=32 * 1024 * 1024):
        filename = filename.replace('\\', '/').rsplit('/', 1)[-1]
        if not filename or len(filename) > 240 or any(ord(c) < 32 for c in filename):
            raise ValueError('Use a filename under 241 characters without control characters.')
        if Path(filename).suffix.lower() not in SUPPORTED:
            raise ValueError('Supported: CSV, MD, TXT, PDF, DOCX, PNG, JPEG, WEBP, GIF, TIFF, BMP.')
        digest, size = hashlib.sha256(), 0
        with tempfile.NamedTemporaryFile(dir=self.root, prefix='upload-', delete=False) as temp:
            temp_path = Path(temp.name)
            try:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError('Upload exceeds the 32 MiB per-file limit.')
                    digest.update(chunk)
                    temp.write(chunk)
            except BaseException:
                temp.close()
                temp_path.unlink(missing_ok=True)
                raise
        sha = digest.hexdigest()
        try:
            if self.storage is not None:
                self.storage.put(sha, temp_path)
            target = self.originals / sha
            # Serialize staging and queue changes. File bytes are durable before the job appears.
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if target.exists():
                    if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
                        raise ValueError('Stored original failed checksum verification; restore from backup.')
                else:
                    temp_path.replace(target)
                existing = db.execute('SELECT * FROM sources WHERE sha256=?', (sha,)).fetchone()
                db.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?,?,NULL)', (sha, filename, size, timestamp()))
                db.execute('INSERT OR IGNORE INTO source_names VALUES(?,?)', (sha, filename))
                job = db.execute('SELECT * FROM ingestion_jobs WHERE sha256=? ORDER BY rowid DESC LIMIT 1', (sha,)).fetchone()
                if not existing:
                    job = self._queue(db, sha, filename)
                return {'sha256': sha, 'duplicate': existing is not None, 'job': dict(job) if job else None}
        finally:
            temp_path.unlink(missing_ok=True)

    def _queue(self, db, sha, filename):
        identifier, stamp = str(uuid4()), timestamp()
        db.execute('INSERT INTO ingestion_jobs VALUES(?,?,?,?,?,?,?,?)',
                   (identifier, sha, filename, 'queued', 0, stamp, stamp, None))
        return db.execute('SELECT * FROM ingestion_jobs WHERE id=?', (identifier,)).fetchone()

    def reprocess(self, sha):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            source = db.execute('SELECT * FROM sources WHERE sha256=?', (sha,)).fetchone()
            if source is None:
                raise Missing('Archive source not found.')
            if db.execute("SELECT 1 FROM ingestion_jobs WHERE sha256=? AND status IN ('queued','processing')", (sha,)).fetchone():
                raise Conflict('This source already has an active import job.')
            return dict(self._queue(db, sha, source['filename']))

    def recover(self):
        with self.connect() as db:
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=240 if self.database else 0)).isoformat()
            db.execute("UPDATE ingestion_jobs SET status='failed',updated_at=?,error='Repeated interrupted extraction. Inspect resource limits before explicitly reprocessing.' WHERE status='processing' AND updated_at<=? AND attempt>=3", (timestamp(), cutoff))
            db.execute("UPDATE ingestion_jobs SET status='queued',updated_at=?,error='Resuming after an interrupted process.' WHERE status='processing' AND updated_at<=?", (timestamp(), cutoff))

    def claim_job(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT * FROM ingestion_jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if job is None:
                return None
            db.execute("UPDATE ingestion_jobs SET status='processing',attempt=attempt+1,error=NULL,updated_at=? WHERE id=?", (timestamp(), job['id']))
            return dict(db.execute('SELECT * FROM ingestion_jobs WHERE id=?', (job['id'],)).fetchone())

    def process_one(self):
        job = self.claim_job()
        if job is None:
            return False
        try:
            _, path = self.original(job['sha256'])
            result = subprocess.run([sys.executable, '-m', 'app.extract', str(path.resolve()), job['filename']],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=180)
            parsed = json.loads(result.stdout)
            if result.returncode or 'error' in parsed:
                raise ValueError(parsed.get('error', 'Local extraction failed.'))
            if parsed['sha256'] != job['sha256']:
                raise ValueError('Original checksum mismatch. Restore the original before retrying.')
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                owned = db.execute('SELECT status,attempt FROM ingestion_jobs WHERE id=?', (job['id'],)).fetchone()
                if owned['status'] != 'processing' or owned['attempt'] != job['attempt']:
                    return True
                run = str(uuid4())
                db.execute('INSERT INTO extraction_runs VALUES(?,?,?,?,?)',
                           (run, job['sha256'], parsed['extractor'], json.dumps(parsed['warnings']), timestamp()))
                db.executemany('INSERT INTO source_units VALUES(?,?,?,?,?,?)',
                               [(run, n, unit['kind'], json.dumps(unit['location']), unit['content'], json.dumps(unit['payload'], ensure_ascii=False))
                                for n, unit in enumerate(parsed['units'], 1)])
                db.execute('UPDATE sources SET current_run=? WHERE sha256=?', (run, job['sha256']))
                db.execute("UPDATE ingestion_jobs SET status='completed',error=NULL,updated_at=? WHERE id=?", (timestamp(), job['id']))
        except Exception as exc:
            error = 'Extraction timed out after 180 seconds; original preserved.' if isinstance(exc, subprocess.TimeoutExpired) else str(exc)[:700]
            with self.connect() as db:
                db.execute("UPDATE ingestion_jobs SET status='failed',error=?,updated_at=? WHERE id=? AND status='processing' AND attempt=?", (error, timestamp(), job['id'], job['attempt']))
        return True

    def start(self):
        self.recover()
        self.stop.clear()
        def work():
            while not self.stop.is_set():
                try:
                    active = self.process_one()
                    if not active and self.database is not None:
                        self.recover()
                except Exception:
                    active = False
                if not active:
                    self.stop.wait(3 if self.database else 0.4)
        self.thread = threading.Thread(target=work, name='archive-ingestion', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            # Extraction subprocesses have a bounded timeout. Do not release the
            # server ownership lock while this worker can still commit a result.
            self.thread.join()

    def detail(self, sha, offset=0, limit=50, run_id=None):
        source = self.source(sha)
        with self.connect() as db:
            runs = [dict(r) for r in db.execute('SELECT * FROM extraction_runs WHERE sha256=? ORDER BY rowid DESC', (sha,))]
            for run in runs:
                run['warnings'] = json.loads(run.pop('warnings_json'))
            chosen = run_id or source['current_run']
            if chosen and chosen not in {run['id'] for run in runs}:
                raise Missing('Extraction revision not found for this source.')
            units = [dict(r) for r in db.execute('SELECT * FROM source_units WHERE run_id=? ORDER BY ordinal LIMIT ? OFFSET ?', (chosen, limit, offset))]
            for unit in units:
                unit['location'] = json.loads(unit.pop('location_json'))
                unit['payload'] = json.loads(unit.pop('payload_json'))
            count = db.execute('SELECT count(*) FROM source_units WHERE run_id=?', (chosen,)).fetchone()[0]
        return {'source': source, 'runs': runs, 'selected_run': chosen, 'units': units, 'total': count, 'offset': offset}

    def inventory(self):
        sources = self.catalog()
        received = {name for source in sources for name in source['names']}
        manifests = [s for s in sources if s['filename'] == '00_MANIFEST.md']
        references = set()
        for source in manifests:
            detail = self.detail(source['sha256'], limit=100)
            for unit in detail['units']:
                for name in re.findall(r'^\|\s*([^|]+?)\s*\|', unit['content'], flags=re.M):
                    if Path(name).suffix.lower() in SUPPORTED | {'.png'}:
                        references.add(name.strip())
        return {'references': sorted(references), 'received': sorted(references & received),
                'outstanding': sorted(references - received),
                'note': 'Filename matches only; similarly named files are not assumed to be replacements.'}

    def export(self, runtime_store=None):
        """Consistent SQLite snapshot plus byte-verified originals; excludes runtime secrets."""
        handle = tempfile.NamedTemporaryFile(dir=self.root, prefix='archive-export-', suffix='.zip', delete=False)
        path = Path(handle.name)
        handle.close()
        try:
            with tempfile.TemporaryDirectory(dir=self.root) as directory:
                snapshot = Path(directory) / 'archive.sqlite3'
                with self.connect() as live, sqlite3.connect(snapshot) as backup:
                    if runtime_store is not None and self.database is None:
                        live.execute('BEGIN')
                    live.backup(backup)
                    if runtime_store is not None:
                        with runtime_store.connect() as runtime_live, sqlite3.connect(Path(directory) / 'runtime.sqlite3') as runtime_backup:
                            if runtime_store.database is None:
                                runtime_live.execute('BEGIN')
                            runtime_live.backup(runtime_backup)
                with sqlite3.connect(snapshot) as db:
                    sources = db.execute('SELECT sha256,filename,size_bytes FROM sources ORDER BY sha256').fetchall()
                    integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
                    if integrity != 'ok':
                        raise ValueError('Archive database integrity check failed.')
                manifest = []
                with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
                    bundle.write(snapshot, 'archive.sqlite3')
                    for sha, filename, size in sources:
                        try:
                            _, original = self.original(sha)
                        except (Missing, Conflict):
                            raise ValueError('An original is missing or failed verification. Export stopped; restore from backup.') from None
                        if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest() != sha:
                            raise ValueError('An original is missing or failed verification. Export stopped; restore from backup.')
                        bundle.write(original, 'originals/' + sha)
                        manifest.append({'sha256': sha, 'filename': filename, 'size_bytes': size})
                    metadata = {'sources': manifest, 'created_at': timestamp(), 'integrity_check': 'ok'}
                    if runtime_store is not None:
                        runtime_path = Path(directory) / 'runtime.sqlite3'
                        with sqlite3.connect(runtime_path) as runtime_db:
                            if runtime_db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or runtime_db.execute('PRAGMA foreign_key_check').fetchall():
                                raise ValueError('Conversation backup verification failed.')
                        bundle.write(runtime_path, 'runtime.sqlite3')
                        metadata['runtime_sha256'] = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
                    bundle.writestr('manifest.json', json.dumps(metadata, indent=2))
            return path
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def restore(self, stream):
        """Restore verified evidence into an EMPTY archive, never over personal work."""
        from scripts.verify_archive_backup import verify
        allowed_tables = {
            'imports', 'records', 'sources', 'source_names', 'ingestion_jobs', 'extraction_runs', 'source_units',
            'reconstruction_records', 'reconstruction_revisions', 'reconstruction_relations',
            'persona_revisions', 'persona_events', 'reconciliation_reports', 'reconciliation_reviews',
        }
        with tempfile.TemporaryDirectory(dir=self.root, prefix='archive-restore-') as directory:
            directory = Path(directory)
            package = directory / 'upload.zip'
            size = 0
            with package.open('xb') as output:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > 32 * 1024 * 1024:
                        raise ValueError('Backup upload exceeds 32 MiB.')
                    output.write(chunk)
            with zipfile.ZipFile(package) as bundle:
                if sum(info.file_size for info in bundle.infolist()) > 512 * 1024 * 1024:
                    raise ValueError('Expanded backup exceeds 512 MiB.')
                for member in bundle.infolist():
                    name = member.filename
                    valid = name in ('archive.sqlite3', 'manifest.json') or (
                        name.startswith('originals/') and len(name) == 74
                        and all(c in '0123456789abcdef' for c in name[10:]))
                    if not valid:
                        raise ValueError('Unexpected path in archive backup. Restore rejected.')
                if len({i.filename for i in bundle.infolist()}) != len(bundle.infolist()):
                    raise ValueError('Backup contains duplicate paths.')
                # Validation reads and hashes data; no source instructions or SQL schema is executed.
                result = verify(package)
                snapshot = directory / 'snapshot.sqlite3'
                snapshot.write_bytes(bundle.read('archive.sqlite3'))
                with sqlite3.connect(snapshot) as source, self.connect() as target:
                    source.row_factory = sqlite3.Row
                    source_tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                    if not source_tables <= allowed_tables:
                        raise ValueError('Backup schema contains unsupported tables. Use a compatible app version.')
                    target.execute('BEGIN IMMEDIATE')
                    target.execute('PRAGMA defer_foreign_keys=ON')
                    for table in allowed_tables:
                        exists = target.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                        if exists and target.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
                            raise Conflict('Restore requires an empty archive and reconstruction workspace. Existing work was not overwritten.')
                    # The only legacy table definitions come from application code, never uploaded SQL.
                    target.execute('CREATE TABLE IF NOT EXISTS imports (sha256 TEXT PRIMARY KEY, filename TEXT NOT NULL, imported_at TEXT NOT NULL, columns_json TEXT NOT NULL, row_count INTEGER NOT NULL)')
                    target.execute('CREATE TABLE IF NOT EXISTS records (import_sha256 TEXT NOT NULL REFERENCES imports(sha256), row_number INTEGER NOT NULL, record_id TEXT, payload_json TEXT NOT NULL, PRIMARY KEY(import_sha256,row_number))')
                    for table in source_tables:
                        source_columns = [r[1] for r in source.execute(f'PRAGMA table_info("{table}")')]
                        target_columns = [r[1] for r in target.execute(f'PRAGMA table_info("{table}")')]
                        if source_columns != target_columns:
                            raise ValueError('Backup table layout is incompatible; nothing was replaced.')
                        columns = ','.join('"' + c.replace('"', '""') + '"' for c in target_columns)
                        placeholders = ','.join('?' for _ in target_columns)
                        target.executemany(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
                                           [tuple(row) for row in source.execute(f'SELECT * FROM "{table}" ORDER BY rowid')])
                    if target.execute('PRAGMA foreign_key_check').fetchall():
                        raise ValueError('Restored archive has broken references. Nothing was committed.')
                    for name in bundle.namelist():
                        if name.startswith('originals/'):
                            raw = bundle.read(name)
                            sha = name.split('/')[1]
                            if hashlib.sha256(raw).hexdigest() != sha:
                                raise ValueError('Original checksum mismatch.')
                            destination = self.originals / sha
                            if destination.exists():
                                if destination.read_bytes() != raw:
                                    raise Conflict('An existing original differs from its checksum. Restore stopped.')
                            else:
                                with destination.open('xb') as output:
                                    output.write(raw)
                            if self.storage is not None:
                                self.storage.put(sha, destination)
                    if self.database is not None:
                        target.sync_sequences()
                    # An interrupted extraction is safe to resume on the newly restored host.
                    target.execute("UPDATE ingestion_jobs SET status='queued',updated_at=? WHERE status='processing'", (timestamp(),))
            return {**result, 'restored': True, 'note': 'Conversations and credentials were not changed. Restored persona configuration is retained.'}
