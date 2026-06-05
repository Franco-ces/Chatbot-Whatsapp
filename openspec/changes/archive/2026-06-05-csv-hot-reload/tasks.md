# Tasks: CSV Hot-Reload

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 60–90 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

## Phase 1: Concurrency Infrastructure

- [x] 1.1 Add `asyncio.Lock` to `RAGOrchestrator.__init__()` in `src/rag_orchestrator.py` as `self._reload_lock = asyncio.Lock()`
- [x] 1.2 Convert `RAGOrchestrator.actualizar_memoria()` to `async def` with `async with self._reload_lock:` guard around existing logic
- [x] 1.3 Update `DocumentManager.actualizar_memoria()` in `src/document_manager.py` to catch exceptions from `setup_retriever()` and log with `ErrorCode.RAG_QUERY_FAILED` instead of propagating

## Phase 2: Per-Query Reload Wiring

- [x] 2.1 In `src/bot_service.py`, add `await rag_instance.actualizar_memoria()` inside a `try/except` block before the `preguntar()` call (line 78), log errors but do not re-raise — fall through to existing `preguntar()` with stale retriever
- [x] 2.2 Add a log line in `RAGOrchestrator.actualizar_memoria()` when changes are detected: `"CSV/PDF change detected, rebuilding vectorstore"` for operator visibility

## Phase 3: Manual Reload Endpoint (Optional Safety Valve)

- [x] 3.1 Add `POST /api/reload-rag` endpoint to `src/interface.py` that calls `rag.actualizar_memoria()` and returns `{"status": "reloaded"}` or `{"status": "no_changes"}`

## Phase 4: Testing

- [x] 4.1 Write unit test: mock `VectorStoreManager.calcular_hash_archivos` to return different hashes on consecutive calls; assert `actualizar_memoria()` returns `True` and `setup_retriever()` is called
- [x] 4.2 Write unit test: mock hash to return same value; assert `actualizar_memoria()` returns `False` and `setup_retriever()` is NOT called
- [x] 4.3 Write concurrency test: launch two async tasks calling `actualizar_memoria()` simultaneously with a slow `setup_retriever()` mock; assert only one rebuild occurs (lock serialization)
- [x] 4.4 Write fallback test: mock `setup_retriever()` to raise; assert `bot_service` still calls `preguntar()` and returns a response (stale but functional)
- [x] 4.5 Run existing test suite to verify no regressions

## Relevant Files

- `src/rag_orchestrator.py` — add async Lock, convert actualizar_memoria to async
- `src/bot_service.py` — call actualizar_memoria before preguntar with error guard
- `src/document_manager.py` — add exception handling in actualizar_memoria
- `src/interface.py` — optional POST /api/reload-rag endpoint
- `src/vectorstore_manager.py` — read-only; hash calculation unchanged
- `tests/test_csv_hot_reload.py` — new test file for hot-reload feature
