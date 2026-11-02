from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.archive import Archive
from app.cloud_storage import SupabaseStorage
from app.config import Settings
from app.database import PersistenceError, Postgres
from app.main import create_app
from app.reconstruction import Reconstruction
from app.store import Conflict, Store
from scripts.start_render import arguments
from scripts.verify_archive_backup import verify


class MemoryStorage:
    """HTTP-level Supabase Storage double. No real account or private keys."""
    def __init__(self):
        self.objects = {}
        self.public = False
        self.fail = False
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        if self.fail:
            return httpx.Response(503, text='simulated private storage error')
        if request.url.path.startswith('/storage/v1/bucket/'):
            return httpx.Response(200, json={'public': self.public})
        prefix = '/storage/v1/object/'
        name = request.url.path.removeprefix(prefix).removeprefix('authenticated/')
        if request.method == 'POST':
            assert request.headers['x-upsert'] == 'false'
            if name in self.objects:
                return httpx.Response(409)
            self.objects[name] = request.content
            return httpx.Response(200, json={'Key': name})
        return httpx.Response(200, content=self.objects[name]) if name in self.objects else httpx.Response(404)

    def client(self):
        return SupabaseStorage('https://example.supabase.co', 'synthetic-server-key', 'ezra-private', self.transport)


class CloudConfigurationTests(unittest.TestCase):
    def test_separate_database_password_is_encoded_without_exposure(self):
        from urllib.parse import unquote
        password = 'synthetic@/%:#?[] complex'
        backend = Postgres('postgresql://postgres.test:[YOUR-PASSWORD]@example.pooler.supabase.com:5432/postgres', password)
        parsed = urlparse(backend.conninfo())
        self.assertEqual(unquote(parsed.password), password)
        self.assertEqual(parsed.hostname, 'example.pooler.supabase.com')
        self.assertNotIn(password, repr(backend))
    def test_local_full_backup_includes_verified_conversations(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(Path(directory)); Reconstruction(archive)
            store = Store(Path(directory))
            store.create_conversation('Local full backup')
            complete = archive.export(store)
            self.assertEqual(verify(complete)['verified_sources'], 0)
            import zipfile, sqlite3
            with zipfile.ZipFile(complete) as bundle:
                snapshot = Path(directory) / 'runtime-export.sqlite3'; snapshot.write_bytes(bundle.read('runtime.sqlite3'))
            with sqlite3.connect(snapshot) as db:
                self.assertEqual(db.execute('SELECT title FROM conversations').fetchone()[0], 'Local full backup')

    def test_no_ephemeral_render_startup_and_no_short_app_password(self):
        with self.assertRaises(ValueError): arguments({})
        environment = {'RENDER': 'true', 'EZRA_DATABASE_URL': 'synthetic', 'SUPABASE_URL': 'https://example.supabase.co',
                       'SUPABASE_SERVICE_ROLE_KEY': 'synthetic', 'EZRA_ACCESS_TOKEN': 'x' * 30, 'PORT': '10000'}
        argv = arguments(environment)
        self.assertIn('10000', argv)
        self.assertNotIn('synthetic', ' '.join(argv))
        with self.assertRaises(ValueError): Settings(supabase_url='https://example.supabase.co')
        with self.assertRaises(ValueError): Settings(database_url='postgresql://localhost/db', supabase_url='https://example.supabase.co', supabase_key='synthetic')

    def test_immutable_objects_checksums_cache_and_failures(self):
        fake = MemoryStorage(); client = fake.client()
        client.validate_bucket()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'original'; raw = b'Exact original\r\nunchanged'; path.write_bytes(raw)
            sha = hashlib.sha256(raw).hexdigest()
            client.put(sha, path); client.put(sha, path)
            path.unlink(); client.cache(sha, path)
            self.assertEqual(path.read_bytes(), raw)
            fake.objects['ezra-private/originals/' + sha] = b'corrupt'
            path.unlink()
            with self.assertRaises(PersistenceError): client.cache(sha, path)
            self.assertFalse(path.exists())
            fake.public = True
            with self.assertRaises(PersistenceError): client.validate_bucket()
            fake.fail = True
            with self.assertRaises(PersistenceError) as caught: client.get(sha)
            self.assertNotIn('synthetic-server-key', str(caught.exception))


PG_URL = os.getenv('EZRA_TEST_POSTGRES_URL', '')


@unittest.skipUnless(PG_URL, 'Set EZRA_TEST_POSTGRES_URL to an isolated local PostgreSQL test database')
class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        parsed = urlparse(PG_URL)
        if parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.path != '/ezra_test':
            raise RuntimeError('Destructive integration reset is restricted to local ezra_test only.')
        with psycopg.connect(PG_URL, autocommit=True) as db:
            db.execute('DROP SCHEMA IF EXISTS ezra_archive CASCADE')
            db.execute('DROP SCHEMA IF EXISTS ezra_runtime CASCADE')
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = Postgres(PG_URL)
        self.fake = MemoryStorage()
        self.storage = self.fake.client()
        self.store = Store(self.root, self.database)
        self.archive = Archive(self.root, self.database, self.storage)
        self.recon = Reconstruction(self.archive)

    def tearDown(self):
        self.archive.close()
        self.temp.cleanup()

    def test_conversation_commit_idempotency_and_cache_loss(self):
        c = self.store.create_conversation('Persistent cloud conversation')
        turn, claimed = self.store.claim(c['id'], 'request-one', 'Original user wording.')
        self.assertTrue(claimed)
        self.store.complete(turn, 'Original reply.', 'test-model', {})
        other = self.root / 'new-render-disk'
        reopened = Store(other, self.database)
        restored = reopened.detail(c['id'])
        self.assertEqual(restored['messages'][0]['content'], 'Original user wording.')
        self.assertTrue(restored['checkpoint'])
        _, claimed = reopened.claim(c['id'], 'request-one', 'Original user wording.')
        self.assertFalse(claimed)

    def test_originals_and_pending_import_survive_loss_of_all_cache_files(self):
        raw = b'# Original\r\nExact supplied belief.'
        staged = self.archive.stage('source.md', io.BytesIO(raw))
        fresh = Archive(self.root / 'fresh-disk', self.database, self.fake.client())
        self.assertTrue(fresh.process_one())
        self.assertEqual(fresh.detail(staged['sha256'])['units'][0]['content'], raw.decode())
        self.assertEqual((fresh.originals / staged['sha256']).read_bytes(), raw)
        duplicate = fresh.stage('alias.md', io.BytesIO(raw))
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(fresh.catalog()[0]['names'], ['alias.md', 'source.md'])

    def test_failed_storage_upload_never_queues_or_acknowledges_source(self):
        self.fake.fail = True
        with self.assertRaises(PersistenceError): self.archive.stage('source.md', io.BytesIO(b'Keep exactly.'))
        self.assertEqual(self.archive.catalog(), [])
        with self.archive.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ingestion_jobs').fetchone()[0], 0)

    def test_cloud_persona_versions_and_portable_sqlite_export(self):
        raw = b'Exact identity.'
        staged = self.archive.stage('source.md', io.BytesIO(raw)); self.archive.process_one()
        run = self.archive.source(staged['sha256'])['current_run']
        item = self.recon.create_record({'title': 'Identity', 'text': raw.decode(), 'kind': 'identity', 'origin': 'source_statement',
                                        'citations': [{'sha256': staged['sha256'], 'run_id': run, 'ordinal': 1}]})
        draft = self.recon.create_persona('Draft', [item['current']['id']]); self.recon.activate(draft['id'], 24000)
        exported = self.archive.export()
        self.assertEqual(verify(exported)['verified_sources'], 1)
        local = Archive(self.root / 'local-mac'); local_recon = Reconstruction(local)
        local.restore(io.BytesIO(exported.read_bytes()))
        self.assertEqual(local_recon.active()['compiled_text'], draft['compiled_text'])
        self.assertEqual(local_recon.record(item['id'])['current']['body']['text'], raw.decode())
        conversation = self.store.create_conversation('Portable conversation')
        complete_backup = self.archive.export(self.store)
        self.assertEqual(verify(complete_backup)['verified_sources'], 1)
        import zipfile, sqlite3
        with zipfile.ZipFile(complete_backup) as bundle:
            snapshot = self.root / 'runtime-snapshot.sqlite3'; snapshot.write_bytes(bundle.read('runtime.sqlite3'))
        with sqlite3.connect(snapshot) as db:
            self.assertEqual(db.execute('SELECT title FROM conversations WHERE id=?', (conversation['id'],)).fetchone()[0], 'Portable conversation')

    def test_sqlite_backup_restores_to_cloud_and_sequences_keep_advancing(self):
        local = Archive(self.root / 'local-seed'); local_recon = Reconstruction(local)
        local.stage('source.txt', io.BytesIO(b'Original.')); local.process_one()
        draft = local_recon.create_persona('Owner', [], 'Owner-provided instructions.')
        local_recon.activate(draft['id'], 24000)
        backup = local.export()
        self.archive.restore(io.BytesIO(backup.read_bytes()))
        self.assertEqual(self.recon.active()['id'], draft['id'])
        self.recon.deactivate(); self.recon.activate(draft['id'], 24000)
        self.assertEqual(len(self.recon.personas()['events']), 3)
        with self.assertRaises(Conflict): self.archive.restore(io.BytesIO(backup.read_bytes()))

    def test_overlapping_deploy_does_not_interrupt_fresh_turn_or_import(self):
        c = self.store.create_conversation('Active request')
        turn, _ = self.store.claim(c['id'], 'active', 'Do not interrupt.')
        self.store.recover(stale_seconds=180)
        self.assertEqual(self.store.detail(c['id'])['turns'][0]['status'], 'running')
        staged = self.archive.stage('source.md', io.BytesIO(b'Original.'))
        self.archive.claim_job(); self.archive.recover()
        self.assertEqual(self.archive.catalog()[0]['status'], 'processing')
        old = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
        with self.store.connect() as db: db.execute('UPDATE turns SET updated_at=? WHERE id=?', (old, turn['id']))
        self.store.recover(stale_seconds=180)
        new_turn = self.store.retry(c['id'], turn['id'])
        self.store.fail(turn, 'Old instance failure must not touch new attempt.')
        self.assertEqual(self.store.detail(c['id'])['turns'][0]['status'], 'running')
        with self.assertRaises(Conflict): self.store.complete(turn, 'Old late reply.', 'test', {})
        self.store.complete(new_turn, 'Current attempt reply.', 'test', {})
        with self.archive.connect() as db: db.execute('UPDATE ingestion_jobs SET updated_at=?', (old,))
        self.archive.recover(); self.assertTrue(self.archive.process_one())
        self.assertEqual(self.archive.catalog()[0]['job']['attempt'], 2)

    def test_atomic_concurrent_claims_across_separate_connections(self):
        c = self.store.create_conversation('Concurrent')
        def claim(number):
            try:
                self.store.claim(c['id'], str(number), str(number))
                return 'claimed'
            except Conflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(claim, [1, 2])), ['claimed', 'conflict'])

    def test_cloud_api_uses_real_postgres_and_never_returns_server_keys(self):
        class Provider:
            async def complete(self, messages): return 'Cloud test reply.', {}
        settings = Settings(data_dir=self.root / 'api-cache', database_url=PG_URL, supabase_url='https://example.supabase.co',
                            supabase_key='synthetic-server-key', access_token='application-test-password-long')
        with patch('app.main.SupabaseStorage', return_value=self.fake.client()):
            with TestClient(create_app(settings, Provider())) as client:
                headers = {'Authorization': 'Bearer application-test-password-long'}
                self.assertEqual(client.get('/healthz').json(), {'status': 'ok'})
                self.assertEqual(client.get('/api/status').status_code, 401)
                status = client.get('/api/status', headers=headers)
                self.assertEqual(status.json()['storage_backend'], 'supabase')
                self.assertNotIn('synthetic-server-key', status.text)
                c = client.post('/api/conversations', json={'title': 'Cloud API'}, headers=headers).json()
                result = client.post('/api/conversations/' + c['id'] + '/turns', json={'request_id': str(uuid4()), 'content': 'Keep my exact words.'}, headers=headers).json()
                self.assertEqual(result['turns'][0]['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
