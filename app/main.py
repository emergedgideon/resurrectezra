import asyncio
from contextlib import asynccontextmanager
import hmac
import fcntl
from pathlib import Path
import io
import threading
import sqlite3
import zipfile
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File, Query
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field

from .config import Settings
from .inference import Featherless, ProviderError, assemble_context
from .store import Conflict, Missing, Store
from .archive import Archive
from .reconstruction import Reconstruction


class ConversationInput(BaseModel):
    title: str = Field(default='New conversation', min_length=1, max_length=160)


class TurnInput(BaseModel):
    request_id: UUID
    content: str = Field(min_length=1, max_length=200000)


class NoteInput(BaseModel):
    content: str = Field(max_length=12000)


class RecordInput(BaseModel):
    body: dict
    expected_revision: int | None = None


class PersonaInput(BaseModel):
    title: str
    revisions: list[str] = Field(default_factory=list)
    instructions: str = ''
    parent_id: str | None = None


class RelationInput(BaseModel):
    left_id: str
    right_id: str
    kind: str
    note: str


class MappingReviewInput(BaseModel):
    status: str
    notes: str
    citations: list[dict] = Field(default_factory=list)


def create_app(settings=None, provider=None):
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir)
    archive = Archive(settings.data_dir)
    reconstruction = Reconstruction(archive)
    preview_lock = threading.Lock()
    provider = provider or Featherless(settings)

    @asynccontextmanager
    async def lifespan(app):
        # Recovery is only safe with a single server process owning this runtime DB.
        with (settings.data_dir / 'runtime.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('This runtime database is already open by another server. Use one worker.') from None
            store.recover()
            archive.start()
            try:
                yield
            finally:
                await asyncio.to_thread(archive.close)
                fcntl.flock(lock, fcntl.LOCK_UN)

    app = FastAPI(title='Ezra environment', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.archive = archive
    app.state.reconstruction = reconstruction

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    async def authorize(request: Request):
        if settings.access_token:
            actual = request.headers.get('authorization', '').encode()
            expected = ('Bearer ' + settings.access_token).encode()
            if not hmac.compare_digest(actual, expected):
                raise HTTPException(401, 'Enter the application access token to connect.')
        else:
            # Without a configured token, only the direct loopback UI may use the API.
            # Host and Origin checks also prevent a remote page from using localhost APIs.
            hostname = request.url.hostname
            peer = request.client.host if request.client else ''
            if hostname not in ('localhost', '127.0.0.1', '::1', 'testserver') or peer not in ('127.0.0.1', '::1', 'testclient'):
                raise HTTPException(403, 'Remote access requires EZRA_ACCESS_TOKEN on the server.')
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Cross-origin API access is disabled.')

    @app.exception_handler(Missing)
    async def missing_handler(request, exc):
        return JSONResponse(status_code=404, content={'detail': str(exc)})

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={'detail': str(exc)})

    protected = [Depends(authorize)]

    @app.exception_handler(ValueError)
    async def value_handler(request, exc):
        return JSONResponse(status_code=422, content={'detail': str(exc)})

    @app.get('/api/status', dependencies=protected)
    async def status():
        active = reconstruction.active()
        return {'phase': 3, 'provider': 'Featherless', 'model': settings.model or None,
                'inference_configured': bool(settings.api_key and settings.model),
                'authentication_enabled': bool(settings.access_token),
                'context_characters': settings.context_characters,
                'persona_status': 'Activated: ' + active['title'] if active else 'Archive persona not yet activated',
                'persona_revision_id': active['id'] if active else None,
                'tools_connected': False}

    @app.post('/api/reconstruction/bootstrap', dependencies=protected)
    async def reconstruction_bootstrap():
        return await asyncio.to_thread(reconstruction.bootstrap)

    @app.get('/api/reconstruction/records', dependencies=protected)
    async def reconstruction_records(kind: str | None = None, q: str = '', offset: int = Query(0, ge=0), limit: int = Query(40, ge=1, le=100)):
        return await asyncio.to_thread(reconstruction.records, kind, q, offset, limit)

    @app.post('/api/reconstruction/records', dependencies=protected, status_code=201)
    async def reconstruction_create(body: RecordInput):
        return await asyncio.to_thread(reconstruction.create_record, body.body)

    @app.get('/api/reconstruction/records/{identifier}', dependencies=protected)
    async def reconstruction_record(identifier: UUID):
        return await asyncio.to_thread(reconstruction.record, str(identifier))

    @app.put('/api/reconstruction/records/{identifier}', dependencies=protected)
    async def reconstruction_revise(identifier: UUID, body: RecordInput):
        return await asyncio.to_thread(reconstruction.revise, str(identifier), body.body, body.expected_revision)

    @app.post('/api/reconstruction/relations', dependencies=protected, status_code=201)
    async def reconstruction_relation(body: RelationInput):
        return await asyncio.to_thread(reconstruction.relate, body.left_id, body.right_id, body.kind, body.note)

    @app.get('/api/reconstruction/reconciliation', dependencies=protected)
    async def reconciliation_report(report_id: str | None = None):
        return await asyncio.to_thread(reconstruction.report, report_id)

    @app.post('/api/reconstruction/reconciliation', dependencies=protected)
    async def reconciliation_run():
        return await asyncio.to_thread(reconstruction.reconcile)

    @app.post('/api/reconstruction/reconciliation/{report_id}/{ledger_id}/reviews', dependencies=protected)
    async def reconciliation_review(report_id: UUID, ledger_id: str, body: MappingReviewInput):
        return await asyncio.to_thread(reconstruction.review_mapping, str(report_id), ledger_id, body.status, body.notes, body.citations)

    @app.get('/api/personas', dependencies=protected)
    async def persona_list():
        return await asyncio.to_thread(reconstruction.personas)

    @app.post('/api/personas', dependencies=protected, status_code=201)
    async def persona_create(body: PersonaInput):
        return await asyncio.to_thread(reconstruction.create_persona, body.title, body.revisions, body.instructions, 'owner', body.parent_id)

    @app.get('/api/personas/{identifier}', dependencies=protected)
    async def persona_detail(identifier: UUID):
        return await asyncio.to_thread(reconstruction.persona, str(identifier))

    @app.post('/api/personas/{identifier}/activate', dependencies=protected)
    async def persona_activate(identifier: UUID):
        return await asyncio.to_thread(reconstruction.activate, str(identifier), settings.context_characters)

    @app.post('/api/personas/deactivate', dependencies=protected)
    async def persona_deactivate():
        return await asyncio.to_thread(reconstruction.deactivate)

    @app.get('/api/archive/sources', dependencies=protected)
    async def archive_sources():
        return await asyncio.to_thread(archive.catalog)

    @app.get('/api/archive/inventory', dependencies=protected)
    async def archive_inventory():
        return await asyncio.to_thread(archive.inventory)

    @app.post('/api/archive/uploads', dependencies=protected, status_code=202)
    async def archive_upload(file: UploadFile = File(...)):
        try:
            return await asyncio.to_thread(archive.stage, file.filename or '', file.file)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        finally:
            await file.close()

    @app.post('/api/archive/restore', dependencies=protected)
    async def archive_restore(file: UploadFile = File(...)):
        try:
            return await asyncio.to_thread(archive.restore, file.file)
        except (ValueError, sqlite3.DatabaseError, zipfile.BadZipFile, KeyError) as exc:
            # Malformed backups are not application instructions and never execute.
            raise HTTPException(422, 'Backup could not be restored: ' + str(exc)[:300]) from None
        finally:
            await file.close()

    @app.get('/api/archive/sources/{sha}', dependencies=protected)
    async def archive_detail(sha: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), run: str | None = None):
        return await asyncio.to_thread(archive.detail, sha, offset, limit, run)

    @app.post('/api/archive/sources/{sha}/reprocess', dependencies=protected, status_code=202)
    async def archive_reprocess(sha: str):
        return await asyncio.to_thread(archive.reprocess, sha)

    @app.get('/api/archive/sources/{sha}/original', dependencies=protected)
    async def archive_original(sha: str):
        source, path = archive.original(sha)
        return FileResponse(path, filename=source['filename'], media_type='application/octet-stream', content_disposition_type='attachment')

    def preview_image(sha, page):
        from PIL import Image, ImageOps
        source, path = archive.original(sha)
        suffix = Path(source['filename']).suffix.lower()
        if suffix == '.pdf':
            import pypdfium2
            with pypdfium2.PdfDocument(str(path)) as pdf:
                if page > len(pdf):
                    raise Missing('PDF page not found.')
                raster_page = pdf[page - 1]
                # Bound preview dimensions while preserving the original file separately.
                width, height = raster_page.get_size()
                scale = min(1.5, 1800 / max(width, height))
                bitmap = raster_page.render(scale=scale)
                image = bitmap.to_pil()
                try:
                    output = io.BytesIO()
                    image.save(output, format='PNG')
                finally:
                    image.close()
                    bitmap.close()
                    raster_page.close()
                return output.getvalue()
        if suffix not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.tif', '.tiff', '.bmp'):
            raise HTTPException(422, 'Visual previews are available for PDF pages and images. Download other originals to open them in their native application.')
        with Image.open(path) as source_image:
            image = ImageOps.exif_transpose(source_image).convert('RGB')
            try:
                image.thumbnail((1800, 1800))
                output = io.BytesIO()
                image.save(output, format='PNG')
                return output.getvalue()
            finally:
                image.close()

    @app.get('/api/archive/sources/{sha}/preview', dependencies=protected)
    async def archive_preview(sha: str, page: int = Query(1, ge=1)):
        try:
            # PDFium is not thread-safe; serialize rendering inside this process.
            def render():
                with preview_lock:
                    return preview_image(sha, page)
            content = await asyncio.to_thread(render)
            return Response(content=content, media_type='image/png')
        except (Missing, HTTPException):
            raise
        except Exception:
            raise HTTPException(422, 'Preview could not be rendered. Download the preserved original instead.') from None

    @app.get('/api/archive/export', dependencies=protected)
    async def archive_export():
        try:
            path = await asyncio.to_thread(archive.export)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return FileResponse(path, filename='ezra-archive.zip', media_type='application/zip',
                            background=BackgroundTask(path.unlink, missing_ok=True))

    @app.get('/api/conversations', dependencies=protected)
    async def conversations():
        return store.list_conversations()

    @app.post('/api/conversations', dependencies=protected, status_code=201)
    async def create_conversation(body: ConversationInput):
        if not body.title.strip():
            raise HTTPException(422, 'A conversation title cannot be blank.')
        return store.create_conversation(body.title)

    @app.get('/api/conversations/{conversation_id}', dependencies=protected)
    async def conversation(conversation_id: UUID):
        return store.detail(str(conversation_id))

    @app.put('/api/conversations/{conversation_id}/continuity', dependencies=protected)
    async def update_continuity(conversation_id: UUID, body: NoteInput):
        return store.note(str(conversation_id), body.content)

    async def generate(turn):
        try:
            detail = store.detail(turn['conversation_id'])
            persona = reconstruction.active()
            messages, metadata = assemble_context(detail, turn['id'], settings.context_characters, persona)
            store.record_context(turn, settings.model, metadata)
            content, usage = await provider.complete(messages)
            store.complete(turn, content, settings.model, usage)
        except ProviderError as exc:
            store.fail(turn, str(exc))
        except asyncio.CancelledError:
            store.fail(turn, 'The request was interrupted. Retry the saved turn explicitly.')
            raise
        except Exception:
            # Preserve the user's message without exposing response bodies or secrets.
            store.fail(turn, 'The generation could not be completed. Your message is saved; retry explicitly.')
        return store.detail(turn['conversation_id'])

    @app.post('/api/conversations/{conversation_id}/turns', dependencies=protected)
    async def send(conversation_id: UUID, body: TurnInput):
        if not body.content.strip():
            raise HTTPException(422, 'A message cannot be blank.')
        turn, claimed = store.claim(str(conversation_id), str(body.request_id), body.content)
        return await generate(turn) if claimed else store.detail(str(conversation_id))

    @app.post('/api/conversations/{conversation_id}/turns/{turn_id}/retry', dependencies=protected)
    async def retry(conversation_id: UUID, turn_id: UUID):
        turn = store.retry(str(conversation_id), str(turn_id))
        return await generate(turn)

    static = Path(__file__).resolve().parent / 'static'
    app.mount('/', StaticFiles(directory=static, html=True), name='interface')
    return app
