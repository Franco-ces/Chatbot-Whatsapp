# AGENTS.md — Chatbot WhatsApp (Gemini + RAG + Evolution API)

## Project Structure

```
Chatbot-Whatsapp/
├── chatbotW/                  # Main application directory
│   ├── src/                   # All Python source (flat module; importable as `python -m src` via namespace package)
│   ├── tests/                 # pytest tests (conftest adds src/ to sys.path)
│   ├── PDFs/                  # Uploaded PDFs for RAG (mounted in Docker)
│   ├── CSVs/                  # Price/stock database (precios.csv) for fuzzy price lookup
│   ├── vectorstore/           # FAISS index + metadata.json (auto-rebuilt on PDF change)
│   ├── cache/                 # Embedding cache (embeddings_cache.json)
│   ├── logs/                  # Chat session logs (chat_YYYY-MM-DD_HH-MM-SS.txt)
│   ├── config_bot.json        # Runtime config (local-only, gitignored) — edited by admin UI
│   ├── docker-compose.yml     # 5 services: bot, admin-ui, evolution-api, postgres, redis
│   ├── Dockerfile             # Python 3.12-slim, installs ffmpeg
│   └── requirements.txt       # Python deps (pinned versions for fastapi, uvicorn, pytest)
├── primera_instalacion.sh     # One-time setup: builds containers, creates Evolution instance
├── comandos.txt               # Docker commands reference
└── conectar.html              # QR scanner for WhatsApp linking
```

## Architecture

Two independent FastAPI apps plus a CLI entry point:
- **`src/main.py`** — Bot webhook server (port 5000). Receives WhatsApp messages via Evolution API webhook, processes through RAG pipeline, responds.
- **`src/interface.py`** — Admin web UI (port 8000). PDF upload/download, config editing, log viewer, report scheduling.
- **`src/__main__.py`** — Admin CLI (`python -m src <subcommand>`). Evolution instance management (list/create/qr/state/set-webhook/set-active). JSON to stdout, human messages to stderr, documented exit codes (0/1/2/3).

Module responsibilities (all under `chatbotW/src/`):
| Module | Role |
|---|---|
| **Core / Logic** | |
| `main.py` | FastAPI app, lifespan, rate limiting, webhook endpoint |
| `bot_service.py` | Orchestrates: audio download → RAG query → send response |
| `query_processor.py` | Core RAG: PDF retrieval, FAISS search, Gemini generation, guardrails |
| `document_manager.py` | Document loading, chunking, embedding pipeline |
| `rag_orchestrator.py` | Orchestrates retrieval + generation pipeline |
| `faq_matcher.py` | Semantic FAQ matching |
| `price_lookup.py` | Fuzzy CSV price/catalog search |
| `guardrails.py` | Input/output guardrail checks via Gemini |
| `context_builder.py` | Builds LangChain context for RAG queries |
| `cache.py` | In-memory cache utilities |
| `prompts.py` | LangChain prompt templates (RAG, guardrails) |
| **WhatsApp / Evolution API** | |
| `whatsapp_client.py` | HTTP client for Evolution API (send text, get audio) |
| `payload_parser.py` | Pydantic models for Evolution webhook, extracts clean data |
| `audio_handler.py` | Transcribes audio via Gemini |
| `evo_client.py` | Evolution API client (instances, webhooks) |
| `evolution_admin.py` | Evolution instance management |
| `evolution_http.py` | Low-level Evolution HTTP helpers |
| `evolution_models.py` | Pydantic models for Evolution API |
| `instance_activation.py` | WhatsApp instance activation logic |
| `instance_watcher.py` | Background instance state monitoring |
| **Infrastructure** | |
| `vectorstore_manager.py` | FAISS save/load, hash-based change detection |
| `embedding_cache.py` | JSON-backed cache to avoid redundant Gemini embedding calls |
| `ConfigManager.py` | Reads/writes `config_bot.json` (email, phone for support messages) |
| `error_codes.py` | `ErrorCode` enum (E-COM, E-RAG, E-CFG, E-API, E-SYS) |
| `exceptions.py` | `AppError` hierarchy (CommunicationError, RAGError, etc.) |
| `error_handler.py` | FastAPI exception handlers for all error types |
| `chat_logger.py` | Writes chat logs to `logs/` |
| `sesionLoggerManager.py` | Session tracking with timeout and context window |
| `health.py` | Health check endpoint logic |
| `httpx_idle_client.py` | HTTP client with connection pooling |
| `logging_config.py` | structlog configuration |
| `paths.py` | Centralized path constants |
| `faq_paths.py` | Centralized resolution of the `faqs.json` path (reads `FAQS_VOLUME_MOUNT`) |
| `telemetry.py` | Interaction telemetry persistence |
| `verificar_datos.py` | Data validation utilities |
| **Admin UI** | |
| `interface.py` | Admin web UI (FastAPI, port 8000) |
| `report_generator.py` | PDF report generation (WeasyPrint) |
| `report_scheduler.py` | Scheduled report generation and delivery |
| **Entry points** | |
| `__main__.py` | Package CLI entry point (`python -m src`) |

