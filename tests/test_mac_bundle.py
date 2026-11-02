import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app.archive import Archive
from app.store import Store
from mac.launcher import configure, seed_data
from scripts.build_mac_bundle import build


class MacBundleTests(unittest.TestCase):
    def test_transfer_preserves_archive_and_runtime_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'source-data'
            archive = Archive(data)
            raw = b'Original private words.\r\nNo changes.'
            source = archive.stage('original.md', io.BytesIO(raw)); archive.process_one()
            Store(data).create_conversation('Saved conversation')
            report = build(root / 'transfer.zip', data, 'test/model')
            self.assertEqual(report['verified_sources'], 1)
            extracted = root / 'unpacked'; extracted.mkdir()
            with zipfile.ZipFile(root / 'transfer.zip') as bundle:
                self.assertNotIn('Ezra/.env', bundle.namelist())
                self.assertNotIn('Ezra/data/runtime.lock', bundle.namelist())
                self.assertTrue((bundle.getinfo('Ezra/Setup.command').external_attr >> 16) & 0o111)
                bundle.extractall(extracted)
            state = root / 'personal-state'; state.mkdir()
            self.assertTrue(seed_data(extracted / 'Ezra', state))
            self.assertEqual((state / 'data' / 'originals' / source['sha256']).read_bytes(), raw)
            with sqlite3.connect(state / 'data' / 'runtime.sqlite3') as db:
                self.assertEqual(db.execute('SELECT title FROM conversations').fetchone()[0], 'Saved conversation')
            marker = state / 'data' / 'personal-note.txt'; marker.write_text('Keep local edits')
            self.assertFalse(seed_data(extracted / 'Ezra', state))
            self.assertEqual(marker.read_text(), 'Keep local edits')

    def test_local_configuration_is_private_and_uses_no_cloud_secret(self):
        from dotenv import dotenv_values
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state = root / 'state'; state.mkdir()
            (root / 'mac-defaults.json').write_text(json.dumps({'model': 'suggested/model'}))
            with patch('mac.launcher.getpass.getpass', return_value='local-test-key'), patch('builtins.input', return_value=''):
                configure(root, state)
            values = dotenv_values(state / '.env')
            self.assertEqual(values['FEATHERLESS_API_KEY'], 'local-test-key')
            self.assertEqual(values['FEATHERLESS_MODEL'], 'suggested/model')
            self.assertEqual((state / '.env').stat().st_mode & 0o777, 0o600)
            with patch('mac.launcher.getpass.getpass', side_effect=AssertionError('should not prompt')):
                configure(root, state)


if __name__ == '__main__':
    unittest.main()
