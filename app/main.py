from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .config import DEFAULT_MODEL, DEFAULT_PROVIDER, MAX_FILE_BYTES, MAX_PAGES, PROVIDERS, ROOT, server_key
from .extraction import ExtractionError, extract
from .readers import DocumentError, FORMATS, prepare_document

app = FastAPI(title='Accord · Document extraction', version='1.0.0')
app.mount('/static', StaticFiles(directory=ROOT / 'app' / 'static'), name='static')


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(ROOT / 'app' / 'static' / 'index.html')


@app.get('/api/config')
def config():
    return {'configured': bool(server_key()), 'model': DEFAULT_MODEL, 'provider': DEFAULT_PROVIDER,
            'providers': {key: {'label': value['label'], 'model': value['model'], 'configured': bool(server_key(key))} for key, value in PROVIDERS.items()}, 'formats': FORMATS,
            'max_file_mb': MAX_FILE_BYTES // (1024 * 1024), 'max_pages': MAX_PAGES}


async def read_upload(file: UploadFile):
    try:
        data = await file.read(MAX_FILE_BYTES + 1)
        return await run_in_threadpool(prepare_document, file.filename or 'document', data)
    except DocumentError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()


@app.post('/api/preview')
async def preview(file: Annotated[UploadFile, File()]):
    doc = await read_upload(file)
    return {'name': doc.name, 'format': doc.format, 'text': doc.text, 'images': doc.images,
            'units': doc.units, 'warnings': doc.warnings}


@app.post('/api/extract')
async def extract_document(
    file: Annotated[UploadFile, File()],
    model: Annotated[str, Form(max_length=100)] = '',
    provider: Annotated[Literal['openai', 'groq'], Form()] = DEFAULT_PROVIDER,
    x_api_key: Annotated[str | None, Header()] = None,
):
    key = (x_api_key or server_key(provider)).strip()
    if not key:
        await file.close()
        raise HTTPException(503, f'Add your {PROVIDERS[provider]["label"]} API key in Settings to enable extraction. Document preview works without a key.')
    model = model.strip() or PROVIDERS[provider]['model']
    doc = await read_upload(file)
    try:
        result = await run_in_threadpool(extract, doc, key, model, provider)
    except ExtractionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {'filename': doc.name, 'provider': provider, 'model': model, 'result': result.model_dump()}