**Critical: `src/` is flat.** Imports are bare (`from bot_service import ...`), never package-style (`from src.bot_service import ...`). The test `conftest.py` adds `src/` to `sys.path`, and `__main__.py` inserts its own directory into `sys.path` (lines 41-43) so the CLI works both locally and in Docker. There is no `src/__init__.py` — `python -m src` and `import src.__main__` (used by `tests/test_cli.py`) work via Python 3 namespace packages (PEP 420). Do not re-add `__init__.py`.

## Commands

### Run locally (without Docker)
```bash
cd chatbotW
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Requires ffmpeg installed on host: sudo apt install ffmpeg
uvicorn src.main:app --host 0.0.0.0 --port 5000 --reload
```

### Run tests
```bash
cd chatbotW
pytest                    # all tests
pytest tests/test_bot_service.py  # single file
pytest -k "test_audio"    # by name pattern
```
Tests use `pytest-asyncio` with `asyncio_mode = "auto"` (from pyproject.toml). All tests are synchronous with mocks — no real API calls.

### Docker
```bash
cd chatbotW
docker compose up -d --build    # build and start all 5 services
docker compose down             # stop everything
docker logs gemini_whatsapp_bot -f  # follow bot logs
```

**First-time setup** requires running `primera_instalacion.sh` which builds containers, waits for Postgres/Redis, creates the Evolution API instance, and configures the webhook. You must scan a QR code manually during that process.

### Run the admin UI
```bash
cd chatbotW
uvicorn src.interface:app --host 127.0.0.1 --port 8000
```

## Gotchas

- **`src/` modules import each other as siblings** — never use `from src.module import ...`. This works because `main.py` runs with `working_dir: /app/src` in Docker, and tests use `sys.path.insert`.
- **FAISS vectorstore rebuilds automatically** when PDFs change (hash-based detection in `vectorstore_manager.py`). First query after adding/removing PDFs is slow — it processes all chunks via Gemini embeddings with `time.sleep(0.5)` per chunk to respect rate limits.
- **Two Gemini models are used**: `gemini-3.1-flash-lite` for generation AND guardrails (via LangChain) and direct SDK calls. Embeddings use `gemini-embedding-2-preview`.
- **Guardrails are double calls**: every user message triggers an input guardrail check, and every bot response triggers an output guardrail check. Each is a separate Gemini API call.
- **Rate limiting is in-memory only** (5 messages/60s per user). Resets on restart.
- **`config_bot.json` is mounted into Docker** — edits via the admin UI persist across container restarts.
- **`.env` contains API keys** — never commit. It's in `.gitignore` but exists in the repo root for local dev. Docker reads it via `env_file`.
- **Embedding cache (`cache/`) is critical** — without it, every restart re-embeds all PDF chunks (slow + hits rate limits). Cache is per-text-hash.
- **Audio processing is in-memory** — audio bytes are never written to disk. Transcription goes directly to Gemini via `Part.from_bytes`.
- **Log format is custom**: `id_usuario|||{id}|||{time}|||{message}` and `id_bot|||{id}|||{time}|||{message}` with `[BR]` as newline placeholder.

## Style Conventions

- **Modular by design**: each file = one concern. Follow this pattern when adding features.
- **Error handling**: use `ErrorCode` enum + `AppError` hierarchy. Never raise raw exceptions — wrap in the appropriate subclass.
- **All user-facing messages in Spanish** (prompts, error messages, log text).
- **Comments in Spanish** in source code.
- **Pydantic for webhook parsing** (`payload_parser.py`).
- **No type hints on most functions** — existing codebase doesn't use them consistently. Follow the pattern of the file you're editing.
- **Never commit or push without explicit authorization**: before running `git commit` or `git push`, ask the user. Even if the task is complete, let the user decide when and whether to commit and push. Never use `--no-verify` without asking. Never use `--force`, `--force-with-lease`, or any force push under any circumstance — if history needs rewriting, explain the situation and let the user decide.
- **Keep docs in sync**: when a code change introduces operator-facing functionality (new endpoints, auth flow changes, new admin panel features), the implementing agent should NOT update `DOCUMENTACION_TECNICA.md` inline. Instead, note what needs documenting and delegate a separate doc update to a fresh agent at the end. Code changes without doc updates create drift that hurts onboarding and troubleshooting.
- **PR descriptions** must end with a `## Reviewer notes` section containing at least one specific file path that was manually inspected during the change.

## Environment Variables

Required in `.env`:
```
GOOGLE_API_KEY=...          # Gemini API key
EVOLUTION_API_KEY=...       # Evolution API auth key
EVOLUTION_API_URL=...       # http://evolution-api:8080 (Docker) or http://localhost:8080 (local)
EVOLUTION_INSTANCE_NAME=... # Instance name (default: rag_bot)
```
