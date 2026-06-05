# Design: CSV Hot-Reload

## Technical Approach

Call `RAGOrchestrator.actualizar_memoria()` at the start of each bot query. The hash check (`VectorStoreManager.calcular_hash_archivos`) is O(n_files) stat + MD5 — negligible for <50 files. When changes are detected, `setup_retriever()` rebuilds FAISS in the background. `price_lookup.buscar_precios()` already reads CSVs fresh from disk on every query, so price data is always current — the staleness only affects the FAISS vectorstore used for RAG document retrieval.

## Architecture Decisions

### Decision: Per-query hash check vs. file watcher vs. admin endpoint

| Approach | Tradeoff | Decision |
|----------|----------|----------|
| Per-query hash check | O(1)-ish overhead per request; rebuild only when files change; zero config | **Chosen** |
| `watchdog` file watcher | Adds dependency; background thread complexity; file system events unreliable in Docker mounts | Rejected |
| Admin UI endpoint only | Requires operator action; no automatic detection | Rejected (keep as supplement) |
| Polling loop (asyncio.create_task) | Wasted cycles; latency depends on poll interval | Rejected |

**Rationale**: `actualizar_memoria()` already implements the perfect pattern — stat files, compare hash, rebuild if changed. It was built for this. We just need to call it.

### Decision: Thread safety for retriever swap

**Choice**: `asyncio.Lock` in `bot_service.py` serializes `actualizar_memoria()` calls.
**Alternatives considered**: Lock-free CAS on retriever ref; lock in RAGOrchestrator.
**Rationale**: Multiple concurrent webhooks can trigger `actualizar_memoria()` simultaneously. Without a lock, two coroutines could both detect changes and both rebuild — wasting API calls. The lock ensures one rebuild at a time. Since rebuild is rare (only on file change), contention is negligible.

### Decision: Remove CSVs from FAISS vectorstore

**Choice**: Exclude CSVs from `DocumentManager.setup_retriever()` ingestion. Keep CSV ingestion in FAISS only for backward compatibility during transition.
**Alternatives considered**: Remove immediately; keep both paths forever.
**Rationale**: `price_lookup.buscar_precios()` already reads CSVs fresh and does fuzzy matching. Having CSVs in FAISS is redundant — they add embedding cost (0.5s per chunk) and stale data risk. However, removing them changes RAG behavior for CSV-heavy queries. Mark as a future cleanup, not part of this change.

## Data Flow

```
Admin UI upload (interface.py)
    → writes CSV to CSV_FOLDER
    → (no trigger currently)

Webhook arrives (main.py → bot_service.py)
    → rag.actualizar_memoria()          ← NEW
        → doc_manager.actualizar_memoria()
            → VectorStoreManager.calcular_hash_archivos()  [stat + MD5]
            → if hash changed: setup_retriever() → rebuild FAISS
        → self.retriever = new retriever (if updated)
    → rag.preguntar() uses fresh retriever
    → construir_contexto() → buscar_precios() reads CSVs fresh (always)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/bot_service.py` | Modify | Call `rag_instance.actualizar_memoria()` before `preguntar()`, guarded by asyncio.Lock |
| `src/rag_orchestrator.py` | Modify | Add `asyncio.Lock` to prevent concurrent rebuilds; make `actualizar_memoria()` async |
| `src/interface.py` | Modify | Add `POST /api/reload-rag` endpoint for manual trigger (admin safety valve) |

## Interfaces / Contracts

```python
# rag_orchestrator.py — change signature to async
async def actualizar_memoria(self) -> bool:
    async with self._reload_lock:
        # ... existing logic ...

# bot_service.py — add before preguntar()
async with reload_lock:
    await rag_instance.actualizar_memoria()

# interface.py — new endpoint
@app.post("/api/reload-rag")
async def reload_rag():
    """Manual RAG reload trigger for admin."""
    rag.actualizar_memoria()  # called from interface context
    return {"status": "reloaded"}
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `actualizar_memoria()` returns True on file change, False on no change | Mock `VectorStoreManager.calcular_hash_archivos` and metadata reads |
| Unit | Lock prevents concurrent rebuilds | Two async tasks call `actualizar_memoria()` simultaneously; assert only one rebuild |
| Integration | Bot responds with fresh CSV data after upload | Upload CSV via admin API, query bot, assert new data in response |
| E2E | Admin upload → next query uses new data (no restart) | Full flow: upload → webhook → response verification |

## Migration / Rollout

No migration required. The change is backward-compatible: existing behavior (stale vectorstore until restart) is replaced by automatic refresh. The `actualizar_memoria()` method already exists and is tested by the existing hash-check logic.

## Open Questions

- [ ] Should the interface.py endpoint also call `actualizar_memoria()` on the shared `rag` instance, or require a separate admin auth check beyond the existing JWT middleware?
- [ ] Should we add a log line when hot-reload detects changes (for operator visibility)?
