"""Схема выжимки из тендерного документа и разбор денег и дат из свободного текста."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field, field_validator

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def parse_money(raw: str | int | float | Decimal | None) -> Decimal | None:
    """Сумма контракта приходит от модели строкой в любом виде: 1 250 000,50 руб., 1250000.5, 1,25 млн.

    Разряды в русских документах разделяются пробелом (в том числе неразрывным), а дробная
    часть запятой, поэтому обычный Decimal(raw) на таких строках падает.
    """
    if raw is None or isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))

    text = raw.replace(" ", " ").replace(" ", " ").strip().lower()
    if not text:
        return None

    multiplier = Decimal(1)
    if re.search(r"\bмлрд\b|\bмиллиард", text):
        multiplier = Decimal(1_000_000_000)
    elif re.search(r"\bмлн\b|\bмиллион", text):
        multiplier = Decimal(1_000_000)
    elif re.search(r"\bтыс\b|\bтысяч", text):
        multiplier = Decimal(1_000)

    digits = re.sub(r"[^\d,.\s]", " ", text)
    digits = re.sub(r"(?<=\d)[\s](?=\d{3}\b)", "", digits)
    # После чистки в строке остаётся мусор от «руб.» и «млн», поэтому берём первое число целиком.
    match = re.search(r"\d+(?:[.,]\d+)*", digits)
    if not match:
        return None
    number = match.group(0)
    if "," in number and "." in number:
        number = number.replace(".", "") if number.rfind(",") > number.rfind(".") else number.replace(",", "")
    number = number.replace(",", ".")
    if number.count(".") > 1:
        head, _, tail = number.rpartition(".")
        number = head.replace(".", "") + "." + tail
    try:
        return (Decimal(number) * multiplier).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def parse_date(raw: str | date | None) -> date | None:
    """Даты в извещениях пишут и как 01.03.2026, и как 2026-03-01, и как «1 марта 2026 г.»."""
    if raw is None or isinstance(raw, date):
        return raw
    text = str(raw).strip().lower().replace("г.", "").strip()
    if not text:
        return None

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", text)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    m = re.search(r"(\d{1,2})\s+([а-я]+)\s+(\d{4})", text)
    if m and m[2] in MONTHS:
        return date(int(m[3]), MONTHS[m[2]], int(m[1]))
    return None


class Penalty(BaseModel):
    """Штраф из проекта контракта."""

    reason: str = Field(description="За что штраф")
    amount: Decimal | None = Field(default=None, description="Сумма в рублях, если названа")
    formula: str | None = Field(default=None, description="Формула или процент, если сумма не фиксированная")

    @field_validator("amount", mode="before")
    @classmethod
    def _money(cls, v):
        return parse_money(v)


class Digest(BaseModel):
    """Выжимка, которую возвращает сервис. Пустые поля допустимы: в документе может не быть цены."""

    contract_amount: Decimal | None = Field(default=None, description="Начальная цена контракта, рубли")
    currency: str = Field(default="RUB")
    deadline_start: date | None = None
    deadline_end: date | None = None
    deadline_text: str | None = Field(default=None, description="Срок словами, как в документе")
    requirements: list[str] = Field(default_factory=list, description="Требования к исполнителю")
    penalties: list[Penalty] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="Что сервис не смог подтвердить")

    @field_validator("contract_amount", mode="before")
    @classmethod
    def _money(cls, v):
        return parse_money(v)

    @field_validator("deadline_start", "deadline_end", mode="before")
    @classmethod
    def _date(cls, v):
        return parse_date(v)

    @field_validator("requirements", mode="before")
    @classmethod
    def _requirements(cls, v):
        if isinstance(v, str):
            return [line.strip(" -•\t") for line in v.splitlines() if line.strip()]
        return v


class DigestResponse(BaseModel):
    digest: Digest
    pages: int
    characters: int
    truncated: bool = Field(description="Текст обрезан до лимита, выжимка построена по началу документа")
    cached: bool = Field(description="Ответ взят из кеша по хешу файла, обращения к модели не было")
    model: str
    usage: dict = Field(default_factory=dict, description="Токены и стоимость запроса")
