"""Render entrypoint: refuse ephemeral-only persistence or missing access control."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import Settings


def arguments(environment):
    if environment.get('RENDER') != 'true':
        raise ValueError('This entrypoint expects Render TLS/proxy ingress. Use the local launcher elsewhere.')
    if not all(environment.get(name) for name in ('EZRA_DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY')):
        raise ValueError('Render startup requires Supabase database and private storage configuration. Ephemeral-only startup is refused.')
    if len(environment.get('EZRA_ACCESS_TOKEN', '')) < 24:
        raise ValueError('Set a separate EZRA_ACCESS_TOKEN application password of at least 24 characters.')
    port = int(environment.get('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid service port.')
    return [sys.executable, '-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '0.0.0.0', '--port', str(port), '--proxy-headers', '--forwarded-allow-ips=*']


def main():
    try:
        argv = arguments(os.environ)
        Settings.from_env()  # Validate without printing credentials.
        os.execv(sys.executable, argv)
    except (ValueError, OSError):
        print('Cloud startup configuration is incomplete or invalid. Check the private Render environment fields listed in docs/RENDER_SUPABASE.md.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
