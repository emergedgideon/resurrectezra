"""Render entrypoint: refuse ephemeral-only persistence or missing access control."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import Settings, ConfigurationError


def arguments(environment):
    if environment.get('RENDER') != 'true':
        raise ConfigurationError('RENDER must be true for this entrypoint. Use the local launcher outside Render.')
    missing = [name for name in ('EZRA_DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY') if not environment.get(name, '').strip()]
    if missing:
        raise ConfigurationError('Missing Render environment fields: ' + ', '.join(missing) + '. Add values in the service Environment tab.')
    if len(environment.get('EZRA_ACCESS_TOKEN', '')) < 24:
        raise ConfigurationError('EZRA_ACCESS_TOKEN must be a separate application password of at least 24 characters. Update it in Render Environment; do not regenerate API keys.')
    try:
        port = int(environment.get('PORT', '8000'))
    except ValueError:
        raise ConfigurationError('PORT must be a number; remove a custom PORT override to use the platform default.') from None
    if not 1 <= port <= 65535:
        raise ConfigurationError('PORT must be between 1 and 65535.')
    return [sys.executable, '-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '0.0.0.0', '--port', str(port), '--proxy-headers', '--forwarded-allow-ips=*']


def main():
    try:
        argv = arguments(os.environ)
        Settings.from_env()  # Validate without printing credentials.
        os.execv(sys.executable, argv)
    except ConfigurationError as exc:
        print('Cloud startup configuration error: ' + str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print('Cloud startup could not complete. Check EZRA_DATA_DIR and private Render environment fields; supplied values are hidden.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
