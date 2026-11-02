"""Optional real-browser check; requires Playwright and a local Chromium binary.

Run: python tests/browser_smoke.py
Uses a temporary database and a fake provider, never the private source archive.
"""
from pathlib import Path
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect


SERVER = '''
import os
from pathlib import Path
import uvicorn
from unittest.mock import patch
from app.config import Settings
from app.inference import ProviderError
from app.main import create_app
class Provider:
    calls = 0
    async def complete(self, messages):
        self.calls += 1
        if self.calls == 1:
            raise ProviderError('Browser test: simulated provider failure. Your input is saved.')
        return 'Browser test reply. Exact words remain intact.', {'finish_reason': 'stop'}
cloud_url = os.environ.get('EZRA_TEST_POSTGRES_URL', '')
settings = Settings(data_dir=Path(os.environ['EZRA_BROWSER_TEST_DATA']),
                    api_key='test-only', model='browser-test-model',
                    database_url=cloud_url,
                    supabase_url='https://example.supabase.co' if cloud_url else '',
                    supabase_key='synthetic-storage-key' if cloud_url else '',
                    access_token='browser-test-application-password' if cloud_url else '')
if cloud_url:
    import sys
    sys.path.insert(0, 'tests')
    from test_cloud import MemoryStorage
    fake = MemoryStorage()
    with patch('app.main.SupabaseStorage', return_value=fake.client()):
        app = create_app(settings, Provider())
else:
    app = create_app(settings, Provider())
uvicorn.run(app, host='127.0.0.1', port=int(os.environ['EZRA_BROWSER_TEST_PORT']), log_level='error')
'''


