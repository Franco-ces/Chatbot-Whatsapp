# Agent Instructions — Chatbot WhatsApp

## Architecture

FastAPI monolith with webhook-based architecture. Inbound messages flow:

```
Evolution API → POST /webhook → payload_parser → bot_service → RAGLangchain → WhatsAppClient
```

**Key constraint: All new code MUST be modular.** No new files in `src/` root unless justified.

## Entry Points

| File | Purpose | Run |
|------|---------|-----|
| `src/main.py` | Webhook server (port 5000) | `uvicorn main:app --host 0.0.0.0 --port 5000 --reload` |
| `src/interface.py` | Admin UI (port 8000) | `python interface.py` |

## Commands

```bash
# Tests (from chatbotW/)
pytest                          # All tests
pytest tests/test_bot_service.py  # Single file
pytest -k "test_name"           # Single test

# Lint (not configured — recommend adding ruff)
```

## Dependencies

- **Runtime**: `.env` with `GOOGLE_API_KEY`, `EVOLUTION_API_KEY`, `EVOLUTION_API_URL`, `EVOLUTION_INSTANCE_NAME`
- **Docker**: `docker compose up -d --build` from `chatbotW/`
- **Ports**: Bot=5000, Admin=8000, Evolution API=8080

## Code Patterns

### Error Handling (CRITICAL)

Use `ErrorCode` enum + `AppError` hierarchy. NEVER raise raw exceptions:

```python
from exceptions import AppError, CommunicationError
from error_codes import ErrorCode

# Bad
raise ValueError("Invalid config")

# Good
raise AppError(ErrorCode.CFG_READ_FAILED, detail=str(e))
```

### Logging

Use `structlog` via `logging_config.get_logger()`. NEVER use `print()` or stdlib `logging`:

```python
from logging_config import get_logger
logger = get_logger("module_name")
logger.info("Event", key=value)
```

### HTTP Client

Use `httpx_idle_client.IdleTimeoutClient()` for all outbound HTTP. NEVER use raw `httpx`:

```python
from httpx_idle_client import IdleTimeoutClient
client = IdleTimeoutClient()
response = await client.request("POST", url, json=payload, headers=headers)
```

### Async Boundaries

- `asyncio.to_thread()` for blocking I/O (file reads, FAISS operations)
- `asyncio.create_task()` for fire-and-forget (webhook processing)

## Testing

- **Framework**: pytest + pytest-asyncio (auto mode)
- **Mocking**: pytest-mock
- **Pattern**: Unit tests mock external services (Evolution API, Gemini)
- **conftest.py**: Adds `src/` to sys.path

## Modular Structure

When adding new functionality:
1. Create module in `src/` with clear responsibility
2. Import via `from module_name import Class`
3. Register in `main.py` lifespan if it has startup/shutdown
4. Add error codes to `ErrorCode` enum
5. Add tests in `tests/test_module_name.py`

## Gotchas

- `vectorstore/` and `cache/` are rebuildable — gitignore them
- FAISS loads with `allow_dangerous_deserialization=True` (safe for local use)
- Evolution API webhook retries if no 200 in time → deduplication via `mensajes_procesados`
- `config_bot.json` is hot-reloaded each request via `ConfigManager.cargar()`
- Rate limit: 5 messages/60s per user (in-memory, not persistent)
