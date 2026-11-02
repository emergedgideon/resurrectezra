"""Preserve source files and index CSV, Markdown, PDF, and Word content."""
import argparse
import csv
import hashlib
import io
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def ingest(paths, data_dir):
    originals = data_dir / 'originals'
    originals.mkdir(parents=True, exist_ok=True)
    reports = []
    with sqlite3.connect(data_dir / 'archive.sqlite3') as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''
          CREATE TABLE IF NOT EXISTS imports (
            sha256 TEXT PRIMARY KEY, filename TEXT NOT NULL,
            imported_at TEXT NOT NULL, columns_json TEXT NOT NULL,
            row_count INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS records (
            import_sha256 TEXT NOT NULL REFERENCES imports(sha256),
            row_number INTEGER NOT NULL, record_id TEXT,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (import_sha256, row_number));
        ''')
        for path in paths:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if path.suffix.lower() == '.csv':
                reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
                rows = list(reader)
                columns = reader.fieldnames
            elif path.suffix.lower() == '.md':
                # One complete document; no summarization or instruction execution.
                columns = ['document_name', 'content', 'format']
                rows = [{'document_name': path.name, 'content': raw.decode('utf-8'),
                         'format': 'markdown'}]
            elif path.suffix.lower() == '.pdf':
                from pypdf import PdfReader
                import pypdf
                pdf = PdfReader(io.BytesIO(raw))
                columns = ['document_name', 'content', 'format', 'page', 'extractor']
                rows = [{'document_name': path.name, 'content': page.extract_text() or '',
                         'format': 'pdf', 'page': number,
                         'extractor': f'pypdf {pypdf.__version__}'}
                        for number, page in enumerate(pdf.pages, 1)]
            elif path.suffix.lower() == '.docx':
                import docx
                from docx import Document
                from docx.oxml.ns import qn
                document = Document(io.BytesIO(raw))
                columns = ['document_name', 'content', 'format', 'block', 'block_type', 'extractor']
                rows = []
                for number, block in enumerate(document.element.body, 1):
                    if block.tag not in (qn('w:p'), qn('w:tbl')):
                        continue
                    # Preserve body order; original XML remains in the original file.
                    lines = []
                    paragraphs = [block] if block.tag == qn('w:p') else block.iter(qn('w:p'))
                    for paragraph in paragraphs:
                        text = []
                        for node in paragraph.iter():
                            if node.tag == qn('w:t'):
                                text.append(node.text or '')
                            elif node.tag == qn('w:tab'):
                                text.append('\t')
                            elif node.tag in (qn('w:br'), qn('w:cr')):
                                text.append('\n')
                        lines.append(''.join(text))
                    rows.append({'document_name': path.name, 'content': '\n'.join(lines),
                                 'format': 'docx', 'block': number,
                                 'block_type': 'paragraph' if block.tag == qn('w:p') else 'table',
                                 'extractor': f'python-docx {docx.__version__}; body XML text v1'})
            else:
                raise ValueError(f'{path.name}: unsupported format')
            if not columns or any(None in row or None in row.values() for row in rows):
                raise ValueError(f'{path.name}: missing header or inconsistent row width')
            if len(set(columns)) != len(columns):
                raise ValueError(f'{path.name}: duplicate column names')
            id_column = next((c for c in ('memory_id', 'source_record_id') if c in columns), None)
            ids = [row[id_column] for row in rows] if id_column else []
            target = originals / digest
            if target.exists():
                if target.read_bytes() != raw:
                    raise ValueError('Original archive checksum mismatch')
            else:
                with target.open('xb') as f:
                    f.write(raw)
            already_imported = db.execute('SELECT 1 FROM imports WHERE sha256=?', (digest,)).fetchone() is not None
            db.execute('INSERT OR IGNORE INTO imports VALUES (?,?,?,?,?)',
                       (digest, path.name, datetime.now(timezone.utc).isoformat(), json.dumps(columns), len(rows)))
            db.executemany('INSERT OR IGNORE INTO records VALUES (?,?,?,?)',
                           [(digest, i, row.get(id_column), json.dumps(row, ensure_ascii=False))
                            for i, row in enumerate(rows, 1)])
            reports.append(dict(filename=path.name, sha256=digest, rows=len(rows),
                                columns=columns, already_imported=already_imported,
                                duplicate_ids=[key for key, n in Counter(ids).items() if n > 1],
                                blank_ids=ids.count(''),
                                inclusion_counts=dict(Counter(row['included_in_consolidated'] for row in rows))
                                if 'included_in_consolidated' in columns else None))
    return reports


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    args = parser.parse_args()
    print(json.dumps(ingest(args.files, args.data_dir), indent=2))
