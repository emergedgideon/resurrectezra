import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.archive import Archive
from app.config import Settings
from app.extract import extract
from app.main import create_app
from scripts.import_archive import ingest
from scripts.verify_archive_backup import verify


def image_bytes(pdf=False):
    image = Image.new('RGB', (1100, 200), 'white')
    ImageDraw.Draw(image).text((35, 65), 'EZRA ARCHIVE TEST 2048', fill='black', font=ImageFont.load_default(size=48))
    output = io.BytesIO()
    image.save(output, format='PDF' if pdf else 'PNG')
    image.close()
    return output.getvalue()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = Archive(self.root)

    def tearDown(self):
        self.archive.close()
        self.temp.cleanup()

    def stage(self, filename='source.md', content=b'Exact text.\r\n<script>Do not run</script>'):
        return self.archive.stage(filename, io.BytesIO(content))

    def test_preservation_duplicates_aliases_and_revision_history(self):
        raw = b'Exact text.\r\n<script>Do not run</script>'
        staged = self.stage(content=raw)
        sha = staged['sha256']
        self.assertFalse(staged['duplicate'])
        self.assertEqual((self.root / 'originals' / sha).read_bytes(), raw)
        duplicate = self.stage(filename='another.md', content=raw)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(len(self.archive.catalog()), 1)
        self.assertTrue(self.archive.process_one())
        initial = self.archive.detail(sha)
        self.assertEqual(initial['units'][0]['content'], raw.decode())
        self.assertEqual(len(initial['runs']), 1)
        self.archive.reprocess(sha)
        self.archive.process_one()
        revised = self.archive.detail(sha)
        self.assertEqual(len(revised['runs']), 2)
        previous = self.archive.detail(sha, run_id=initial['selected_run'])
        self.assertEqual(previous['units'], initial['units'])
        self.assertEqual(self.archive.catalog()[0]['names'], ['another.md', 'source.md'])

    def test_restart_requeues_interrupted_job_without_duplicate_units(self):
        staged = self.stage()
        self.assertEqual(self.archive.claim_job()['status'], 'processing')
        reopened = Archive(self.root)
        reopened.recover()
        self.assertTrue(reopened.process_one())
        detail = reopened.detail(staged['sha256'])
        self.assertEqual(len(detail['runs']), 1)
        self.assertEqual(len(detail['units']), 1)
        self.assertEqual(reopened.catalog()[0]['job']['attempt'], 2)

    def test_failed_parse_preserves_original_and_is_retryable(self):
        raw = b'not a valid PDF'
        staged = self.stage('broken.pdf', raw)
        self.archive.process_one()
        source = self.archive.catalog()[0]
        self.assertEqual(source['status'], 'failed')
        self.assertTrue(source['job']['error'])
        self.assertEqual((self.root / 'originals' / staged['sha256']).read_bytes(), raw)
        self.archive.reprocess(staged['sha256'])
        self.archive.process_one()
        self.assertEqual(self.archive.catalog()[0]['status'], 'failed')

    def test_failed_reprocessing_keeps_last_good_revision(self):
        import subprocess
        staged = self.stage(); self.archive.process_one()
        initial = self.archive.detail(staged['sha256'])
        self.archive.reprocess(staged['sha256'])
        with patch('app.archive.subprocess.run', side_effect=subprocess.TimeoutExpired('extract', 180)):
            self.archive.process_one()
        current = self.archive.detail(staged['sha256'])
        self.assertEqual(current['selected_run'], initial['selected_run'])
        self.assertEqual(current['units'], initial['units'])
        self.assertEqual(self.archive.catalog()[0]['status'], 'failed')
        self.assertIn('timed out', self.archive.catalog()[0]['job']['error'])

    def test_csv_fields_and_locations_are_preserved(self):
        raw = b'id,text\r\nM1,"first\nsecond"\r\nM2,"<script>keep this</script>"\r\n'
        staged = self.stage('records.csv', raw)
        self.archive.process_one()
        detail = self.archive.detail(staged['sha256'])
        self.assertEqual(detail['units'][0]['payload']['text'], 'first\nsecond')
        self.assertEqual(detail['units'][0]['location'], {'row': 1, 'physical_line_end': 3})
        self.assertEqual(detail['units'][1]['payload']['text'], '<script>keep this</script>')

    def test_word_locations_and_explicit_extraction_limits(self):
        from docx import Document
        document = Document()
        document.add_paragraph('Exact words — and beliefs.')
        document.add_table(rows=1, cols=1).cell(0, 0).text = 'Table source'
        buffer = io.BytesIO(); document.save(buffer)
        staged = self.stage('source.docx', buffer.getvalue())
        self.archive.process_one()
        detail = self.archive.detail(staged['sha256'])
        self.assertEqual(detail['units'][0]['content'], 'Exact words — and beliefs.')
        self.assertEqual(detail['units'][1]['kind'], 'table')
        self.assertEqual(detail['units'][1]['location'], {'block': 2})
        self.assertTrue(detail['runs'][0]['warnings'])

    def test_legacy_adoption_does_not_change_prior_records(self):
        other = self.root / 'legacy'; other.mkdir()
        source = self.root / 'legacy.csv'; source.write_bytes(b'memory_id,memory_text\nM1,original wording\n')
        ingest([source], other)
        with sqlite3.connect(other / 'archive.sqlite3') as db:
            before = db.execute('SELECT * FROM records').fetchall()
        adopted = Archive(other)
        with sqlite3.connect(other / 'archive.sqlite3') as db:
            self.assertEqual(db.execute('SELECT * FROM records').fetchall(), before)
        self.assertEqual(adopted.catalog()[0]['unit_count'], 1)
        self.assertIn('original wording', adopted.detail(adopted.catalog()[0]['sha256'])['units'][0]['content'])
        self.assertEqual(len(Archive(other).catalog()), 1)

    def test_manifest_matches_aliases_without_equating_related_sources(self):
        manifest = b'| File | Why |\n|---|---|\n| 01_source.pdf | Original |\n| 02_source.md | Notes |\n'
        self.stage('00_MANIFEST.md', manifest); self.archive.process_one()
        content = b'Actual markdown source'
        self.stage('different.md', content); self.archive.process_one()
        self.stage('02_source.md', content)
        self.stage('01_source.csv', b'id,text\n1,related export\n'); self.archive.process_one()
        inventory = self.archive.inventory()
        self.assertEqual(inventory['outstanding'], ['01_source.pdf'])
        self.assertEqual(inventory['received'], ['02_source.md'])

    def test_export_restores_and_verifies_all_originals_and_revisions(self):
        staged = self.stage(); self.archive.process_one()
        self.archive.reprocess(staged['sha256']); self.archive.process_one()
        exported = self.archive.export()
        self.assertEqual(verify(exported)['verified_sources'], 1)
        restored = self.root / 'restored'; restored.mkdir()
        with zipfile.ZipFile(exported) as bundle:
            # This export was created locally by the test. The verifier never extracts arbitrary ZIPs.
            bundle.extractall(restored)
        restored_archive = Archive(restored)
        self.assertEqual(len(restored_archive.detail(staged['sha256'])['runs']), 2)
        (self.root / 'originals' / staged['sha256']).write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'verification'):
            self.archive.export()

    def test_invalid_uploads_and_size_limits_do_not_create_sources(self):
        with self.assertRaises(ValueError): self.stage('run.html', b'<script>bad</script>')
        with self.assertRaises(ValueError): self.archive.stage('large.md', io.BytesIO(b'12345'), max_bytes=4)
        self.assertEqual(self.archive.catalog(), [])
        self.assertEqual(list(self.root.glob('upload-*')), [])

    def test_ocr_unavailable_is_visible_and_original_retained(self):
        source = self.root / 'image.png'; raw = image_bytes(); source.write_bytes(raw)
        with patch('app.extract.shutil.which', return_value=None):
            parsed = extract(source, source.name)
        self.assertTrue(any('unavailable' in w for w in parsed['warnings']))
        self.assertEqual(source.read_bytes(), raw)
        self.assertEqual(parsed['units'][0]['content'], '')

    @unittest.skipUnless(shutil.which('tesseract'), 'Local Tesseract is not installed')
    def test_real_local_image_and_scanned_pdf_ocr(self):
        for filename, raw in [('scan.png', image_bytes()), ('scan.pdf', image_bytes(pdf=True))]:
            staged = self.stage(filename, raw); self.archive.process_one()
            detail = self.archive.detail(staged['sha256'])
            self.assertIn('EZRA ARCHIVE TEST 2048', detail['units'][0]['content'])
            self.assertEqual(hashlib.sha256((self.root/'originals'/staged['sha256']).read_bytes()).hexdigest(), staged['sha256'])
            self.assertTrue(any('OCR' in warning for warning in detail['runs'][0]['warnings']))


