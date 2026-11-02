"""Local, source-linked extraction. Never execute document instructions."""
import csv
import hashlib
import io
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

VERSION = 'ezra-extract-2.0'
SUPPORTED = {'.csv', '.md', '.txt', '.pdf', '.docx', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.tif', '.tiff', '.bmp'}


def ocr(image, warnings):
    binary = shutil.which('tesseract')
    if not binary:
        warnings.append('Local OCR unavailable: install Tesseract. Original image is preserved; retry after installation.')
        return None
    with tempfile.TemporaryDirectory(prefix='ezra-ocr-') as directory:
        source = Path(directory) / 'page.png'
        image.save(source, format='PNG')
        result = subprocess.run([binary, str(source), 'stdout', '-l', 'eng'],
                                capture_output=True, timeout=60)
        if result.returncode:
            warnings.append('Tesseract could not recognize this page. Check the local English language data.')
            return None
        return result.stdout.decode('utf-8')


def extract(path, filename):
    path = Path(path)
    suffix = Path(filename).suffix.lower()
    raw = path.read_bytes()
    units, warnings, tools = [], [], [VERSION]

    def add(kind, location, content, payload=None):
        units.append({'kind': kind, 'location': location, 'content': content,
                      'payload': payload or {}})

    if suffix in ('.md', '.txt'):
        text = raw.decode('utf-8')
        add('document', {'line_start': 1, 'line_end': text.count('\n') + 1}, text)
        tools.append('Python UTF-8 decoder; no text normalization')
    elif suffix == '.csv':
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('CSV requires a header with unique column names.')
        for number, row in enumerate(reader, 1):
            if None in row or None in row.values():
                raise ValueError(f'CSV logical row {number} has inconsistent field count.')
            add('row', {'row': number, 'physical_line_end': reader.line_num},
                '\n'.join(f'{key}: {value}' for key, value in row.items()), row)
        tools.append('Python csv.DictReader; field values preserved in payload')
    elif suffix == '.docx':
        import docx
        from docx.oxml.ns import qn
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            if sum(info.file_size for info in package.infolist()) > 256 * 1024 * 1024:
                raise ValueError('Expanded Word content exceeds the 256 MiB extraction limit. Original preserved.')
        document = docx.Document(io.BytesIO(raw))
        for number, block in enumerate(document.element.body, 1):
            if block.tag not in (qn('w:p'), qn('w:tbl')):
                continue
            lines = []
            paragraphs = [block] if block.tag == qn('w:p') else block.iter(qn('w:p'))
            for paragraph in paragraphs:
                pieces = []
                for node in paragraph.iter():
                    if node.tag == qn('w:t'):
                        pieces.append(node.text or '')
                    elif node.tag == qn('w:tab'):
                        pieces.append('\t')
                    elif node.tag in (qn('w:br'), qn('w:cr')):
                        pieces.append('\n')
                lines.append(''.join(pieces))
            kind = 'paragraph' if block.tag == qn('w:p') else 'table'
            add(kind, {'block': number}, '\n'.join(lines))
        tools.append('python-docx ' + docx.__version__)
        warnings.append('Word extraction covers body paragraphs/tables. Formatting, headers, footers, images, and annotations remain in the original; they are not fully represented here.')
    elif suffix == '.pdf':
        import pypdf
        from pypdf import PdfReader
        capture = io.StringIO()
        handler = logging.StreamHandler(capture)
        logger = logging.getLogger('pypdf')
        logger.addHandler(handler)
        rendered = None
        try:
            pdf = PdfReader(io.BytesIO(raw))
            if pdf.is_encrypted:
                raise ValueError('Encrypted PDF: upload an unlocked copy. The encrypted original remains preserved.')
            tools.append('pypdf ' + pypdf.__version__)
            for number, page in enumerate(pdf.pages, 1):
                content = page.extract_text() or ''
                kind = 'page'
                if not content.strip():
                    import pypdfium2
                    if rendered is None:
                        rendered = pypdfium2.PdfDocument(raw)
                    raster_page = rendered[number - 1]
                    width, height = raster_page.get_size()
                    bitmap = raster_page.render(scale=min(2, 2400 / max(width, height)))
                    image = bitmap.to_pil()
                    try:
                        recognized = ocr(image, warnings)
                    finally:
                        image.close()
                        bitmap.close()
                        raster_page.close()
                    if recognized is not None:
                        content, kind = recognized, 'ocr_page'
                add(kind, {'page': number}, content)
        finally:
            if rendered is not None:
                rendered.close()
            logger.removeHandler(handler)
        if capture.getvalue().strip():
            warnings.append('PDF parser warnings: ' + capture.getvalue().strip())
        warnings.append('PDF text is derived extraction. OCR is attempted on text-empty pages only; mixed text/image pages may contain additional unindexed text.')
    elif suffix in SUPPORTED:
        from PIL import Image, ImageOps, __version__ as pillow_version
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            try:
                content = ocr(image, warnings)
                add('image', {'frame': 1}, content or '',
                    {'width': source.width, 'height': source.height, 'image_format': source.format,
                     'ocr_available': content is not None})
                if getattr(source, 'n_frames', 1) > 1:
                    warnings.append('Only the first image frame was indexed; all frames remain in the original.')
            finally:
                image.close()
        tools.append('Pillow ' + pillow_version)
    else:
        raise ValueError('Unsupported source format.')
    if any(unit['kind'] in ('ocr_page', 'image') for unit in units):
        tools.append('Local Tesseract OCR, eng, where available; PDFium for scanned PDF rendering')
        warnings.append('OCR is a machine transcription and may be inaccurate. The original remains authoritative; no image understanding model is used.')
    if not units or not any(unit['content'].strip() for unit in units):
        warnings.append('No searchable text was extracted. Inspect the original; image-only sources may need OCR installation or manual transcription.')
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'units': units,
            'warnings': list(dict.fromkeys(warnings)), 'extractor': '; '.join(tools)}


if __name__ == '__main__':
    try:
        print(json.dumps(extract(sys.argv[1], sys.argv[2]), ensure_ascii=False))
    except Exception as exc:
        # No tracebacks or document contents in subprocess logs.
        print(json.dumps({'error': f'{type(exc).__name__}: {str(exc)[:500]}'}))
        raise SystemExit(1)
