import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.inference import Featherless, ProviderError, assemble_context
from app.main import create_app
from app.store import Conflict, Store


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def complete(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise ProviderError('Test provider unavailable.')
        return 'A saved reply — unchanged.', {'total_tokens': 20, 'finish_reason': 'stop'}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.directory.name), model='test-model', api_key='private-provider-key')
        self.provider = FakeProvider()
        self.app = create_app(self.settings, self.provider)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.conversation = self.client.post('/api/conversations', json={'title': 'Continuity test'}).json()
        self.path = '/api/conversations/' + self.conversation['id']

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.directory.cleanup()

    def send(self, content='Unchanged text: <script> & “quotes”\nSecond line.', request_id=None):
        return self.client.post(self.path + '/turns', json={'request_id': request_id or str(uuid4()), 'content': content})

    def test_messages_checkpoint_and_note_survive_new_store(self):
        note = 'Preserve these words exactly.\nNo substituted beliefs.'
        self.assertEqual(self.client.put(self.path + '/continuity', json={'content': note}).status_code, 200)
        response = self.send()
        self.assertEqual(response.status_code, 200)
        value = response.json()
        self.assertEqual(value['messages'][0]['content'], 'Unchanged text: <script> & “quotes”\nSecond line.')
        self.assertEqual(value['turns'][0]['status'], 'completed')
        self.assertIn(note, self.provider.calls[0][0]['content'])
        reopened = Store(self.settings.data_dir).detail(self.conversation['id'])
        self.assertEqual(reopened['messages'], value['messages'])
        self.assertEqual(reopened['continuity_note'], note)
        self.assertEqual(reopened['checkpoint']['last_completed_turn_id'], value['turns'][0]['id'])

    def test_idempotency_and_changed_request_rejected(self):
        request_id = str(uuid4())
        first = self.send(request_id=request_id).json()
        second = self.send(request_id=request_id).json()
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(first['messages'], second['messages'])
        self.assertEqual(self.send('different', request_id).status_code, 409)

    def test_failed_turn_is_saved_and_explicit_retry_does_not_duplicate(self):
        self.provider.fail = True
        value = self.send('Keep this unaltered.').json()
        self.assertEqual(value['turns'][0]['status'], 'failed')
        self.assertEqual(len(value['messages']), 1)
        self.assertEqual(self.send('next').status_code, 409)
        self.provider.fail = False
        retried = self.client.post(self.path + '/turns/' + value['turns'][0]['id'] + '/retry').json()
        self.assertEqual(len(retried['messages']), 2)
        self.assertEqual(retried['turns'][0]['attempt'], 2)
        self.assertEqual(retried['turns'][0]['status'], 'completed')
        self.assertEqual(self.client.post(self.path + '/turns/' + value['turns'][0]['id'] + '/retry').status_code, 409)

    def test_single_owner_lock_prevents_second_server_recovery(self):
        other = create_app(self.settings, FakeProvider())
        with self.assertRaisesRegex(RuntimeError, 'already open'):
            with TestClient(other):
                pass

    def test_context_keeps_complete_pairs_and_records_omissions(self):
        for n in range(4):
            self.send(str(n) + 'a' * 500)
        store = self.app.state.store
        turn, _ = store.claim(self.conversation['id'], str(uuid4()), 'latest')
        value = store.detail(self.conversation['id'])
        context, metadata = assemble_context(value, turn['id'], 1800)
        self.assertEqual(context[-1]['content'], 'latest')
        self.assertGreater(metadata['previous_turns_omitted'], 0)
        self.assertLessEqual(metadata['character_count'], 1800)
        roles = [m['role'] for m in context[1:-1]]
        self.assertEqual(roles, ['user', 'assistant'] * (len(roles) // 2))
        store.fail(turn, 'test cleanup')

    def test_oversized_input_is_preserved_and_not_sent(self):
        response = self.send('字' * 30000).json()
        self.assertEqual(response['messages'][0]['content'], '字' * 30000)
        self.assertEqual(response['turns'][0]['status'], 'failed')
        self.assertIn('budget', response['turns'][0]['error'])
        self.assertEqual(self.provider.calls, [])

    def test_static_assets_status_and_no_provider_secret(self):
        index = self.client.get('/')
        self.assertEqual(index.status_code, 200)
        self.assertIn('A place to begin.', index.text)
        self.assertEqual(self.client.get('/app.js').status_code, 200)
        self.assertEqual(self.client.get('/style.css').status_code, 200)
        status = self.client.get('/api/status')
        self.assertNotIn('private-provider-key', status.text + index.text)
        self.assertFalse(status.json()['tools_connected'])
        self.assertIn("script-src 'self'", index.headers['content-security-policy'])

    def test_running_turn_blocks_note_edits(self):
        turn, _ = self.app.state.store.claim(self.conversation['id'], str(uuid4()), 'In progress')
        response = self.client.put(self.path + '/continuity', json={'content': 'racing note'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.app.state.store.detail(self.conversation['id'])['continuity_note'], '')
        self.app.state.store.fail(turn, 'test cleanup')

    def test_blank_and_missing_input(self):
        self.assertEqual(self.send('   ').status_code, 422)
        self.assertEqual(self.client.get('/api/conversations/' + str(uuid4())).status_code, 404)


class RecoveryTests(unittest.TestCase):
    def test_missing_live_config_preserves_message_and_reports_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Settings(data_dir=Path(directory)))) as client:
                self.assertFalse(client.get('/api/status').json()['inference_configured'])
                conversation = client.post('/api/conversations', json={'title': 'Unconfigured'}).json()
                value = client.post('/api/conversations/' + conversation['id'] + '/turns',
                                    json={'request_id': str(uuid4()), 'content': 'Keep this.'}).json()
                self.assertEqual(value['messages'][0]['content'], 'Keep this.')
                self.assertEqual(value['turns'][0]['status'], 'failed')
                self.assertIn('FEATHERLESS_MODEL', value['turns'][0]['error'])

    def test_restart_marks_interrupted_without_resending(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            conversation = store.create_conversation('Interrupted')
            turn, _ = store.claim(conversation['id'], str(uuid4()), 'Still here.')
            provider = FakeProvider()
            with TestClient(create_app(Settings(data_dir=Path(directory)), provider)) as client:
                value = client.get('/api/conversations/' + conversation['id']).json()
                self.assertEqual(value['turns'][0]['status'], 'interrupted')
                self.assertEqual(value['messages'][0]['content'], 'Still here.')
                self.assertEqual(provider.calls, [])
                reply = client.post('/api/conversations/' + conversation['id'] + '/turns/' + turn['id'] + '/retry').json()
                self.assertEqual(reply['turns'][0]['status'], 'completed')

    def test_concurrent_claims_allow_one_running_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            identifier = store.create_conversation('Concurrent')['id']
            def claim(number):
                try:
                    store.claim(identifier, str(uuid4()), str(number))
                    return 'claimed'
                except Conflict:
                    return 'conflict'
            with ThreadPoolExecutor(max_workers=2) as pool:
                result = list(pool.map(claim, [1, 2]))
            self.assertCountEqual(result, ['claimed', 'conflict'])

    def test_access_token_and_origin_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory), access_token='app-secret')
            with TestClient(create_app(settings, FakeProvider())) as client:
                self.assertEqual(client.get('/api/status').status_code, 401)
                headers = {'Authorization': 'Bearer app-secret'}
                self.assertEqual(client.get('/api/status', headers=headers).status_code, 200)
                self.assertNotIn('app-secret', client.get('/api/status', headers=headers).text)
                headers['Origin'] = 'https://another.example'
                self.assertEqual(client.get('/api/status', headers=headers).status_code, 403)

    def test_remote_access_without_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Settings(data_dir=Path(directory))), base_url='https://public.example') as client:
                self.assertEqual(client.get('/api/status').status_code, 403)


