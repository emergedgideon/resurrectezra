import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient

from app.archive import Archive
from app.config import Settings
from app.inference import ProviderError, assemble_context
from app.main import create_app
from app.reconstruction import Reconstruction
from app.store import Conflict
from scripts.verify_archive_backup import verify


def csv_bytes(rows):
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    return buffer.getvalue().encode()


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.archive = Archive(self.root)
        self.recon = Reconstruction(self.archive)
        self.text = 'Exact belief — 🔥 keep these words.\n<script>inert</script>'
        source = self.archive.stage('voice.md', io.BytesIO(self.text.encode()))
        self.archive.process_one()
        self.sha = source['sha256']
        self.run = self.archive.source(self.sha)['current_run']
        self.citation = {'sha256': self.sha, 'run_id': self.run, 'ordinal': 1, 'quote': self.text}
        self.body = {'title': 'Source belief', 'kind': 'belief', 'origin': 'source_statement', 'text': self.text,
                     'citations': [self.citation], 'dates': {'precision': 'unknown'}, 'tags': ['exact'], 'notes': 'Keep uncertainty.'}

    def tearDown(self):
        self.directory.cleanup()

    def test_exact_evidence_unicode_offsets_and_rejection_of_mismatches(self):
        entry = self.recon.create_record(self.body)
        evidence = entry['current']['body']['citations'][0]
        self.assertEqual(evidence['quote'], self.text)
        self.assertIn('run=' + self.run, evidence['href'])
        start = self.text.index('🔥')
        sub = self.recon.evidence({**self.citation, 'start': start, 'end': start + 1, 'quote': '🔥'})
        self.assertEqual(sub['quote'], '🔥')
        with self.assertRaises(ValueError): self.recon.evidence({**self.citation, 'quote': 'altered'})
        with self.assertRaises(ValueError): self.recon.evidence({**self.citation, 'sha256': 'wrong'})
        with self.assertRaises(ValueError): self.recon.evidence({**self.citation, 'end': len(self.text) + 1})
        with self.assertRaises(ValueError): self.recon.evidence('not an object')
        with self.assertRaises(ValueError): self.recon.create_record({**self.body, 'text': 'softened version'})

    def test_immutable_revisions_optimistic_conflict_and_pinned_evidence(self):
        entry = self.recon.create_record(self.body)
        first = entry['current']['id']
        revised = self.recon.revise(entry['id'], {**self.body, 'origin': 'interpretation', 'text': 'Explicitly labeled interpretation.'}, 1)
        self.assertEqual(len(revised['revisions']), 2)
        self.assertEqual(revised['revisions'][1]['body']['text'], self.text)
        self.assertEqual(revised['revisions'][1]['id'], first)
        with self.assertRaises(Conflict): self.recon.revise(entry['id'], self.body, 1)
        self.archive.reprocess(self.sha); self.archive.process_one()
        self.assertEqual(self.recon.evidence(revised['revisions'][1]['body']['citations'][0])['run_id'], self.run)

    def test_owner_additions_interpretations_and_contradictions_stay_distinct(self):
        first = self.recon.create_record(self.body)
        second = self.recon.create_record({'title': 'Other account', 'text': 'A conflicting claim.', 'kind': 'belief', 'origin': 'owner_statement'})
        relation = self.recon.relate(first['id'], second['id'], 'contradicts', 'Both accounts retained; unresolved.')
        self.assertEqual(relation['kind'], 'contradicts')
        self.assertEqual(len(self.recon.record(second['id'])['relations']), 1)
        self.assertEqual(self.recon.record(first['id'])['current']['body']['text'], self.text)
        with self.assertRaises(ValueError): self.recon.create_record({'title': 'Unsupported inference', 'kind': 'belief', 'origin': 'interpretation', 'text': 'No evidence.'})

    def test_persona_drafts_activation_rollback_deactivation_and_restart(self):
        entry = self.recon.create_record(self.body)
        first = self.recon.create_persona('First draft', [entry['current']['id']])
        self.assertIsNone(self.recon.active())
        self.assertIn(self.text, first['compiled_text'])
        self.recon.activate(first['id'], 24000)
        second = self.recon.create_persona('Second draft', [], 'Owner instruction — exactly.', parent=first['id'])
        self.recon.activate(second['id'], 24000)
        self.assertEqual(Reconstruction(Archive(self.root)).active()['id'], second['id'])
        self.recon.activate(first['id'], 24000)
        self.assertEqual(self.recon.active()['compiled_text'], first['compiled_text'])
        self.recon.deactivate()
        self.assertIsNone(self.recon.active())
        self.assertEqual(len(self.recon.personas()['events']), 4)

    def test_later_record_edits_do_not_change_persona_snapshots(self):
        entry = self.recon.create_record(self.body)
        draft = self.recon.create_persona('Pinned', [entry['current']['id']])
        self.recon.revise(entry['id'], {**self.body, 'origin': 'owner_statement', 'text': 'New owner wording.'}, 1)
        self.assertEqual(self.recon.persona(draft['id'])['compiled_text'], draft['compiled_text'])
        oversized = self.recon.create_persona('Too large', [], 'x' * 22000)
        with self.assertRaises(Conflict): self.recon.activate(oversized['id'], 24000)
        self.assertIsNone(self.recon.active())

    def seed_fixtures(self):
        consolidated = [{'memory_id': 'M0001', 'title': 'Identity anchor', 'memory_text': 'An exact identity statement.',
                         'category': 'identity', 'event_date_start': '2025-07', 'event_date_end': '', 'tags': 'identity|voice',
                         'temporal_status': 'historical', 'source_titles': 'Original.pdf', 'contradiction_or_usage_notes': 'Conflicts with another account.'}]
        ledger = [{'source_record_id': 'MEMARA-001', 'content': 'The exact source event happened.', 'record_date': '2025-08-22', 'tags': 'event', 'notes': 'Raw archive.', 'included_in_consolidated': 'no'}]
        for name, raw in [('ezra_memories_consolidated.csv', csv_bytes(consolidated)), ('memara_100_source_ledger.csv', csv_bytes(ledger))]:
            self.archive.stage(name, io.BytesIO(raw)); self.archive.process_one()

    def test_bootstrap_is_idempotent_preserves_dates_notes_and_does_not_activate(self):
        self.seed_fixtures()
        self.recon.bootstrap(); first = self.recon.records()
        self.recon.bootstrap(); second = self.recon.records()
        self.assertEqual(first, second)
        self.assertIsNone(self.recon.active())
        self.assertEqual(len(self.recon.personas()['revisions']), 1)
        records = first['records']; self.assertEqual(len(records), 2)
        ledger = next(r for r in records if r['title'] == 'MEMARA-001')
        self.assertEqual(ledger['dates']['record_date'], '2025-08-22')
        self.assertEqual(ledger['dates']['event_start'], '')
        self.assertIn('uncertainty', ledger['facets'])
        identity = next(r for r in records if r['title'] == 'Identity anchor')
        self.assertEqual(identity['dates']['event_start'], '2025-07')
        self.assertIn('Conflicts with another account.', identity['notes'])

    def test_reconciliation_distinguishes_matching_from_semantic_review(self):
        self.seed_fixtures()
        # Use a tiny actual text PDF, preserving a deterministic page location.
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter(); page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject(); stream.set_data(b'BT /F1 14 Tf 30 700 Td (The exact source event happened.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        buffer = io.BytesIO(); writer.write(buffer)
        self.archive.stage('08_Memara_100_Memory_Export.pdf', io.BytesIO(buffer.getvalue())); self.archive.process_one()
        first = self.recon.reconcile(); second = self.recon.reconcile()
        self.assertEqual(first['id'], second['id'])
        mapping = first['mappings'][0]
        self.assertEqual(mapping['pdf_status'], 'normalized_text_match')
        self.assertEqual(mapping['review_status'], 'unreviewed')
        self.assertIsNone(mapping['event_date'])
        self.assertEqual(mapping['inclusion_claim'], 'no')
        pdf = mapping['pdf_candidates'][0]
        citation = {**pdf, 'quote': 'The exact source event happened.'}
        # Extractors can retain a newline. Pin the exact range explicitly.
        citation.update({'start': 0, 'end': len('The exact source event happened.')})
        reviewed = self.recon.review_mapping(first['id'], 'MEMARA-001', 'verified', 'Checked actual PDF wording.', [citation])
        self.assertEqual(reviewed['mappings'][0]['review_status'], 'verified')
        self.recon.review_mapping(first['id'], 'MEMARA-001', 'unresolved', 'Review reopened.', [])
        self.assertEqual(len(self.recon.report()['reviews']), 2)
        with self.assertRaises(ValueError): self.recon.review_mapping(first['id'], 'MEMARA-001', 'verified', 'No evidence.', [])

    def test_reconstruction_personas_and_evidence_survive_archive_export_restore(self):
        entry = self.recon.create_record(self.body)
        draft = self.recon.create_persona('Pinned', [entry['current']['id']]); self.recon.activate(draft['id'], 24000)
        backup = self.archive.export(); self.assertEqual(verify(backup)['verified_sources'], 1)
        restored = self.root / 'restore'; restored.mkdir()
        with zipfile.ZipFile(backup) as bundle: bundle.extractall(restored)
        recon = Reconstruction(Archive(restored))
        self.assertEqual(recon.active()['compiled_text'], draft['compiled_text'])
        self.assertEqual(recon.record(entry['id'])['current']['body']['text'], self.text)


class PersonaAPITests(unittest.TestCase):
    def test_explicit_activation_controls_context_and_turn_metadata(self):
        calls = []
        class Provider:
            async def complete(self, messages):
                calls.append(messages)
                return 'Test reply.', {}
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(data_dir=Path(directory)), Provider())
            with TestClient(app) as client:
                revision = client.post('/api/personas', json={'title': 'Owner draft', 'instructions': 'Exact persona instruction — no replacement.'}).json()
                self.assertIsNone(client.get('/api/status').json()['persona_revision_id'])
                self.assertEqual(client.post('/api/personas/' + revision['id'] + '/activate').status_code, 200)
                conversation = client.post('/api/conversations', json={'title': 'Persona test'}).json()
                base = '/api/conversations/' + conversation['id']
                value = client.post(base + '/turns', json={'request_id': str(uuid4()), 'content': 'Test.'}).json()
                self.assertIn('Exact persona instruction — no replacement.', calls[-1][0]['content'])
                context_event = next(e for e in value['events'] if e['type'] == 'context.assembled')
                self.assertEqual(context_event['payload']['persona_revision_id'], revision['id'])
                self.assertEqual(client.post('/api/personas/deactivate').status_code, 200)
                client.post(base + '/turns', json={'request_id': str(uuid4()), 'content': 'Again.'})
                self.assertNotIn('Exact persona instruction — no replacement.', calls[-1][0]['content'])
                self.assertEqual(client.get('/reconstruction.html').status_code, 200)


if __name__ == '__main__':
    unittest.main()