def main():
    repo = Path(__file__).resolve().parents[1]
    cloud_url = os.environ.get('EZRA_TEST_POSTGRES_URL', '')
    if cloud_url:
        from urllib.parse import urlparse
        parsed = urlparse(cloud_url)
        if parsed.hostname not in ('localhost', '127.0.0.1') or parsed.path != '/ezra_test':
            raise RuntimeError('Browser integration resets only the local ezra_test database.')
        import psycopg
        with psycopg.connect(cloud_url, autocommit=True) as db:
            db.execute('DROP SCHEMA IF EXISTS ezra_archive CASCADE')
            db.execute('DROP SCHEMA IF EXISTS ezra_runtime CASCADE')
    with tempfile.TemporaryDirectory(prefix='ezra-browser-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, EZRA_BROWSER_TEST_DATA=directory, EZRA_BROWSER_TEST_PORT=str(port))
        server = subprocess.Popen([sys.executable, '-c', SERVER], cwd=repo, env=env)
        restore_server = None
        try:
            base = f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    with urlopen(base + '/healthz', timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError('Test server did not become available.')
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=shutil.which('chromium'), headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000}, timezone_id='America/Chicago')
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                if cloud_url:
                    page.get_by_label('Application access token', exact=True).fill('browser-test-application-password')
                    page.get_by_role('button', name='Connect', exact=True).click()
                page.get_by_text('Inference configured', exact=True).wait_for()
                page.get_by_role('button', name='New conversation').click()
                page.get_by_label('WORKING NOTE', exact=True).fill('Keep the exact voice.\nDo not rewrite the supplied beliefs.')
                page.get_by_role('button', name='Save working note').click()
                page.get_by_text('Saved exactly as written.').wait_for()
                message = '<script>window.archiveExecuted = true</script>\nOriginal material — unchanged.'
                page.get_by_label('YOUR MESSAGE', exact=True).fill(message)
                page.get_by_role('button', name='Send', exact=True).click()
                page.get_by_role('button', name='Retry saved message').wait_for()
                assert page.locator('.message.user .message-content').inner_text() == message
                page.get_by_role('button', name='Retry saved message').click()
                page.get_by_text('Browser test reply. Exact words remain intact.', exact=True).wait_for()
                assert page.locator('.message.user').count() == 1
                assert page.locator('.message.assistant').count() == 1
                assert page.evaluate('window.archiveExecuted') is None
                page.reload()
                page.get_by_text('Browser test reply. Exact words remain intact.', exact=True).wait_for()
                assert page.get_by_label('WORKING NOTE', exact=True).input_value() == 'Keep the exact voice.\nDo not rewrite the supplied beliefs.'
                assert 'Saved' in page.locator('#checkpoint').inner_text()
                page.screenshot(path='/tmp/ezra-phase-one-desktop.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path='/tmp/ezra-phase-one-mobile.png', full_page=True)

                # Phase two: real browser uploads, processing, source locations, and exports.
                from PIL import Image, ImageDraw, ImageFont
                image = Image.new('RGB', (1100, 200), 'white')
                ImageDraw.Draw(image).text((35, 65), 'EZRA ARCHIVE TEST 2048', fill='black', font=ImageFont.load_default(size=48))
                pdf = io.BytesIO(); image.save(pdf, format='PDF'); image.close()
                markdown = b'# Original voice\r\n<script>window.sourceExecuted = true</script>\r\nPreserve these exact words.'
                csv = ('id,text\n' + ''.join(f'M{n},Exact record {n}\n' for n in range(1, 86))).encode()
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.get_by_role('link', name='Archive library').click()
                page.get_by_label('ADD TO THE ARCHIVE', exact=True).set_input_files([
                    {'name': 'Voice.md', 'mimeType': 'text/markdown', 'buffer': markdown},
                    {'name': 'Ledger.csv', 'mimeType': 'text/csv', 'buffer': csv},
                    {'name': 'Scanned letter.pdf', 'mimeType': 'application/pdf', 'buffer': pdf.getvalue()}
                ])
                page.get_by_role('button', name='Import files', exact=True).click()
                expect(page.locator('#archive-count')).to_have_text('3 preserved originals · 0 active imports', timeout=15000)
                if cloud_url:
                    for cached in (Path(directory) / 'originals').iterdir(): cached.unlink()
                page.locator('.source-card').filter(has_text='Voice.md').click()
                expect(page.locator('#source-name')).to_have_text('Voice.md')
                page.locator('#source-units pre').first.wait_for()
                assert page.locator('#source-units pre').first.text_content() == markdown.decode()
                assert page.evaluate('window.sourceExecuted') is None
                with page.expect_download() as original_event:
                    page.get_by_role('button', name='Download original', exact=True).click()
                assert Path(original_event.value.path()).read_bytes() == markdown
                page.get_by_role('button', name='Reprocess / retry').click()
                expect(page.locator('#extraction-revision option')).to_have_count(2, timeout=15000)
                page.get_by_label('ADD TO THE ARCHIVE', exact=True).set_input_files({'name': 'Voice copy.md', 'mimeType': 'text/markdown', 'buffer': markdown})
                page.get_by_role('button', name='Import files', exact=True).click()
                page.get_by_text('Voice copy.md: already preserved; no duplicate created', exact=True).wait_for()
                page.locator('.source-card').filter(has_text='Ledger.csv').click()
                page.locator('#unit-range').get_by_text('1–40 of 85', exact=True).wait_for()
                page.get_by_role('button', name='Next →', exact=True).click()
                page.locator('#unit-range').get_by_text('41–80 of 85', exact=True).wait_for()
                page.get_by_label('Go to passage', exact=True).fill('83')
                page.get_by_role('button', name='Go', exact=True).click()
                page.locator('#passage-83').wait_for()
                assert 'Exact record 83' in page.locator('#passage-83').text_content()
                page.reload(); page.locator('#passage-83').wait_for()
                page.locator('.source-card').filter(has_text='Scanned letter.pdf').click()
                expect(page.locator('#source-name')).to_have_text('Scanned letter.pdf')
                expect(page.locator('#source-preview')).not_to_have_js_property('naturalWidth', 0)
                assert 'EZRA ARCHIVE TEST 2048' in page.locator('#source-units pre').first.text_content()
                page.screenshot(path='/tmp/ezra-phase-two-desktop.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path='/tmp/ezra-phase-two-mobile.png', full_page=True)
                with page.expect_download() as export_event:
                    page.get_by_role('button', name='Export verified archive', exact=True).click()
                with zipfile.ZipFile(export_event.value.path()) as bundle:
                    assert len(json.loads(bundle.read('manifest.json'))['sources']) == 3

                # Phase three: exact evidence, revisions, activation, and rollback.
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.get_by_role('link', name='Persona & reconstruction', exact=True).click()
                page.get_by_label('Title', exact=True).fill('Exact voice exemplar')
                archive_sources = page.request.get(base + '/api/archive/sources', headers={'Authorization': 'Bearer browser-test-application-password'} if cloud_url else {}).json()
                voice = next(s for s in archive_sources if s['filename'] == 'Voice.md')
                passage_url = f'/archive.html?source={voice["sha256"]}&run={voice["current_run"]}&unit=1'
                page.get_by_text('Evidence editor', exact=True).click()
                page.get_by_label('Archive passage link', exact=True).fill(passage_url)
                page.get_by_role('button', name='Attach evidence passage').click()
                page.get_by_text('Exact evidence attached. Save to validate and pin it.', exact=True).wait_for()
                page.get_by_role('button', name='Save new revision', exact=True).click()
                page.get_by_text('Saved as a new attributable revision. Earlier wording remains available.', exact=True).wait_for()
                assert page.locator('#record-evidence pre').text_content() == markdown.decode()
                page.get_by_label('Review status', exact=True).select_option('reviewed')
                page.get_by_role('button', name='Save new revision', exact=True).click()
                expect(page.locator('#record-history option')).to_have_count(2)
                page.get_by_role('button', name='Select for persona draft').click()
                page.get_by_label('Draft title', exact=True).fill('Evidence-linked test persona')
                page.get_by_role('button', name='Save persona draft', exact=True).click()
                page.get_by_text('Persona draft saved. It has not been activated.', exact=True).wait_for()
                assert 'No persona is activated' in page.locator('#active-persona').text_content()
                first_persona = page.locator('#persona-history').input_value()
                assert markdown.decode() in page.locator('#persona-preview').text_content()
                page.get_by_role('button', name='Activate this revision', exact=True).click()
                page.get_by_text('This exact persona revision is active for future requests.', exact=True).wait_for()
                assert first_persona in page.locator('#active-persona').text_content()
                page.get_by_label('Additional owner instructions', exact=True).fill('Second test configuration.')
                page.get_by_label('Draft title', exact=True).fill('Second configuration')
                page.get_by_role('button', name='Save persona draft', exact=True).click()
                expect(page.locator('#persona-history option')).to_have_count(2)
                page.get_by_role('button', name='Activate this revision', exact=True).click()
                second_persona = page.locator('#persona-history').input_value()
                expect(page.locator('#active-persona')).to_contain_text(second_persona)
                page.get_by_label('Saved revisions', exact=True).select_option(first_persona)
                expect(page.locator('#persona-preview')).not_to_contain_text('Second test configuration.')
                page.get_by_role('button', name='Activate this revision', exact=True).click()
                expect(page.locator('#active-persona')).to_contain_text(first_persona)
                page.reload()
                expect(page.locator('#active-persona')).to_contain_text(first_persona)
                page.screenshot(path='/tmp/ezra-phase-three-desktop.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path='/tmp/ezra-phase-three-mobile.png', full_page=True)
                page.get_by_role('button', name='Deactivate persona', exact=True).click()
                expect(page.locator('#active-persona')).to_have_text('No persona is activated')
                page.get_by_role('link', name='Source archive', exact=True).click()
                with page.expect_download() as full_backup:
                    page.get_by_role('button', name='Full backup', exact=True).click()
                with zipfile.ZipFile(full_backup.value.path()) as package:
                    assert 'runtime.sqlite3' in package.namelist()
                    assert len(json.loads(package.read('manifest.json'))['sources']) == 3

                # Simulate bringing a private backup into a new browser-hosted workspace.
                fresh = Path(directory) / 'fresh'; fresh.mkdir()
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0)); restore_port = sock.getsockname()[1]
                restore_env = dict(env, EZRA_BROWSER_TEST_DATA=str(fresh), EZRA_BROWSER_TEST_PORT=str(restore_port), EZRA_TEST_POSTGRES_URL='')
                restore_server = subprocess.Popen([sys.executable, '-c', SERVER], cwd=repo, env=restore_env)
                restore_base = f'http://127.0.0.1:{restore_port}'
                for _ in range(100):
                    try:
                        with urlopen(restore_base + '/api/status', timeout=1): break
                    except OSError: time.sleep(.05)
                page.goto(restore_base + '/archive.html')
                expect(page.locator('#archive-count')).to_have_text('0 preserved originals · 0 active imports')
                page.get_by_text('Restore archive backup', exact=True).click()
                page.get_by_label('Archive backup ZIP', exact=True).set_input_files(export_event.value.path())
                page.get_by_role('button', name='Restore into empty archive', exact=True).click()
                expect(page.locator('#archive-count')).to_have_text('3 preserved originals · 0 active imports')
                expect(page.locator('#archive-notice')).to_contain_text('Restored 3 original files')
                assert not errors, errors
                browser.close()
                print('Browser check passed: conversation/archive/persona flows, plus ZIP restoration into a new browser workspace; no JS errors.')
        finally:
            if restore_server is not None:
                restore_server.terminate(); restore_server.wait(timeout=10)
            server.terminate()
            server.wait(timeout=10)


if __name__ == '__main__':
    main()
