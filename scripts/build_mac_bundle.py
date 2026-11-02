"""Build a private transfer bundle using an explicit code/data allowlist."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.archive import Archive
from scripts.verify_archive_backup import verify


def build(output, data_dir, model=''):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    archive = Archive(data_dir)
    exported = archive.export()
    try:
        verified = verify(exported)
        with tempfile.TemporaryDirectory(prefix='ezra-mac-build-') as directory:
            staged = Path(directory) / 'Ezra'
            staged.mkdir()
            for folder in ('app', 'scripts', 'docs', 'mac', 'tests'):
                for source in (ROOT / folder).rglob('*'):
                    if source.is_file() and '__pycache__' not in source.parts and source.suffix in ('.py', '.html', '.css', '.js', '.md', '.sh', '.command'):
                        target = staged / source.relative_to(ROOT)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
            for name in ('requirements.txt', 'README.md', 'PROJECT_PLAN.md', 'PROJECT_STATE.md', 'AGENTS.md', '.gitignore', '.env.example'):
                shutil.copyfile(ROOT / name, staged / name)
            for name in ('Setup.command', 'Start.command', 'Stop.command', 'Configure.command'):
                shutil.copyfile(ROOT / 'mac' / name, staged / name)
                (staged / name).chmod(0o755)
            shutil.copyfile(ROOT / 'docs' / 'MAC_START_HERE.md', staged / 'START HERE.md')
            shutil.copyfile(exported, staged / 'starter-archive.zip')
            runtime = Path(data_dir) / 'runtime.sqlite3'
            if runtime.exists():
                with sqlite3.connect(runtime) as source, sqlite3.connect(staged / 'starter-runtime.sqlite3') as target:
                    source.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Runtime snapshot integrity check failed.')
            (staged / 'mac-defaults.json').write_text(json.dumps({'model': model, 'base_url': 'https://api.featherless.ai/v1'}, indent=2))
            files = {}
            for source in staged.rglob('*'):
                if source.is_file():
                    files[str(source.relative_to(staged))] = hashlib.sha256(source.read_bytes()).hexdigest()
            (staged / 'BUNDLE_MANIFEST.json').write_text(json.dumps({'files': files, 'originals_verified': verified['verified_sources'], 'credentials_included': False}, indent=2))
            temp_output = output.with_suffix('.zip.tmp')
            with zipfile.ZipFile(temp_output, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
                for source in sorted(staged.rglob('*')):
                    if source.is_file():
                        bundle.write(source, 'Ezra/' + str(source.relative_to(staged)))
            with zipfile.ZipFile(temp_output) as bundle:
                if bundle.testzip() is not None:
                    raise ValueError('Transfer ZIP failed verification.')
                for name, digest in files.items():
                    if hashlib.sha256(bundle.read('Ezra/' + name)).hexdigest() != digest:
                        raise ValueError('Transfer file checksum mismatch.')
                if any(Path(name).name == '.env' or '/.git/' in name or '/.venv/' in name for name in bundle.namelist()):
                    raise ValueError('A prohibited local configuration path entered the bundle.')
            temp_output.replace(output)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        output.with_suffix('.sha256.txt').write_text(f'{digest}  {output.name}\n')
        return {'file': str(output), 'bytes': output.stat().st_size, 'sha256': digest, **verified, 'credentials_included': False}
    finally:
        exported.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'ezra-downloads' / 'Ezra-Mac-Starter.zip')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.data_dir, os.getenv('FEATHERLESS_MODEL', '')), indent=2))
