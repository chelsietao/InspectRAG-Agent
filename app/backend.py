"""Local single-process API, with persistent jobs and bounded execution."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import fcntl
import hashlib
import io
import json
import re
from pathlib import Path
import threading
import warnings

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from PIL import Image, UnidentifiedImageError

from app.case_store import Store, identifier
from app.groq_provider import ProviderError

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD = 10 * 1024 * 1024
MAX_PIXELS = 16_000_000


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class NewCase(Payload):
    title: str = Field(min_length=1, max_length=120)

    @field_validator('title')
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError('blank_title')
        return value.strip()


class NewRun(Payload):
    kind: str = Field(pattern='^(analysis|references|agent)$')
    question: str = Field(default='', max_length=2000)
    image_id: str | None = Field(default=None, pattern='^[a-f0-9]{32}$')
    request_key: str = Field(min_length=1, max_length=80, pattern='^[A-Za-z0-9_-]+$')


class NewReport(Payload):
    run_id: str = Field(pattern='^[a-f0-9]{32}$')


class Confirmation(Payload):
    accepted: bool


def execute_run(root, directory, run, image):
    """Use existing local tools and Groq adapter, without retries or paid fallback."""
    from app.inspection_tools import LocalTools
    from app.agent_runtime import AgentRunner
    from app.groq_provider import GroqProvider, load_config
    tools = provider = None
    try:
        tools = LocalTools(root, directory, image)
        if run['kind'] == 'references':
            result = tools.execute('search_reference_images', {'k': 3})
            return {**result, 'evidence': tools.evidence}
        if run['kind'] == 'analysis':
            result = tools.execute('analyze_image', {'image_id': 'selected-image'})
            return {**result, 'evidence': tools.evidence}
        config = load_config(root)
        provider = GroqProvider(root, config)
        prompt = (root / 'prompts' / (config['prompt_version'].replace('-', '_') + '.txt')).read_text()
        return AgentRunner(provider, tools, config, prompt).run(run['question'], bool(image))
    finally:
        if tools:
            tools.close()
        if provider:
            provider.close()


def create_app(data_dir=None, executor_fn=execute_run):
    data = Path(data_dir or ROOT / 'artifacts/backend').resolve()
    # LocalTools writes artifact links relative to ROOT, keep all storage in artifacts.
    if not data.is_relative_to(ROOT / 'artifacts'):
        raise ValueError('storage_must_be_under_project_artifacts')
    store = Store(data / 'inspectrag.sqlite3')
    (data / 'images').mkdir(exist_ok=True)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='inspection')
    slots = threading.BoundedSemaphore(4)

    def work(run):
        try:
            store.update_run(run['id'], 'running')
            image = data / 'images' / (run['image_id'] + '.png') if run['image_id'] else None
            result = executor_fn(ROOT, data / 'runs' / run['id'], run, image)
            if result.get('status') in ('answered', 'insufficient_evidence', 'needs_context', 'ok'):
                store.update_run(run['id'], 'succeeded', result)
            else:
                store.update_run(run['id'], 'failed', result, result.get('error') or 'run_stopped')
        except ProviderError as exc:
            store.update_run(run['id'], 'failed', error=exc.code)
        except Exception:
            # Never serialize raw exception strings, which could contain credentials or local paths.
            store.update_run(run['id'], 'failed', error='execution_failed')
        finally:
            slots.release()

    @asynccontextmanager
    async def lifespan(api):
        lock = (data / 'server.lock').open('a')
        try:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('database_already_in_use_by_another_server') from None
            api.state.recovered_jobs = store.recover()
            try:
                yield
            finally:
                pool.shutdown(wait=True, cancel_futures=False)
        finally:
            lock.close()

    api = FastAPI(title='InspectRAG local API', version='0.6.0', lifespan=lifespan)
    api.state.store = store
    api.state.data_dir = data

    @api.middleware('http')
    async def local_only(request: Request, call_next):
        # Host allowlist + browser Origin rejection, this service has no public authentication.
        host = request.url.hostname
        if host not in ('127.0.0.1', 'localhost', 'testserver'):
            return JSONResponse(status_code=403, content={'detail': 'local_host_required'})
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse(status_code=403, content={'detail': 'origin_not_allowed'})
        return await call_next(request)

    @api.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse(status_code=404, content={'detail': 'not_found'})

    @api.get('/', include_in_schema=False)
    def dashboard():
        return FileResponse(ROOT / 'web/index.html', media_type='text/html',
                            headers={'Cache-Control': 'no-store'})

    @api.get('/assets/{name}', include_in_schema=False)
    def web_asset(name: str):
        allowed = {'app.css': 'text/css', 'app.js': 'text/javascript',
                   'ui-core.mjs': 'text/javascript'}
        if name not in allowed:
            raise HTTPException(404, 'not_found')
        return FileResponse(ROOT / 'web' / name, media_type=allowed[name],
                            headers={'Cache-Control': 'no-cache'})

    @api.get('/demo/bottle.png', include_in_schema=False)
    def sample_image():
        path = ROOT / 'bottle/test/broken_large/000.png'
        if not path.is_file():
            raise HTTPException(404, 'sample_data_not_installed')
        return FileResponse(path, media_type='image/png')

    @api.get('/health')
    def health():
        with store.connection() as db:
            db.execute('SELECT 1').fetchone()
        return {'status': 'ok', 'database_schema': 1, 'scope': 'local_single_user',
                'llm_online_checked': False, 'recovered_jobs': getattr(api.state, 'recovered_jobs', 0)}

    @api.post('/cases', status_code=201)
    def new_case(body: NewCase):
        return store.create_case(body.title)

    @api.get('/cases')
    def cases():
        return {'items': store.list('cases')}

    @api.get('/cases/{case_id}')
    def case(case_id: str):
        return store.get('cases', case_id)

    @api.post('/cases/{case_id}/images', status_code=201)
    async def upload(case_id: str, file: UploadFile):
        store.get('cases', case_id)
        try:
            raw = await file.read(MAX_UPLOAD + 1)
            if len(raw) > MAX_UPLOAD:
                raise HTTPException(413, 'image_too_large')
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as source:
                    if source.format not in ('PNG', 'JPEG'):
                        raise HTTPException(415, 'png_or_jpeg_required')
                    if source.width * source.height > MAX_PIXELS:
                        raise HTTPException(413, 'image_dimensions_too_large')
                    if getattr(source, 'n_frames', 1) != 1:
                        raise HTTPException(415, 'single_frame_required')
                    image = source.convert('RGB')
                    image.load()
            encoded = io.BytesIO()
            image.save(encoded, format='PNG')
            content, image_id = encoded.getvalue(), identifier()
            destination = data / 'images' / (image_id + '.png')
            destination.write_bytes(content)
            try:
                return store.add_image(case_id, image_id, hashlib.sha256(content).hexdigest(),
                                       image.width, image.height)
            except Exception:
                destination.unlink(missing_ok=True)
                raise
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
                Image.DecompressionBombWarning):
            raise HTTPException(415, 'invalid_image') from None
        finally:
            await file.close()

    @api.get('/cases/{case_id}/images')
    def images(case_id: str):
        store.get('cases', case_id)
        return {'items': store.list('images', case_id)}

    @api.get('/cases/{case_id}/images/{image_id}')
    def image_file(case_id: str, image_id: str):
        store.get('images', image_id, case_id)
        return FileResponse(data / 'images' / (image_id + '.png'), media_type='image/png')

    @api.post('/cases/{case_id}/runs', status_code=202)
    def submit(case_id: str, body: NewRun):
        store.get('cases', case_id)
        if body.image_id:
            store.get('images', body.image_id, case_id)
        if body.kind in ('analysis', 'references') and not body.image_id:
            raise HTTPException(422, body.kind + '_requires_image')
        if body.kind == 'agent' and not body.question.strip():
            raise HTTPException(422, 'agent_requires_question')
        fingerprint = hashlib.sha256(json.dumps(body.model_dump(exclude={'request_key'}),
                                                sort_keys=True).encode()).hexdigest()
        # Reserve capacity before writing a pending job, prevent abandoned pending rows.
        if not slots.acquire(blocking=False):
            # Existing identical requests remain readable even when capacity is full.
            for existing in store.list('runs', case_id):
                if existing['request_key'] == body.request_key:
                    try:
                        run, _ = store.submit(case_id, body.image_id, body.kind, body.question,
                                              body.request_key, fingerprint)
                    except ValueError:
                        raise HTTPException(409, 'idempotency_conflict') from None
                    return run
            raise HTTPException(429, 'local_queue_full')
        try:
            run, created = store.submit(case_id, body.image_id, body.kind, body.question,
                                        body.request_key, fingerprint)
        except ValueError:
            slots.release()
            raise HTTPException(409, 'idempotency_conflict') from None
        except Exception:
            slots.release()
            raise
        if created:
            try:
                pool.submit(work, run)
            except RuntimeError:
                slots.release()
                store.update_run(run['id'], 'failed', error='server_stopping')
                raise HTTPException(503, 'server_stopping') from None
        else:
            slots.release()
        return run

    @api.get('/cases/{case_id}/runs')
    def runs(case_id: str):
        store.get('cases', case_id)
        return {'items': store.list('runs', case_id),
                'memory_policy': 'saved_history_only_not_injected_into_agent_context'}

    @api.get('/cases/{case_id}/runs/{run_id}')
    def run(case_id: str, run_id: str):
        return store.get('runs', run_id, case_id)

    @api.get('/cases/{case_id}/runs/{run_id}/heatmap')
    def heatmap(case_id: str, run_id: str):
        store.get('runs', run_id, case_id)
        path = data / 'runs' / run_id / 'analysis/heatmap.png'
        if not path.is_file():
            raise HTTPException(404, 'heatmap_not_available')
        return FileResponse(path, media_type='image/png')

    @api.get('/cases/{case_id}/runs/{run_id}/references/{index}')
    def reference_file(case_id: str, run_id: str, index: int):
        run = store.get('runs', run_id, case_id)
        result = run.get('result') or {}
        evidence = list((result.get('evidence') or {}).values()) + result.get('citations', [])
        matches = next((item.get('matches', []) for item in evidence
                        if item.get('kind') == 'image_references'), [])
        if index < 0 or index >= min(len(matches), 3):
            raise HTTPException(404, 'reference_not_available')
        row = matches[index]
        relative = row.get('path', '')
        digest = row.get('sha256', '')
        if not re.fullmatch(r'train/good/[0-9]{3}\.png', relative):
            raise HTTPException(404, 'reference_not_available')
        path = ROOT / 'bottle' / relative
        if (not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to((ROOT / 'bottle/train/good').resolve())):
            raise HTTPException(404, 'reference_not_available')
        if not re.fullmatch(r'[a-f0-9]{64}', digest) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise HTTPException(409, 'reference_source_changed')
        return FileResponse(path, media_type='image/png')

    @api.post('/cases/{case_id}/reports', status_code=201)
    def draft(case_id: str, body: NewReport):
        store.get('cases', case_id)
        try:
            return store.draft(case_id, body.run_id)
        except ValueError:
            raise HTTPException(409, 'answered_run_required') from None

    @api.get('/cases/{case_id}/reports')
    def reports(case_id: str):
        store.get('cases', case_id)
        return {'items': store.list('reports', case_id)}

    @api.get('/cases/{case_id}/reports/{report_id}')
    def report(case_id: str, report_id: str):
        return store.get('reports', report_id, case_id)

    @api.post('/cases/{case_id}/reports/{report_id}/confirm')
    def confirm(case_id: str, report_id: str, body: Confirmation):
        if not body.accepted:
            raise HTTPException(422, 'explicit_acceptance_required')
        return store.confirm(case_id, report_id)

    return api
