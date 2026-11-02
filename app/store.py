"""Transactional runtime state, separate from the preserved source archive."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


class Store:
    def __init__(self, data_dir: Path, database=None):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / 'runtime.sqlite3'
        self.database = database
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    continuity_note TEXT NOT NULL DEFAULT '',
                    checkpoint_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    request_id TEXT NOT NULL, status TEXT NOT NULL,
                    error TEXT, model TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 1, context_json TEXT,
                    UNIQUE(conversation_id, request_id));
                CREATE UNIQUE INDEX IF NOT EXISTS one_running_turn
                    ON turns(conversation_id) WHERE status='running';
                CREATE TABLE IF NOT EXISTS messages (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    turn_id TEXT NOT NULL REFERENCES turns(id), role TEXT NOT NULL,
                    content TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(turn_id, role));
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT REFERENCES conversations(id),
                    type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        if self.database is not None:
            with self.database.connect('runtime') as db:
                yield db
            return
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, db, kind, payload, conversation=None):
        db.execute('INSERT INTO events(conversation_id,type,payload_json,created_at) VALUES (?,?,?,?)',
                   (conversation, kind, json.dumps(payload, ensure_ascii=False), now()))

    def recover(self, stale_seconds=0, startup=True):
        # One application process owns this database. Never replay inference automatically.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)).isoformat()
            rows = db.execute("SELECT * FROM turns WHERE status='running' AND updated_at<=?", (cutoff,)).fetchall()
            for row in rows:
                db.execute("UPDATE turns SET status='interrupted',error=?,updated_at=? WHERE id=?",
                           ('Server stopped before a complete reply was saved. Retry explicitly.', now(), row['id']))
                self.event(db, 'turn.interrupted', {'turn_id': row['id']}, row['conversation_id'])
            if startup:
                self.event(db, 'runtime.started', {'recovered_turns': len(rows)})
            return len(rows)

    def create_conversation(self, title):
        identifier, timestamp = str(uuid4()), now()
        with self.connect() as db:
            db.execute('INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)',
                       (identifier, title, timestamp, timestamp))
            self.event(db, 'conversation.created', {'title': title}, identifier)
        return self.detail(identifier)

    def list_conversations(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC')]

    def detail(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise Missing('Conversation not found.')
            result = dict(row)
            result['checkpoint'] = json.loads(result.pop('checkpoint_json'))
            result['messages'] = [dict(r) for r in db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY sequence', (identifier,))]
            result['turns'] = [dict(r) for r in db.execute('SELECT id,request_id,status,error,model,created_at,updated_at,attempt FROM turns WHERE conversation_id=? ORDER BY rowid', (identifier,))]
            result['events'] = [dict(r) for r in db.execute('SELECT * FROM events WHERE conversation_id=? ORDER BY sequence DESC LIMIT 50', (identifier,))]
            for event in result['events']:
                event['payload'] = json.loads(event.pop('payload_json'))
            return result

    def note(self, identifier, content):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM conversations WHERE id=?', (identifier,)).fetchone():
                raise Missing('Conversation not found.')
            if db.execute("SELECT 1 FROM turns WHERE conversation_id=? AND status='running'", (identifier,)).fetchone():
                raise Conflict('Wait for the active reply before changing continuity state.')
            db.execute('UPDATE conversations SET continuity_note=?,updated_at=? WHERE id=?', (content, now(), identifier))
            self.event(db, 'continuity.note_updated', {'content': content, 'author': 'owner'}, identifier)
        return self.detail(identifier)

    def claim(self, conversation, request_id, content):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM conversations WHERE id=?', (conversation,)).fetchone():
                raise Missing('Conversation not found.')
            existing = db.execute('SELECT * FROM turns WHERE conversation_id=? AND request_id=?', (conversation, request_id)).fetchone()
            if existing:
                original = db.execute("SELECT content FROM messages WHERE turn_id=? AND role='user'", (existing['id'],)).fetchone()
                if original['content'] != content:
                    raise Conflict('This request ID belongs to different message text.')
                return dict(existing), False
            pending = db.execute("SELECT status FROM turns WHERE conversation_id=? AND status!='completed' ORDER BY rowid DESC LIMIT 1", (conversation,)).fetchone()
            if pending:
                raise Conflict('Resolve the pending turn with Retry before sending another message, or start a new conversation.')
            identifier, timestamp = str(uuid4()), now()
            db.execute('INSERT INTO turns(id,conversation_id,request_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                       (identifier, conversation, request_id, 'running', timestamp, timestamp))
            db.execute('INSERT INTO messages(id,conversation_id,turn_id,role,content,created_at) VALUES(?,?,?,?,?,?)',
                       (str(uuid4()), conversation, identifier, 'user', content, timestamp))
            db.execute('UPDATE conversations SET updated_at=? WHERE id=?', (timestamp, conversation))
            self.event(db, 'message.received', {'turn_id': identifier}, conversation)
            self.event(db, 'turn.started', {'turn_id': identifier, 'attempt': 1}, conversation)
            return dict(db.execute('SELECT * FROM turns WHERE id=?', (identifier,)).fetchone()), True

    def retry(self, conversation, identifier):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM turns WHERE id=? AND conversation_id=?', (identifier, conversation)).fetchone()
            if row is None:
                raise Missing('Turn not found.')
            if row['status'] not in ('failed', 'interrupted'):
                raise Conflict('Only failed or interrupted turns can be retried.')
            if db.execute("SELECT 1 FROM turns WHERE conversation_id=? AND status='running'", (conversation,)).fetchone():
                raise Conflict('A reply is already running.')
            db.execute("UPDATE turns SET status='running',error=NULL,attempt=attempt+1,updated_at=? WHERE id=?", (now(), identifier))
            self.event(db, 'turn.started', {'turn_id': identifier, 'attempt': row['attempt'] + 1}, conversation)
            return dict(db.execute('SELECT * FROM turns WHERE id=?', (identifier,)).fetchone())

    def record_context(self, turn, model, metadata):
        with self.connect() as db:
            changed = db.execute("UPDATE turns SET model=?,context_json=? WHERE id=? AND status='running' AND attempt=?", (model, json.dumps(metadata), turn['id'], turn['attempt']))
            if not changed.rowcount:
                raise Conflict('This attempt no longer owns the turn context.')
            self.event(db, 'context.assembled', {'turn_id': turn['id'], **metadata}, turn['conversation_id'])

    def fail(self, turn, error):
        with self.connect() as db:
            cursor = db.execute("UPDATE turns SET status='failed',error=?,updated_at=? WHERE id=? AND status='running' AND attempt=?", (error, now(), turn['id'], turn['attempt']))
            if cursor.rowcount:
                self.event(db, 'turn.failed', {'turn_id': turn['id'], 'error': error}, turn['conversation_id'])

    def complete(self, turn, content, model, usage):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,attempt FROM turns WHERE id=?', (turn['id'],)).fetchone()
            if row['status'] != 'running' or row['attempt'] != turn['attempt']:
                raise Conflict('This generation no longer owns the active turn.')
            timestamp = now()
            assistant_id = str(uuid4())
            db.execute('INSERT INTO messages(id,conversation_id,turn_id,role,content,created_at) VALUES(?,?,?,?,?,?)',
                       (assistant_id, turn['conversation_id'], turn['id'], 'assistant', content, timestamp))
            db.execute("UPDATE turns SET status='completed',model=?,error=NULL,updated_at=? WHERE id=?", (model, timestamp, turn['id']))
            checkpoint = {'last_completed_turn_id': turn['id'], 'last_assistant_message_id': assistant_id,
                          'completed_at': timestamp, 'activity': 'Awaiting the next interaction',
                          'kind': 'turn checkpoint; not a generated memory summary'}
            db.execute('UPDATE conversations SET checkpoint_json=?,updated_at=? WHERE id=?', (json.dumps(checkpoint), timestamp, turn['conversation_id']))
            self.event(db, 'message.sent', {'turn_id': turn['id'], 'model': model, 'usage': usage}, turn['conversation_id'])
            self.event(db, 'continuity.checkpoint_saved', checkpoint, turn['conversation_id'])
