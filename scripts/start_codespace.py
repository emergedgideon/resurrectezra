"""Start a single authenticated, private-port Codespaces test application."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def configuration(environment, root=ROOT):
    if environment.get('CODESPACES') != 'true':
        raise ValueError('This launcher is for GitHub Codespaces. See docs/RUNNING.md for local startup.')
    if len(environment.get('EZRA_ACCESS_TOKEN', '')) < 24:
        raise ValueError('Add an EZRA_ACCESS_TOKEN Codespaces secret of at least 24 characters, then restart the codespace. This is your application password, not your Featherless key.')
    result = dict(environment)
    result['EZRA_DATA_DIR'] = str((root / 'data').resolve())
    return result


def probe(environment):
    request = Request('http://127.0.0.1:8000/api/status', headers={'Authorization': 'Bearer ' + environment['EZRA_ACCESS_TOKEN']})
    with urlopen(request, timeout=1) as response:
        status = json.load(response)
    return status.get('provider') == 'Featherless' and 'persona_status' in status


def browser_url(environment):
    name = environment.get('CODESPACE_NAME', '')
    domain = environment.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'app.github.dev')
    if not re.fullmatch(r'[a-zA-Z0-9-]+', name) or not re.fullmatch(r'[a-zA-Z0-9.-]+', domain):
        return None
    return f'https://{name}-8000.{domain}'


def main():
    try:
        environment = configuration(os.environ)
        data = Path(environment['EZRA_DATA_DIR']); data.mkdir(parents=True, exist_ok=True)
        try:
            ready = probe(environment)
        except Exception:
            ready = False
        if not ready:
            with socket.socket() as check:
                try:
                    check.bind(('127.0.0.1', 8000))
                except OSError:
                    raise RuntimeError('Port 8000 is occupied or the app password changed. Stop/restart this codespace; no process was killed.') from None
            with (data / 'codespaces-server.log').open('a') as log:
                process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '0.0.0.0', '--port', '8000', '--proxy-headers', '--forwarded-allow-ips=127.0.0.1,::1'],
                                           cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(60):
                if process.poll() is not None:
                    raise RuntimeError('The server stopped. See data/codespaces-server.log; do not share credentials.')
                try:
                    if probe(environment):
                        ready = True
                        break
                except Exception:
                    pass
                time.sleep(.25)
        if not ready:
            raise RuntimeError('Startup has not confirmed readiness. Inspect the server log before starting another instance.')
        print('Ezra is ready. Keep port 8000 PRIVATE in the Ports tab.')
        if browser_url(environment):
            print(browser_url(environment))
        print('Enter your EZRA_ACCESS_TOKEN using Connection in the app. Never enter the Featherless key there.')
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
