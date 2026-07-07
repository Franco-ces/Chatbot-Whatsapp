# Contributing to Neuradocs

Thanks for your interest in contributing! This document covers the essentials for getting set up and shipping changes that merge cleanly.

For deeper architectural context, see [`README.md`](./README.md) and [`DOCUMENTACION_TECNICA.md`](./DOCUMENTACION_TECNICA.md). English versions (`README.en.md`, `DOCUMENTACION_TECNICA.en.md`) are available for international contributors.

## Getting Started

### Option 1: Full stack with Docker (recommended)

The project runs as a 5-service Docker Compose stack (bot, admin-ui, evolution-api, postgres, redis). Use this when you need to test the full system end-to-end.

```bash
git clone https://github.com/Franco-ces/Chatbot-Whatsapp.git
cd Chatbot-Whatsapp/chatbotW
cp .env.example .env          # Edit .env with your API keys
docker compose up -d --build
docker logs gemini_whatsapp_bot -f  # Follow bot logs
```

See [`README.md`](./README.md) for the first-time setup script and WhatsApp QR linking.

### Option 2: Local venv (test-only contributions)

Use this for quick test runs when you don't need the full stack. Requires `ffmpeg` on the host.

```bash
git clone https://github.com/Franco-ces/Chatbot-Whatsapp.git
cd Chatbot-Whatsapp/chatbotW
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest  # Confirm 777 passed, 0 failures
```

### Dependencies

- **Audio transcription** requires `ffmpeg` on the host:
   ```bash
   sudo apt install ffmpeg   # Linux
   ```

## Development Workflow

1. **Branch from `main`**, never commit directly to `main`:
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feat/your-feature-name
   ```
2. **Run the full test suite before pushing.** CI will reject red builds, but running locally is faster.
3. **Keep branches short-lived** and focused on a single concern.
4. **Rebase onto `main`** if your branch falls behind to avoid messy merge commits.

## Commit Conventions

We use [Conventional Commits](https://www.conventionalcommits.org/). Each commit message starts with a type prefix:

| Prefix   | Use for |
|----------|---------|
| `feat:`  | A new feature |
| `fix:`   | A bug fix |
| `docs:`  | Documentation changes |
| `chore:` | Build, config, tooling, maintenance |
| `test:`  | Adding or correcting tests |

Example: `feat: add fuzzy price lookup fallback to CSV search`

Keep the subject line under 72 characters. Add a body when the *why* is not obvious from the subject.

## Testing

The test suite lives in `chatbotW/tests/` and uses `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"`). All tests are synchronous and rely on mocks — no real API calls are made.

### Run the full suite
```bash
cd chatbotW
pytest
```

### Run a single test file
```bash
cd chatbotW
pytest tests/test_bot_service.py
```

### Run tests by name pattern
```bash
cd chatbotW
pytest -k "test_audio"
```

> Tests add `chatbotW/src/` to `sys.path` via `conftest.py`. Do not add an `__init__.py` to `src/` — it relies on PEP 420 namespace packages.

## Code Style

- **Follow the patterns of the file you are editing.** Consistency with surrounding code wins over personal preference.
- **Comments in source code are in Spanish** — match the existing convention.
- **User-facing messages are in Spanish** (bot replies, error messages shown to end users, log text).
- **Error handling** uses the `ErrorCode` enum and `AppError` hierarchy (`src/exceptions.py`, `src/error_codes.py`). Never raise raw `Exception`.
- **Each module owns one concern.** When adding a feature, create a focused new file rather than bloating an existing one.
- **Pydantic models** are used for webhook payload parsing (`src/payload_parser.py`).
- **Type hints** are not consistently applied across the codebase. Match the file you are editing; do not add hints to files that do not use them.

## Pull Requests

1. **Keep PRs focused** — one logical change per PR. If a change spans multiple concerns, split it into chained PRs.
2. **Link the PR to an issue** in the description (e.g., `Closes #42`).
3. **Ensure the test suite is green** (`777 passed, 0 failures`) before requesting review.
4. **Describe the *what* and *why*** in the PR body, not just the *how* — the diff already shows the how.
5. Small, reviewable PRs (under ~400 changed lines) merge faster. Larger changes should be split into a chain.

## Documentation

- **Update docs when you change behavior.** If you add an endpoint, a config flag, or alter an admin flow, the relevant doc (README, `DOCUMENTACION_TECNICA.md`, or `TROUBLESHOOTING.md`) must reflect it.
- **English versions** (`*.en.md`) exist for international contributors. Keep them in sync with their Spanish counterparts when a doc change touches translated content.
- **Avoid doc drift**: code changes that introduce operator-facing functionality should note what needs documenting and delegate the doc update to a separate pass rather than leaving docs stale.

## Questions?

If anything here is unclear or you are unsure where to start, **open an issue** with the `question` label. A maintainer will point you in the right direction. Don't guess — ask.