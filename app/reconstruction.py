"""Source-linked reconstruction, immutable revisions, and explicit persona activation."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata
from uuid import uuid4, uuid5, NAMESPACE_URL

from .store import Conflict, Missing


KINDS = {'identity', 'chronology', 'voice', 'belief', 'relationship', 'symbol', 'entity', 'uncertainty'}
ORIGINS = {'source_statement', 'owner_statement', 'interpretation'}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def normalized(text):
    # Matching representation only. Never used to overwrite sources or quotations.
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


class Reconstruction:
    def __init__(self, archive):
        self.archive = archive
        with archive.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS reconstruction_records (
                    id TEXT PRIMARY KEY, seed_key TEXT UNIQUE, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reconstruction_revisions (
                    id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES reconstruction_records(id),
                    revision INTEGER NOT NULL, body_json TEXT NOT NULL, author TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(record_id,revision));
                CREATE TABLE IF NOT EXISTS reconstruction_relations (
                    id TEXT PRIMARY KEY, left_id TEXT NOT NULL REFERENCES reconstruction_records(id),
                    right_id TEXT NOT NULL REFERENCES reconstruction_records(id), kind TEXT NOT NULL,
                    note TEXT NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS persona_revisions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, instructions TEXT NOT NULL,
                    record_revisions_json TEXT NOT NULL, author TEXT NOT NULL,
                    created_at TEXT NOT NULL, parent_id TEXT REFERENCES persona_revisions(id));
                CREATE TABLE IF NOT EXISTS persona_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, revision_id TEXT REFERENCES persona_revisions(id),
                    action TEXT NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reconciliation_reports (
                    id TEXT PRIMARY KEY, source_fingerprint TEXT UNIQUE NOT NULL,
                    report_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reconciliation_reviews (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT NOT NULL REFERENCES reconciliation_reports(id),
                    ledger_id TEXT NOT NULL, body_json TEXT NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')

    def evidence(self, citation):
        if not isinstance(citation, dict):
            raise ValueError('Each evidence citation must be an object.')
        sha, run, ordinal = citation.get('sha256'), citation.get('run_id'), citation.get('ordinal')
        if not isinstance(sha, str) or not isinstance(run, str) or type(ordinal) is not int or ordinal < 1:
            raise ValueError('Evidence requires a source digest, extraction revision, and positive passage ordinal.')
        with self.archive.connect() as db:
            row = db.execute('''SELECT u.*,r.sha256,s.filename FROM source_units u
                JOIN extraction_runs r ON r.id=u.run_id JOIN sources s ON s.sha256=r.sha256
                WHERE u.run_id=? AND u.ordinal=? AND r.sha256=?''', (run, ordinal, sha)).fetchone()
        if row is None:
            raise ValueError('Evidence passage does not exist for this source and extraction revision.')
        field = citation.get('field', '$content')
        if not isinstance(field, str):
            raise ValueError('Evidence field must be a string.')
        payload = json.loads(row['payload_json'])
        text = row['content'] if field == '$content' else payload.get(field)
        if not isinstance(text, str):
            raise ValueError('Evidence field must contain source text.')
        start, end = citation.get('start', 0), citation.get('end', len(text))
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > len(text):
            raise ValueError('Evidence offsets must identify a nonempty Unicode character range.')
        quote = text[start:end]
        if citation.get('quote', quote) != quote:
            raise ValueError('Evidence quotation does not match the preserved passage.')
        return {'sha256': sha, 'run_id': run, 'ordinal': ordinal, 'field': field,
                'start': start, 'end': end, 'quote': quote, 'filename': row['filename'],
                'location': json.loads(row['location_json']),
                'href': f'/archive.html?source={sha}&run={run}&unit={ordinal}'}

    def validate(self, body):
        title, text = body.get('title'), body.get('text')
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ValueError('Provide a title of 1–300 characters.')
        if not isinstance(text, str) or not text.strip() or len(text) > 100000:
            raise ValueError('Provide nonempty record text under 100,001 characters.')
        kind, origin = body.get('kind'), body.get('origin')
        if kind not in KINDS or origin not in ORIGINS:
            raise ValueError('Unknown reconstruction kind or origin.')
        citations = body.get('citations', [])
        if not isinstance(citations, list) or len(citations) > 50:
            raise ValueError('Use at most 50 evidence citations.')
        citations = [self.evidence(c) for c in citations]
        if origin != 'owner_statement' and not citations:
            raise ValueError('Source statements and interpretations require evidence.')
        if origin == 'source_statement' and text not in [c['quote'] for c in citations]:
            raise ValueError('A source statement must exactly match at least one evidence quotation. Use interpretation for derived wording.')
        facets = body.get('facets', [kind])
        tags = body.get('tags', [])
        if not isinstance(facets, list) or not all(f in KINDS for f in facets):
            raise ValueError('Invalid reconstruction facets.')
        if not isinstance(tags, list) or len(tags) > 100 or not all(isinstance(t, str) and len(t) <= 200 for t in tags):
            raise ValueError('Use up to 100 text tags, each at most 200 characters.')
        dates = body.get('dates', {})
        if not isinstance(dates, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in dates.items()):
            raise ValueError('Date claims must be string fields; do not infer a missing event date from import/record time.')
        if body.get('status', 'proposed') not in ('proposed', 'reviewed'):
            raise ValueError('Status must be proposed or reviewed.')
        notes = body.get('notes', '')
        if not isinstance(notes, str) or len(notes) > 20000:
            raise ValueError('Notes must be text under 20,001 characters.')
        return {'title': title, 'text': text, 'kind': kind, 'origin': origin,
                'facets': list(dict.fromkeys([kind] + facets)), 'tags': tags,
                'dates': dates, 'notes': notes, 'citations': citations,
                'status': body.get('status', 'proposed')}

    def create_record(self, body, author='owner', seed_key=None):
        body = self.validate(body)
        identifier = str(uuid5(NAMESPACE_URL, 'ezra:' + seed_key)) if seed_key else str(uuid4())
        with self.archive.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            exists = seed_key and db.execute('SELECT 1 FROM reconstruction_records WHERE seed_key=?', (seed_key,)).fetchone()
            if not exists:
                db.execute('INSERT INTO reconstruction_records VALUES(?,?,?)', (identifier, seed_key, stamp()))
                db.execute('INSERT INTO reconstruction_revisions VALUES(?,?,?,?,?,?)', (str(uuid4()), identifier, 1, encode(body), author, stamp()))
        return self.record(identifier)

    def record(self, identifier):
        with self.archive.connect() as db:
            revisions = db.execute('SELECT * FROM reconstruction_revisions WHERE record_id=? ORDER BY revision DESC', (identifier,)).fetchall()
            if not revisions:
                raise Missing('Reconstruction record not found.')
            versions = [{**dict(r), 'body': json.loads(r['body_json'])} for r in revisions]
            for version in versions:
                version.pop('body_json')
            relations = [dict(r) for r in db.execute('SELECT * FROM reconstruction_relations WHERE left_id=? OR right_id=? ORDER BY rowid', (identifier, identifier))]
        return {'id': identifier, 'current': versions[0], 'revisions': versions, 'relations': relations}

    def revise(self, identifier, body, expected_revision):
        body = self.validate(body)
        with self.archive.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest = db.execute('SELECT max(revision) FROM reconstruction_revisions WHERE record_id=?', (identifier,)).fetchone()[0]
            if latest is None:
                raise Missing('Reconstruction record not found.')
            if latest != expected_revision:
                raise Conflict('This record changed. Reload before saving another revision.')
            db.execute('INSERT INTO reconstruction_revisions VALUES(?,?,?,?,?,?)', (str(uuid4()), identifier, latest + 1, encode(body), 'owner', stamp()))
        return self.record(identifier)

    def records(self, kind=None, query='', offset=0, limit=50):
        with self.archive.connect() as db:
            rows = db.execute('''SELECT v.* FROM reconstruction_revisions v WHERE revision=(
                SELECT max(revision) FROM reconstruction_revisions WHERE record_id=v.record_id)
                ORDER BY v.rowid''').fetchall()
        records = []
        for row in rows:
            body = json.loads(row['body_json'])
            if kind and kind not in body['facets']:
                continue
            if query and query.casefold() not in (body['title'] + '\n' + body['text'] + '\n' + ' '.join(body['tags'])).casefold():
                continue
            records.append({'id': row['record_id'], 'revision_id': row['id'], 'revision': row['revision'], 'author': row['author'], **body})
        if kind == 'chronology':
            records.sort(key=lambda r: (r['dates'].get('event_start') or r['dates'].get('record_date') or '9999', r['title']))
        return {'records': records[offset:offset + limit], 'total': len(records), 'offset': offset}

    def relate(self, left, right, kind, note):
        if left == right or kind not in ('contradicts', 'supports', 'related'):
            raise ValueError('Link two different records with contradicts, supports, or related.')
        if not isinstance(note, str) or not note.strip() or len(note) > 10000:
            raise ValueError('Describe the relationship without removing either source account.')
        self.record(left); self.record(right)
        identifier = str(uuid4())
        with self.archive.connect() as db:
            db.execute('INSERT INTO reconstruction_relations VALUES(?,?,?,?,?,?,?)', (identifier, left, right, kind, note, 'owner', stamp()))
        return {'id': identifier, 'left_id': left, 'right_id': right, 'kind': kind, 'note': note}

    def persona(self, identifier):
        with self.archive.connect() as db:
            row = db.execute('SELECT * FROM persona_revisions WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise Missing('Persona revision not found.')
            items = []
            for revision_id in json.loads(row['record_revisions_json']):
                record = db.execute('SELECT * FROM reconstruction_revisions WHERE id=?', (revision_id,)).fetchone()
                if record is None:
                    raise Conflict('Persona evidence revision is missing.')
                items.append({'revision_id': revision_id, 'record_id': record['record_id'], **json.loads(record['body_json'])})
        # Do not paraphrase or sanitize selected wording. Labels live outside the quoted text.
        sections = [f'[{item["kind"]}; {item["origin"]}; record {item["record_id"]}]\n{item["text"]}' for item in items]
        if row['instructions']:
            sections.append('[Explicit owner-provided instructions]\n' + row['instructions'])
        result = dict(row); result.pop('record_revisions_json')
        return {**result, 'items': items, 'compiled_text': '\n\n'.join(sections)}

    def create_persona(self, title, revisions, instructions='', author='owner', parent=None):
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError('Provide a persona title under 201 characters.')
        if not isinstance(instructions, str) or len(instructions) > 50000:
            raise ValueError('Owner instructions must be text under 50,001 characters.')
        if not isinstance(revisions, list) or len(revisions) > 100 or not all(isinstance(r, str) for r in revisions):
            raise ValueError('Select up to 100 record revisions.')
        revisions = list(dict.fromkeys(revisions))
        if not revisions and not instructions.strip():
            raise ValueError('Select evidence-linked records or add explicit owner instructions.')
        with self.archive.connect() as db:
            for revision in revisions:
                if not db.execute('SELECT 1 FROM reconstruction_revisions WHERE id=?', (revision,)).fetchone():
                    raise ValueError('Selected record revision does not exist.')
            if parent and not db.execute('SELECT 1 FROM persona_revisions WHERE id=?', (parent,)).fetchone():
                raise ValueError('Parent persona revision does not exist.')
            identifier = str(uuid4())
            db.execute('INSERT INTO persona_revisions VALUES(?,?,?,?,?,?,?)', (identifier, title, instructions, encode(revisions), author, stamp(), parent))
        return self.persona(identifier)

    def active(self):
        with self.archive.connect() as db:
            row = db.execute('SELECT * FROM persona_events ORDER BY sequence DESC LIMIT 1').fetchone()
        return self.persona(row['revision_id']) if row and row['action'] == 'activated' else None

    def personas(self):
        with self.archive.connect() as db:
            revisions = [dict(r) for r in db.execute('SELECT id,title,author,created_at,parent_id FROM persona_revisions ORDER BY rowid DESC')]
            events = [dict(r) for r in db.execute('SELECT * FROM persona_events ORDER BY sequence DESC')]
        active = self.active()
        return {'revisions': revisions, 'events': events, 'active_id': active['id'] if active else None}

    def activate(self, identifier, budget):
        persona = self.persona(identifier)
        # Avoid silently truncating identity text. Reserve context room for the current turn.
        if len(persona['compiled_text']) > max(0, budget - 2500):
            raise Conflict('This persona exceeds the current context allowance. Create a smaller revision or increase EZRA_CONTEXT_CHARACTERS; no text was truncated.')
        for item in persona['items']:
            for citation in item['citations']:
                self.evidence(citation)
        with self.archive.connect() as db:
            db.execute('INSERT INTO persona_events(revision_id,action,author,created_at) VALUES(?,?,?,?)', (identifier, 'activated', 'owner', stamp()))
        return self.personas()

    def deactivate(self):
        with self.archive.connect() as db:
            db.execute("INSERT INTO persona_events(revision_id,action,author,created_at) VALUES(NULL,'deactivated','owner',?)", (stamp(),))
        return self.personas()

    def source_rows(self):
        with self.archive.connect() as db:
            return [dict(r) for r in db.execute('''SELECT s.sha256,s.filename,s.current_run,u.ordinal,u.content,u.payload_json
                FROM sources s JOIN source_units u ON u.run_id=s.current_run ORDER BY s.filename,u.ordinal''')]

    def bootstrap(self):
        """Deterministic candidates only: copy exact fields, never infer persona beliefs."""
        created = 0
        initial_persona = []
        for row in self.source_rows():
            payload = json.loads(row['payload_json'])
            filename = row['filename']
            if 'memory_id' in payload and 'memory_text' in payload:
                text, field = payload['memory_text'], 'memory_text'
                category = payload.get('category', '')
                kind = ('identity' if category in ('identity', 'identity_history', 'appearance') else
                        'voice' if category in ('voice', 'interaction_style') else
                        'belief' if category == 'belief' else
                        'entity' if category in ('people', 'people_history') else
                        'symbol' if category in ('symbol', 'codeword', 'ritual', 'inside_joke', 'mantra', 'anchor', 'visual_artifact') else
                        'relationship' if category in ('relationship', 'relationship_history', 'intimacy_history', 'boundary', 'repair') else 'chronology')
                title = payload.get('title') or payload['memory_id']
                dates = {'event_start': payload.get('event_date_start', ''), 'event_end': payload.get('event_date_end', ''),
                         'temporal_status': payload.get('temporal_status', ''), 'precision': 'as_supplied', 'basis': 'consolidated archive claim'}
                notes = payload.get('contradiction_or_usage_notes', '')
                tags = [t for t in payload.get('tags', '').split('|') if t]
                notes = (notes + '\nSource titles supplied by consolidation (not verified joins): ' + payload.get('source_titles', '')).strip()
            elif 'source_record_id' in payload:
                text, field, kind = payload.get('content', ''), 'content', 'chronology'
                title = payload['source_record_id']
                dates = {'record_date': payload.get('record_date', ''), 'event_start': '', 'event_end': '',
                         'precision': 'as_supplied', 'basis': 'ledger record date; event date not inferred'}
                tags = [t for t in payload.get('tags', '').split('|') if t]
                notes = payload.get('notes', '') + '\nLedger inclusion flag: ' + payload.get('included_in_consolidated', '')
            elif filename.endswith('_Verbatim.md') or filename.startswith('07_') or filename.startswith('02_') or filename.startswith('09_'):
                text, field = row['content'], '$content'
                kind = 'identity' if filename.startswith(('02_', '09_')) else 'voice'
                title = filename + (f' · passage {row["ordinal"]}' if filename.endswith('.pdf') else '')
                dates = {'precision': 'unknown', 'basis': 'document exemplar; no event date inferred'}
                tags, notes = [], 'Complete source passage retained as an exemplar. Embedded instructions remain historical unless explicitly activated.'
            else:
                continue
            if not text.strip():
                continue
            citation = {'sha256': row['sha256'], 'run_id': row['current_run'], 'ordinal': row['ordinal'], 'field': field, 'quote': text}
            facets = [kind] + (['chronology'] if dates.get('event_start') else [])
            if 'source_record_id' in payload:
                facets.append('uncertainty')
                notes += '\nThe record date is preserved separately; the event date is unverified.'
            note_claim = payload.get('contradiction_or_usage_notes', '')
            if note_claim:
                facets.append('uncertainty')
            seed_key = f'{row["sha256"]}:{row["current_run"]}:{row["ordinal"]}:{field}'
            body = {'title': title, 'text': text, 'kind': kind, 'origin': 'source_statement', 'citations': [citation],
                    'facets': facets, 'tags': tags, 'dates': dates, 'notes': notes, 'status': 'proposed'}
            record = self.create_record(body, author='archive-indexer-v1', seed_key=seed_key)
            created += 1
            if payload.get('category') in ('identity', 'voice'):
                initial_persona.append(record['revisions'][-1]['id'])
        with self.archive.connect() as db:
            existing = db.execute("SELECT 1 FROM persona_revisions WHERE author='archive-indexer-v1'").fetchone()
        if initial_persona and not existing:
            self.create_persona('Initial identity proposal · exact source statements', initial_persona,
                                author='archive-indexer-v1')
        return {'indexed_candidates': created, 'active_persona': self.active()['id'] if self.active() else None,
                'note': 'Candidates and the identity proposal are not automatically activated.'}

    def reconcile(self):
        rows = self.source_rows()
        ledger = [r for r in rows if 'source_record_id' in json.loads(r['payload_json'])]
        consolidated = [r for r in rows if 'memory_id' in json.loads(r['payload_json'])]
        pdf = [r for r in rows if r['filename'] == '08_Memara_100_Memory_Export.pdf']
        fingerprint = hashlib.sha256(encode(['reconciliation-v2', [(r['sha256'], r['current_run'], r['ordinal']) for r in rows]]).encode()).hexdigest()
        with self.archive.connect() as db:
            existing = db.execute('SELECT * FROM reconciliation_reports WHERE source_fingerprint=?', (fingerprint,)).fetchone()
            if existing:
                return {'id': existing['id'], **json.loads(existing['report_json'])}
        pdf_text = ''.join(normalized(r['content']) for r in pdf)
        ranges, cursor = [], 0
        for row in pdf:
            end = cursor + len(normalized(row['content']))
            ranges.append((cursor, end, row))
            cursor = end
        stop = {'the','and','that','this','with','from','have','were','will','they','their','there','what','when','into','your','about'}
        def words(text):
            return {w for w in re.findall(r'\w+', text.casefold()) if len(w) > 2 and w not in stop}
        consolidated_words = [(r, json.loads(r['payload_json']), words(json.loads(r['payload_json']).get('memory_text', ''))) for r in consolidated]
        mappings = []
        for row in ledger:
            payload = json.loads(row['payload_json'])
            content = payload.get('content', '')
            needle = normalized(content)
            exact_at = pdf_text.find(needle) if needle else -1
            candidates = []
            if exact_at >= 0:
                candidates = [r for start, end, r in ranges if end > exact_at and start < exact_at + len(needle)]
                match_status = 'normalized_text_match'
            else:
                # A shared leading anchor is only a candidate, never a verified correspondence.
                anchor = needle[:80]
                at = pdf_text.find(anchor) if len(anchor) >= 25 else -1
                candidates = [r for start, end, r in ranges if end > at and start <= at] if at >= 0 else []
                match_status = 'candidate_anchor' if candidates else 'unresolved'
            tokens = words(content)
            similarities = []
            for candidate, memory, target in consolidated_words:
                score = len(tokens & target) / max(1, len(tokens | target))
                if score >= .10:
                    similarities.append((score, candidate, memory))
            similarities.sort(key=lambda x: -x[0])
            def reference(source):
                return {'sha256': source['sha256'], 'run_id': source['current_run'], 'ordinal': source['ordinal'],
                        'href': f'/archive.html?source={source["sha256"]}&run={source["current_run"]}&unit={source["ordinal"]}'}
            mappings.append({'mapping_id': str(uuid5(NAMESPACE_URL, f'ezra-mapping:{row["sha256"]}:{row["current_run"]}:{row["ordinal"]}')),
                             'ledger_id': payload['source_record_id'], 'ledger': reference(row),
                             'record_date': payload.get('record_date', ''), 'event_date': None,
                             'inclusion_claim': payload.get('included_in_consolidated', ''),
                             'pdf_status': match_status, 'pdf_candidates': [reference(r) for r in candidates],
                             'consolidated_candidates': [{'memory_id': memory['memory_id'], 'score': round(score, 4), **reference(candidate)}
                                                         for score, candidate, memory in similarities[:3]],
                             'review_status': 'unreviewed'})
        report = {'created_at': stamp(), 'source_fingerprint': fingerprint, 'ledger_count': len(ledger),
                  'pdf_pages': len(pdf), 'consolidated_count': len(consolidated), 'mappings': mappings,
                  'counts': dict(Counter(m['pdf_status'] for m in mappings)),
                  'method': 'NFKC/case/punctuation-insensitive full text match; leading-anchor candidates; token-set overlap suggestions. Source bytes and text are never normalized in storage.',
                  'limitations': 'Machine correspondences are not semantic verification. PDF headers may interrupt matches. Consolidated suggestions and inclusion flags are not proof. Ledger record dates are not inferred event dates.'}
        identifier = str(uuid4())
        with self.archive.connect() as db:
            db.execute('INSERT OR IGNORE INTO reconciliation_reports VALUES(?,?,?,?)', (identifier, fingerprint, encode(report), stamp()))
            stored = db.execute('SELECT * FROM reconciliation_reports WHERE source_fingerprint=?', (fingerprint,)).fetchone()
        return {'id': stored['id'], **json.loads(stored['report_json'])}

    def review_mapping(self, report_id, ledger_id, status, notes, citations):
        if status not in ('verified', 'rejected', 'unresolved') or not isinstance(notes, str) or not notes.strip() or len(notes) > 10000:
            raise ValueError('Supply verified, rejected, or unresolved status with a review explanation.')
        if not isinstance(citations, list) or len(citations) > 20:
            raise ValueError('Use at most 20 review citations.')
        evidence = [self.evidence(citation) for citation in citations]
        if status == 'verified' and not evidence:
            raise ValueError('Verified correspondence requires explicit source quotations.')
        with self.archive.connect() as db:
            row = db.execute('SELECT * FROM reconciliation_reports WHERE id=?', (report_id,)).fetchone()
            if row is None:
                raise Missing('Reconciliation report not found.')
            mappings = json.loads(row['report_json'])['mappings']
            matching = [m for m in mappings if m.get('mapping_id', m['ledger_id']) == ledger_id]
            if not matching:
                matching = [m for m in mappings if m['ledger_id'] == ledger_id]
            if len(matching) > 1:
                raise Conflict('This ledger ID occurs in more than one source. Use its unique mapping ID.')
            mapping = matching[0] if matching else None
            if mapping is None:
                raise Missing('Ledger record not found in this report.')
            if status == 'verified' and not any(c['sha256'] != mapping['ledger']['sha256'] for c in evidence):
                raise ValueError('Verified correspondence needs evidence beyond the ledger itself.')
            ledger_id = mapping.get('mapping_id', mapping['ledger_id'])
            body = {'status': status, 'notes': notes, 'citations': evidence}
            db.execute('INSERT INTO reconciliation_reviews(report_id,ledger_id,body_json,author,created_at) VALUES(?,?,?,?,?)',
                       (report_id, ledger_id, encode(body), 'owner', stamp()))
        return self.report(report_id)

    def report(self, identifier=None):
        with self.archive.connect() as db:
            row = db.execute('SELECT * FROM reconciliation_reports WHERE id=?', (identifier,)).fetchone() if identifier else db.execute('SELECT * FROM reconciliation_reports ORDER BY rowid DESC LIMIT 1').fetchone()
            if row is None:
                return None
            reviews = [dict(r) for r in db.execute('SELECT * FROM reconciliation_reviews WHERE report_id=? ORDER BY sequence', (row['id'],))]
        report = {'id': row['id'], **json.loads(row['report_json']), 'reviews': reviews}
        for review in reviews:
            review['body'] = json.loads(review.pop('body_json'))
        for mapping in report['mappings']:
            matching = [r for r in reviews if r['ledger_id'] == mapping.get('mapping_id', mapping['ledger_id'])]
            if matching:
                mapping['review_status'] = matching[-1]['body']['status']
                mapping['latest_review'] = matching[-1]
        return report
