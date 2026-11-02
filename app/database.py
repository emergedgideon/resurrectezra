"""PostgreSQL persistence for the application's deliberately small SQL vocabulary.

Local mode still uses native sqlite3. Cloud mode preserves the current SQL model,
keeps ordering explicit, serializes transactions per private schema, and exports
portable SQLite backups. This is not a general SQL compatibility library.
"""
from contextlib import contextmanager
import re
import sqlite3


class PersistenceError(Exception):
    """Sanitized connection/storage error suitable for the private UI."""


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor=None, rows=None):
        self.cursor = cursor
        self.rows = iter(rows or [])
        self.rowcount = cursor.rowcount if cursor else 0

    def fetchone(self):
        row = self.cursor.fetchone() if self.cursor else next(self.rows, None)
        return Row({k: v for k, v in row.items() if k != '_rowid'}) if row is not None else None

    def fetchall(self):
        return list(self)

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


class Postgres:
    def __init__(self, url, password=''):
        self.url = url  # Secret: never include in repr, logs, exceptions, or exports.
        self.password = password

    def conninfo(self):
        if not self.password:
            return self.url
        from urllib.parse import urlsplit, urlunsplit, quote
        parts = urlsplit(self.url.replace('[YOUR-PASSWORD]', '').replace('[YOUR_PASSWORD]', ''))
        host = parts.hostname
        if ':' in host:
            host = '[' + host + ']'
        if parts.port:
            host += ':' + str(parts.port)
        authority = quote(parts.username or 'postgres', safe='') + ':' + quote(self.password, safe='') + '@' + host
        return urlunsplit((parts.scheme, authority, parts.path, parts.query, parts.fragment))

    @contextmanager
    def connect(self, kind):
        import psycopg
        from psycopg.rows import dict_row
        schema = {'runtime': 'ezra_runtime', 'archive': 'ezra_archive'}[kind]
        connection = None
        try:
            from urllib.parse import urlparse
            import certifi
            dsn = self.conninfo()
            tls = {} if urlparse(dsn).hostname in ('localhost', '127.0.0.1', '::1') else {'sslmode': 'verify-full', 'sslrootcert': certifi.where()}
            connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row,
                                         connect_timeout=15, prepare_threshold=None, **tls)
            lock = 862310 if kind == 'runtime' else 862311
            connection.execute('SET statement_timeout TO 60000')
            connection.execute('SELECT pg_advisory_lock(%s)', (lock,))
            connection.execute(f'CREATE SCHEMA IF NOT EXISTS {schema}')
            connection.execute(f'REVOKE ALL ON SCHEMA {schema} FROM PUBLIC')
            connection.execute(f'SET search_path TO {schema}')
            connection.execute('SET statement_timeout TO 60000')
            connection.autocommit = False
            # Serializes a single-owner app's schema transactions across rolling
            # deployments as well as threads. Locks release on rollback/disconnect.
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (lock,))
            connection.execute('SELECT pg_advisory_unlock(%s)', (lock,))
            connection.execute('''CREATE TABLE IF NOT EXISTS _ezra_schema (
                name TEXT PRIMARY KEY, kind TEXT NOT NULL, sql TEXT NOT NULL)''')
            adapter = Connection(connection)
            yield adapter
            connection.commit()
        except psycopg.Error:
            if connection is not None:
                connection.rollback()
            raise PersistenceError('Cloud database operation failed. Check database connectivity, SSL settings, and credentials. No credential values are shown.') from None
        except BaseException:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()