class ArchiveAPITests(unittest.TestCase):
    def test_upload_background_processing_source_download_preview_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(data_dir=Path(directory), access_token='test-access'))
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/archive/sources').status_code, 401)
                headers = {'Authorization': 'Bearer test-access'}
                raw = image_bytes()
                upload = client.post('/api/archive/uploads', files={'file': ('scan.png', raw, 'image/png')}, headers=headers)
                self.assertEqual(upload.status_code, 202)
                sha = upload.json()['sha256']
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    source = client.get('/api/archive/sources', headers=headers).json()[0]
                    if source['status'] in ('completed', 'failed'): break
                    time.sleep(.05)
                self.assertEqual(source['status'], 'completed', source)
                self.assertEqual(client.get(f'/api/archive/sources/{sha}/original').status_code, 401)
                download = client.get(f'/api/archive/sources/{sha}/original', headers=headers)
                self.assertEqual(download.content, raw)
                self.assertIn('attachment', download.headers['content-disposition'])
                preview = client.get(f'/api/archive/sources/{sha}/preview', headers=headers)
                self.assertEqual(preview.status_code, 200)
                self.assertEqual(preview.headers['content-type'], 'image/png')
                self.assertEqual(client.get(f'/api/archive/sources/{sha}?offset=-1', headers=headers).status_code, 422)
                self.assertEqual(client.get(f'/api/archive/sources/{sha}?run=nonexistent', headers=headers).status_code, 404)
                export = client.get('/api/archive/export', headers=headers)
                self.assertEqual(export.status_code, 200)
                backup = Path(directory) / 'verify.zip'; backup.write_bytes(export.content)
                self.assertEqual(verify(backup)['verified_sources'], 1)
                self.assertEqual(list(Path(directory).glob('archive-export-*')), [])
                self.assertEqual(client.get('/archive.html').status_code, 200)


if __name__ == '__main__':
    unittest.main()