class ProviderTests(unittest.TestCase):
    def call(self, handler):
        real_client = httpx.AsyncClient
        settings = Settings(api_key='do-not-expose', model='chosen/model')
        with patch('app.inference.httpx.AsyncClient', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)):
            return asyncio.run(Featherless(settings).complete([{'role': 'user', 'content': 'exact wording'}]))

    def test_adapter_request_and_exact_output(self):
        def handler(request):
            self.assertEqual(str(request.url), 'https://api.featherless.ai/v1/chat/completions')
            self.assertEqual(request.headers['authorization'], 'Bearer do-not-expose')
            payload = json.loads(request.content)
            self.assertEqual(payload['model'], 'chosen/model')
            self.assertEqual(payload['messages'][0]['content'], 'exact wording')
            return httpx.Response(200, json={'choices': [{'message': {'content': '  Exact\noutput.  '}, 'finish_reason': 'stop'}]})
        self.assertEqual(self.call(handler)[0], '  Exact\noutput.  ')

    def test_http_errors_do_not_echo_secret_or_raw_provider_body(self):
        with self.assertRaises(ProviderError) as caught:
            self.call(lambda request: httpx.Response(401, text='do-not-expose raw private content'))
        self.assertNotIn('do-not-expose', str(caught.exception))
        self.assertNotIn('raw private content', str(caught.exception))

    def test_malformed_reply_and_missing_configuration(self):
        with self.assertRaises(ProviderError):
            self.call(lambda request: httpx.Response(200, json={'choices': []}))
        with self.assertRaisesRegex(ProviderError, 'Configure'):
            asyncio.run(Featherless(Settings()).complete([]))

    def test_timeout_is_an_explicit_error(self):
        def handler(request):
            raise httpx.ReadTimeout('sensitive transport detail', request=request)
        with self.assertRaisesRegex(ProviderError, 'timed out') as caught:
            self.call(handler)
        self.assertNotIn('sensitive transport detail', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
