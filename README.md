# tender-digest

Сервис принимает PDF тендерной документации и возвращает выжимку: цену контракта, сроки, требования к исполнителю и штрафы.

Разбор логики и алгоритма: [SOLUTION.md](SOLUTION.md).

## Запуск

```bash
pip install -r requirements.txt
cp .env.example .env        # вписать ключ и адрес модели
uvicorn app.main:app --reload
```

Проверка:

```bash
curl -F "file=@izveshchenie.pdf" http://127.0.0.1:8000/digest
```

Ответ:

```json
{
  "digest": {
    "contract_amount": "1250000.50",
    "currency": "RUB",
    "deadline_start": "2026-03-01",
    "deadline_end": "2026-06-30",
    "deadline_text": "в течение 120 календарных дней с даты заключения контракта",
    "requirements": ["членство в СРО", "опыт аналогичных работ от 2 лет"],
    "penalties": [
      {"reason": "просрочка исполнения", "amount": null, "formula": "1/300 ключевой ставки за каждый день"}
    ],
    "warnings": ["документ обрезан до 60000 знаков, выжимка построена по началу"]
  },
  "pages": 42,
  "characters": 60000,
  "truncated": true,
  "cached": false,
  "model": "gpt-4o-mini",
  "usage": {"prompt_tokens": 15200, "completion_tokens": 480, "cost_rub": "0.9312"}
}
```

## Настройки

| Переменная | Зачем | По умолчанию |
|---|---|---|
| `LLM_BASE_URL` | адрес OpenAI-совместимого API | `https://api.openai.com/v1` |
| `LLM_MODEL` | имя модели | `gpt-4o-mini` |
| `LLM_API_KEY` | ключ | обязательна |
| `LLM_PRICE_IN_RUB` | цена за миллион входных токенов, рубли | `0` |
| `LLM_PRICE_OUT_RUB` | цена за миллион выходных токенов, рубли | `0` |
| `MAX_UPLOAD_BYTES` | предел размера файла | 20 МБ |
| `MAX_DOC_CHARS` | сколько знаков уходит в модель | 60000 |
| `CACHE_SIZE` | сколько разобранных документов помнить | 64 |

Адрес API вынесен в настройку, поэтому сервис работает с OpenAI, с российскими шлюзами и с локальной моделью через Ollama (`http://localhost:11434/v1`) без правок кода.

## Тесты

```bash
python -m pytest tests/ -q
```

22 теста: разбор денег и дат в русских формулировках, извлечение текста, распознавание скана без текстового слоя, гашение инструкций внутри документа, кеш по хешу файла.

## Лицензия

MIT, файл [LICENSE](LICENSE).
