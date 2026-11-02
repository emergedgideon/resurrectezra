"""Verify an exported archive without restoring or executing its contents."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def verify(path):
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        with tempfile.TemporaryDirectory(prefix='ezra-backup-check-') as directory:
            snapshot = Path(directory) / 'archive.sqlite3'
            snapshot.write_bytes(bundle.read('archive.sqlite3'))
            with sqlite3.connect(snapshot) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Database integrity check failed.')
                if db.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('Database contains broken source links.')
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'reconstruction_revisions' in tables:
                    for body_json, in db.execute('SELECT body_json FROM reconstruction_revisions'):
                        body = json.loads(body_json)
                        for citation in body['citations']:
                            row = db.execute('''SELECT u.content,u.payload_json FROM source_units u
                                JOIN extraction_runs r ON r.id=u.run_id
                                WHERE u.run_id=? AND u.ordinal=? AND r.sha256=?''',
                                (citation['run_id'], citation['ordinal'], citation['sha256'])).fetchone()
                            if row is None:
                                raise ValueError('Reconstruction evidence passage is missing.')
                            text = row[0] if citation['field'] == '$content' else json.loads(row[1]).get(citation['field'])
                            if not isinstance(text, str) or text[citation['start']:citation['end']] != citation['quote']:
                                raise ValueError('Reconstruction evidence quotation mismatch.')
                if 'persona_revisions' in tables:
                    for items_json, in db.execute('SELECT record_revisions_json FROM persona_revisions'):
                        for revision_id in json.loads(items_json):
                            if not db.execute('SELECT 1 FROM reconstruction_revisions WHERE id=?', (revision_id,)).fetchone():
                                raise ValueError('Persona refers to a missing reconstruction revision.')
                sources = {r[0]: (r[1], r[2]) for r in db.execute('SELECT sha256,filename,size_bytes FROM sources')}
                if len(sources) != len(manifest['sources']):
                    raise ValueError('Manifest/source count mismatch.')
                seen = set()
                for source in manifest['sources']:
                    sha = source['sha256']
                    if sha in seen or sources.get(sha) != (source['filename'], source['size_bytes']):
                        raise ValueError('Manifest/source metadata mismatch.')
                    seen.add(sha)
                    raw = bundle.read('originals/' + sha)
                    if len(raw) != source['size_bytes'] or hashlib.sha256(raw).hexdigest() != sha:
                        raise ValueError('Original checksum or byte count mismatch.')
        return {'verified_sources': len(sources), 'database_integrity': 'ok', 'original_checksums': 'ok'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    print(json.dumps(verify(parser.parse_args().backup), indent=2))