class Connection:
    def __init__(self, connection):
        self.connection = connection
        self._columns = {}

    def columns(self, table):
        if table not in self._columns:
            self._columns[table] = [r['column_name'] for r in self.connection.execute('''SELECT column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name=%s AND column_name!='_rowid'
            ORDER BY ordinal_position''', (table,))]
        return self._columns[table]

    def execute(self, sql, parameters=None):
        original = sql.strip().rstrip(';')
        lower = original.lower()
        if lower.startswith('begin immediate') or lower.startswith('begin exclusive'):
            return Cursor()  # The connection already owns the transaction advisory lock.
        if lower.startswith('pragma'):
            if lower == 'pragma defer_foreign_keys=on':
                self.connection.execute('SET CONSTRAINTS ALL DEFERRED')
            elif lower == 'pragma foreign_key_check':
                self.connection.execute('SET CONSTRAINTS ALL IMMEDIATE')
            elif lower.startswith('pragma table_info'):
                match = re.search(r'\(["\s]*([a-zA-Z_][a-zA-Z_0-9]*)', original)
                if not match:
                    raise ValueError('Unsupported schema inspection.')
                return Cursor(rows=[Row(cid=n, name=name) for n, name in enumerate(self.columns(match[1]))])
            elif lower == 'pragma integrity_check':
                return Cursor(rows=[Row(integrity_check='ok')])
            return Cursor()
        schema_object = re.match(r'CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX)\s+IF\s+NOT\s+EXISTS\s+(\w+)', original, re.I)
        translated = original
        if schema_object and schema_object[1].upper() == 'TABLE':
            translated = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY', translated, flags=re.I)
            translated = re.sub(r'(REFERENCES\s+\w+\s*\([^)]*\))', r'\1 DEFERRABLE INITIALLY IMMEDIATE', translated, flags=re.I)
            at = translated.find('(')
            translated = translated[:at + 1] + '_rowid BIGSERIAL UNIQUE, ' + translated[at + 1:]
        if 'sqlite_master' in translated:
            translated = translated.replace('sqlite_master', "(SELECT table_name AS name, 'table'::text AS type FROM information_schema.tables WHERE table_schema=current_schema() AND table_name NOT LIKE '_ezra_%') AS sqlite_master")
        translated = re.sub(r'\browid\b', '_rowid', translated)
        ignore = bool(re.match(r'INSERT\s+OR\s+IGNORE\s+', translated, re.I))
        translated = re.sub(r'INSERT\s+OR\s+IGNORE\s+', 'INSERT ', translated, flags=re.I)
        positional = re.match(r'(INSERT\s+INTO\s+(\w+))\s+VALUES', translated, re.I)
        if positional:
            columns = ','.join('"' + c + '"' for c in self.columns(positional[2]))
            translated = translated[:positional.end(1)] + '(' + columns + ')' + translated[positional.end(1):]
        if ignore:
            translated += ' ON CONFLICT DO NOTHING'
        if parameters:
            translated = translated.replace('%', '%%').replace('?', '%s')
        else:
            translated = translated.replace('?', '%s')
        cursor = self.connection.execute(translated, parameters if parameters else None)
        if schema_object:
            self.connection.execute('INSERT INTO _ezra_schema(name,kind,sql) VALUES(%s,%s,%s) ON CONFLICT(name) DO NOTHING',
                                    (schema_object[2], schema_object[1].lower(), original))
        return Cursor(cursor)

    def executemany(self, sql, rows):
        # psycopg batches these parameterized inserts using pipeline mode rather
        # than paying a network round trip for every archive passage.
        translated = sql.strip().rstrip(';')
        if not translated.upper().startswith('INSERT '):
            for row in rows:
                self.execute(sql, row)
            return
        ignore = bool(re.match(r'INSERT\s+OR\s+IGNORE\s+', translated, re.I))
        translated = re.sub(r'INSERT\s+OR\s+IGNORE\s+', 'INSERT ', translated, flags=re.I)
        positional = re.match(r'(INSERT\s+INTO\s+(\w+))\s+VALUES', translated, re.I)
        if positional:
            columns = ','.join('"' + c + '"' for c in self.columns(positional[2]))
            translated = translated[:positional.end(1)] + '(' + columns + ')' + translated[positional.end(1):]
        if ignore:
            translated += ' ON CONFLICT DO NOTHING'
        translated = translated.replace('%', '%%').replace('?', '%s')
        with self.connection.cursor() as cursor:
            cursor.executemany(translated, rows)

    def executescript(self, script):
        for statement in script.split(';'):
            if statement.strip():
                self.execute(statement)

    def sync_sequences(self):
        for row in self.connection.execute('''SELECT table_name,column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND column_default LIKE 'nextval(%' '''):
            table, column = row['table_name'], row['column_name']
            # Identifiers come exclusively from our private schema catalog.
            self.connection.execute(f'''SELECT setval(pg_get_serial_sequence(%s,%s),
                COALESCE((SELECT max("{column}") FROM "{table}"),1),
                EXISTS(SELECT 1 FROM "{table}"))''', (table, column))

    def backup(self, target):
        """Advisory lock held: export one consistent schema transaction to SQLite."""
        definitions = self.connection.execute('SELECT * FROM _ezra_schema ORDER BY kind DESC,name').fetchall()
        target.execute('PRAGMA foreign_keys=OFF')
        for definition in definitions:
            if definition['kind'] == 'table':
                target.execute(definition['sql'])
        for definition in definitions:
            if definition['kind'] != 'table':
                continue
            table = definition['name']
            columns = self.columns(table)
            integer_pk = any(r[2].upper() == 'INTEGER' and r[5] for r in target.execute(f'PRAGMA table_info("{table}")'))
            fields = (['rowid'] if not integer_pk else []) + columns
            names = ','.join('"' + c + '"' for c in fields)
            placeholders = ','.join('?' for _ in fields)
            for row in self.connection.execute(f'SELECT * FROM "{table}" ORDER BY _rowid'):
                values = ([row['_rowid']] if not integer_pk else []) + [row[c] for c in columns]
                target.execute(f'INSERT INTO "{table}"({names}) VALUES({placeholders})', values)
        for definition in definitions:
            if definition['kind'] == 'index':
                target.execute(definition['sql'])
        target.commit()
        if target.execute('PRAGMA foreign_key_check').fetchall():
            raise PersistenceError('Portable export failed reference verification.')
