import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from fastapi.testclient import TestClient

from app.archive import Archive
from app.config import Settings
from app.main import create_app
from app.reconstruction import Reconstruction
from app.store import Conflict
from scripts.start_codespace import browser_url, configuration


class BrowserHostingTests(unittest.TestCase):
    def test_codespace_start_requires_private_app_password(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): configuration({'CODESPACES': 'true'}, Path(directory))
            with self.assertRaises(ValueError): configuration({'EZRA_ACCESS_TOKEN': 'x' * 30}, Path(directory))
            environment = {'CODESPACES': 'true', 'EZRA_ACCESS_TOKEN': 'x' * 30, 'FEATHERLESS_API_KEY': 'synthetic-only'}
            configured = configuration(environment, Path(directory))
            self.assertEqual(configured['EZRA_DATA_DIR'], str(Path(directory) / 'data'))
            self.assertEqual(environment.get('EZRA_DATA_DIR'), None)
            self.assertEqual(browser_url({'CODESPACE_NAME': 'test-example'}), 'https://test-example-8000.app.github.dev')
            self.assertIsNone(browser_url({'CODESPACE_NAME': '../bad'}))

    def test_verified_restore_preserves_persona_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Archive(root / 'source'); recon = Reconstruction(source)
            raw = b'Unchanged original.\r\nFull text.'
            staged = source.stage('original.md', io.BytesIO(raw)); source.process_one()
            item = recon.create_record({'title': 'Owner declaration', 'text': 'Exact owner belief.', 'kind': 'belief', 'origin': 'owner_statement'})
            persona = recon.create_persona('Draft', [item['current']['id']])
            exported = source.export(); package = exported.read_bytes()
            destination = Archive(root / 'destination'); Reconstruction(destination)
            report = destination.restore(io.BytesIO(package))
            self.assertEqual(report['verified_sources'], 1)
            self.assertEqual((destination.originals / staged['sha256']).read_bytes(), raw)
            restored = Reconstruction(destination)
            self.assertEqual(restored.persona(persona['id'])['compiled_text'], persona['compiled_text'])
            self.assertIsNone(restored.active())
            with self.assertRaises(Conflict): destination.restore(io.BytesIO(package))
            self.assertEqual(len(destination.catalog()), 1)

    def test_restore_does_not_overwrite_owner_records_in_an_empty_source_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Archive(root / 'source'); Reconstruction(source)
            source.stage('original.txt', io.BytesIO(b'Source words.')); source.process_one()
            package = source.export().read_bytes()
            target = Archive(root / 'target'); recon = Reconstruction(target)
            recon.create_record({'title': 'Keep me', 'text': 'Existing owner record.', 'kind': 'identity', 'origin': 'owner_statement'})
            with self.assertRaises(Conflict): target.restore(io.BytesIO(package))
            self.assertEqual(recon.records()['total'], 1)
            self.assertEqual(target.catalog(), [])

    def test_unsafe_paths_are_rejected_without_extracting(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(Path(directory)); Reconstruction(archive)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as package: package.writestr('../escape.txt', 'Do not write')
            with self.assertRaisesRegex(ValueError, 'Unexpected path'): archive.restore(io.BytesIO(buffer.getvalue()))
            self.assertFalse((Path(directory).parent / 'escape.txt').exists())
            self.assertEqual(archive.catalog(), [])

    def test_private_restore_api_keeps_conversations_and_credentials_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Archive(root / 'source'); Reconstruction(source)
            source.stage('original.md', io.BytesIO(b'Source material.')); source.process_one()
            package = source.export().read_bytes()
            settings = Settings(data_dir=root / 'destination', access_token='test-application-password')
            with TestClient(create_app(settings)) as client:
                headers = {'Authorization': 'Bearer test-application-password'}
                conversation = client.post('/api/conversations', json={'title': 'Keep conversation'}, headers=headers).json()
                self.assertEqual(client.post('/api/archive/restore', files={'file': ('backup.zip', package)}).status_code, 401)
                result = client.post('/api/archive/restore', files={'file': ('backup.zip', package)}, headers=headers)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertTrue(result.json()['restored'])
                self.assertEqual(client.get('/api/conversations/' + conversation['id'], headers=headers).status_code, 200)
                repeated = client.post('/api/archive/restore', files={'file': ('backup.zip', package)}, headers=headers)
                self.assertEqual(repeated.status_code, 409)
                malformed = client.post('/api/archive/restore', files={'file': ('broken.zip', b'not zip')}, headers=headers)
                self.assertEqual(malformed.status_code, 422)


if __name__ == '__main__':
    unittest.main()
