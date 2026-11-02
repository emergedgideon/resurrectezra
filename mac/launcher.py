"""Personal Mac installation/start helper. No cloud credentials are copied."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
import webbrowser
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = Path.home() / 'Library' / 'Application Support' / 'ResurrectEzra'


def seed_data(root, state):
    """First install only; never merge a seed over an existing personal database."""
    target = state / 'data'
    if (target / 'archive.sqlite3').exists():
        print('Existing archive found. Keeping your local data unchanged.')
        return False
    if target.exists() and any(target.iterdir()):
        raise RuntimeError('The data folder contains files but no archive database. Stop here and ask for help; nothing was overwritten.')
    bundle = root / 'starter-archive.zip'
    if not bundle.is_file():
        target.mkdir(parents=True, exist_ok=True)
        print('No starter archive supplied; starting with an empty library.')
        return False
    sys.path.insert(0, str(root))
    from scripts.verify_archive_backup import verify
    result = verify(bundle)
    with tempfile.TemporaryDirectory(dir=state, prefix='first-install-') as directory:
        extracted = Path(directory) / 'data'
        extracted.mkdir()
        with zipfile.ZipFile(bundle) as archive:
            for member in archive.infolist():
                name = member.filename
                allowed = name in ('archive.sqlite3', 'manifest.json') or (
                    name.startswith('originals/') and len(name) == len('originals/') + 64
                    and all(c in '0123456789abcdef' for c in name.split('/')[1]))
                if not allowed:
                    raise RuntimeError('Unexpected path in starter archive; nothing was installed.')
                destination = extracted / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open('xb') as output:
                    shutil.copyfileobj(source, output)
                destination.chmod(0o600)
        runtime = root / 'starter-runtime.sqlite3'
        if runtime.is_file():
            with sqlite3.connect(runtime) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Starter conversation database failed verification.')
            shutil.copy2(runtime, extracted / 'runtime.sqlite3')
            (extracted / 'runtime.sqlite3').chmod(0o600)
        if target.exists():
            target.rmdir()  # It was checked empty; refuse if that changed.
        extracted.rename(target)
    print(f'Installed and verified {result["verified_sources"]} original files and their archive records.')
    return True


def configure(root, state, force=False):
    from dotenv import dotenv_values, set_key
    path = state / '.env'
    values = dotenv_values(path) if path.exists() else {}
    defaults_file = root / 'mac-defaults.json'
    defaults = json.loads(defaults_file.read_text()) if defaults_file.exists() else {}
    if not values.get('FEATHERLESS_API_KEY') or force:
        print('Enter your actual Featherless API key here. It will not appear while you type or paste.')
        print('A blank entry keeps an existing key, or leaves inference unconfigured.')
        key = getpass.getpass('Featherless key: ')
        if key:
            if '\n' in key or '\r' in key:
                raise RuntimeError('The key contains a newline; enter it on one line.')
            values['FEATHERLESS_API_KEY'] = key.strip()
    if not values.get('FEATHERLESS_MODEL') or force:
        default = values.get('FEATHERLESS_MODEL') or defaults.get('model', '')
        model = input(f'Featherless model ID [{default}]: ').strip()
        if model or default:
            values['FEATHERLESS_MODEL'] = model or default
    values['EZRA_DATA_DIR'] = str((state / 'data').resolve())
    values.setdefault('FEATHERLESS_BASE_URL', defaults.get('base_url', 'https://api.featherless.ai/v1'))
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    for name, value in values.items():
        if value is not None:
            set_key(str(path), name, str(value), quote_mode='always')
    print('Local settings saved privately. No key was sent back to the development workspace.')


def setup(root, state):
    python = root / '.venv' / 'bin' / 'python'
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(root / '.venv')], check=True)
    requirements = root / 'requirements.txt'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = root / '.venv' / '.ezra-requirements-sha256'
    if not marker.exists() or marker.read_text() != digest:
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], check=True)
        marker.write_text(digest)
    seed_data(root, state)
    # Re-enter using the venv where dotenv and application dependencies are installed.
    subprocess.run([str(python), str(root / 'mac' / 'launcher.py'), 'configure-if-needed', '--state-dir', str(state)], check=True)
    print('\nSetup finished. Double-click Start.command to open Ezra.')
    print('OCR is optional. Existing extracted archive text works without installing Tesseract.')


def local_environment(state):
    from dotenv import dotenv_values
    environment = dict(os.environ)
    environment.update({k: v for k, v in dotenv_values(state / '.env').items() if v is not None})
    environment['EZRA_DATA_DIR'] = str((state / 'data').resolve())
    return environment


def status(environment):
    headers = {}
    if environment.get('EZRA_ACCESS_TOKEN'):
        headers['Authorization'] = 'Bearer ' + environment['EZRA_ACCESS_TOKEN']
    with urlopen(Request('http://127.0.0.1:8000/api/status', headers=headers), timeout=1) as response:
        result = json.load(response)
    return result if result.get('provider') == 'Featherless' and 'persona_status' in result else None


def start(root, state):
    if not (state / '.env').exists():
        raise RuntimeError('Run Setup.command first to create your private local settings.')
    environment = local_environment(state)
    try:
        existing = status(environment)
    except Exception:
        existing = None
    if existing:
        print('Ezra is already running. Opening the browser.')
        webbrowser.open('http://127.0.0.1:8000')
        return
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 8000))
        except OSError:
            raise RuntimeError('Port 8000 is already occupied. No process was stopped; ask for help.') from None
    argv = [str(root / '.venv' / 'bin' / 'python'), '-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', '8000']
    with (state / 'server.log').open('a') as log:
        process = subprocess.Popen(argv, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (state / 'server.json').write_text(json.dumps({'pid': process.pid, 'argv': argv, 'root': str(root)}))
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError(f'The app stopped during startup. The local log is at {state / "server.log"}.')
        try:
            if status(environment):
                print('Ezra is running locally. Double-click Stop.command when you want to stop it.')
                webbrowser.open('http://127.0.0.1:8000')
                return
        except Exception:
            pass
        time.sleep(.25)
    raise RuntimeError('The app has not confirmed readiness yet. Check the local server.log before starting another copy.')


def stop(state):
    path = state / 'server.json'
    if not path.exists():
        print('No locally started server was recorded.')
        return
    saved = json.loads(path.read_text())
    result = subprocess.run(['ps', '-p', str(saved['pid']), '-o', 'command='], capture_output=True, text=True)
    if result.returncode:
        print('The recorded server is already stopped.')
        return
    if result.stdout.strip() != ' '.join(saved['argv']):
        raise RuntimeError('The process identity changed. Nothing was stopped.')
    os.kill(saved['pid'], signal.SIGTERM)
    print('Requested a clean shutdown. An active archive extraction may finish first.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'configure', 'configure-if-needed', 'start', 'stop'])
    parser.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    state = args.state_dir.expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    try:
        if args.action == 'setup': setup(ROOT, state)
        elif args.action in ('configure', 'configure-if-needed'): configure(ROOT, state, args.action == 'configure')
        elif args.action == 'start': start(ROOT, state)
        else: stop(state)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'\nSetup/start stopped: {exc if not isinstance(exc, KeyboardInterrupt) else "canceled"}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
