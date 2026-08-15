"""Извлечение текста из PDF и подготовка его к отправке в модель."""
from __future__ import annotations

import io
import re

from pypdf import PdfReader

# Инструкция, спрятанная в теле документа, для модели выглядит так же, как инструкция от нас.
# Тендерную документацию присылает посторонний, поэтому такие места гасим до отправки.
INJECTION = re.compile(
    r"(игнорируй|забудь).{0,40}(инструкц|предыдущ|выше)"
    r"|ignore\s+(all\s+)?(previous|above)\s+instructions"
    r"|system\s*:|assistant\s*:"
    r"|ты\s+(теперь|больше не)\s+"
    r"|верни\s+.{0,30}(вместо|игнорир)",
    re.IGNORECASE | re.DOTALL,
)


class PdfError(ValueError):
    pass


def extract_text(data: bytes, max_chars: int) -> tuple[str, int, bool]:
    """Возвращает текст, число страниц и признак обрезки.

    Обрезка нужна не ради аккуратности, а ради денег: документация госзакупки бывает
    на сотни страниц, и целиком она стоит дороже, чем даёт пользы.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise PdfError(f"файл не читается как PDF: {exc}") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise PdfError("PDF закрыт паролем") from exc

    chunks: list[str] = []
    total = 0
    truncated = False
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = re.sub(r"[ \t]+", " ", text)
        if total + len(text) > max_chars:
            chunks.append(text[: max_chars - total])
            truncated = True
            break
        chunks.append(text)
        total += len(text)

    return "\n".join(chunks).strip(), len(reader.pages), truncated


def looks_scanned(text: str, pages: int) -> bool:
    """Скан без текстового слоя отдаёт почти пустой extract_text, и модель на нём выдумает выжимку."""
    return pages > 0 and len(text) / pages < 120


def defang(text: str) -> tuple[str, list[str]]:
    """Гасит найденные попытки перехвата инструкции и говорит, сколько их было."""
    found = INJECTION.findall(text)
    if not found:
        return text, []
    cleaned = INJECTION.sub("[фрагмент удалён сервисом]", text)
    return cleaned, [f"в документе найдено {len(found)} мест, похожих на попытку подменить инструкцию модели"]
