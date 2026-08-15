"""HTTP-сервис: принимает PDF тендерной документации, отдаёт выжимку по контракту."""
from __future__ import annotations

import hashlib
import os
from collections import OrderedDict

from fastapi import FastAPI, File, HTTPException, UploadFile

from .llm import LlmError, summarize
from .models import DigestResponse
from .pdf import PdfError, defang, extract_text, looks_scanned

MAX_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 20 * 1024 * 1024))
MAX_CHARS = int(os.getenv("MAX_DOC_CHARS", 60_000))
CACHE_SIZE = int(os.getenv("CACHE_SIZE", 64))

app = FastAPI(title="tender-digest", version="1.0.0")

# ponytail: кеш в памяти процесса, одного инстанса хватает. При нескольких воркерах нужен Redis.
_cache: OrderedDict[str, DigestResponse] = OrderedDict()


def _cached(key: str) -> DigestResponse | None:
    hit = _cache.get(key)
    if hit is not None:
        _cache.move_to_end(key)
    return hit


def _remember(key: str, value: DigestResponse) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "cached_documents": len(_cache)}


async def _read_limited(file: UploadFile) -> bytes:
    """Читает загрузку порциями и обрывает на первом байте сверх лимита.

    Целиком через file.read() нельзя: тогда лимит проверяется уже после того, как
    присланный файл занял память, и один запрос кладёт процесс.
    """
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, f"файл больше {MAX_BYTES} байт")
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/digest", response_model=DigestResponse)
async def digest(file: UploadFile = File(...)) -> DigestResponse:
    data = await _read_limited(file)
    if not data:
        raise HTTPException(400, "пустой файл")

    # Один и тот же документ присылают по несколько раз, и каждый разбор стоит денег.
    key = hashlib.sha256(data).hexdigest()
    hit = _cached(key)
    if hit is not None:
        return hit.model_copy(update={"cached": True})

    try:
        text, pages, truncated = extract_text(data, MAX_CHARS)
    except PdfError as exc:
        raise HTTPException(400, str(exc)) from exc

    if looks_scanned(text, pages):
        raise HTTPException(
            422,
            f"в PDF нет текстового слоя ({len(text)} знаков на {pages} страниц), "
            "нужен OCR: по такому файлу выжимка была бы выдумана",
        )

    text, warnings = defang(text)

    try:
        parsed, model, usage = summarize(text)
    except LlmError as exc:
        raise HTTPException(502, str(exc)) from exc

    if truncated:
        warnings.append(f"документ обрезан до {MAX_CHARS} знаков, выжимка построена по началу")
    parsed.warnings = [*parsed.warnings, *warnings]

    result = DigestResponse(
        digest=parsed,
        pages=pages,
        characters=len(text),
        truncated=truncated,
        cached=False,
        model=model,
        usage=usage,
    )
    _remember(key, result)
    return result
