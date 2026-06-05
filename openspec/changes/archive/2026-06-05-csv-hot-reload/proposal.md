# Proposal: CSV Hot-Reload

## Intent

When a CSV is uploaded through the admin UI, the bot continues responding with stale data until Docker containers are restarted. The admin expects changes to take effect immediately.

## Scope

### In Scope
- Make `precios.csv` updates apply within seconds of admin UI upload
- Fix the broken refresh pipeline so hash-based detection actually triggers rebuilds

### Out of Scope
- PDF hot-reload (same issue, separate change)
- Performance optimization of embedding generation
- New features (file watchers, websockets)

## Root Cause

Two independent data paths exist for CSV prices, and **both are stale**:

1. **FAISS vectorstore** (`document_manager.py`): CSVs are embedded at startup. `actualizar_memoria()` detects changes via hash comparison — but **is never called at runtime**. No polling, no file watcher, no trigger.

2. **Direct CSV reader** (`price_lookup.py`): Reads CSVs with `csv.DictReader` on every query. This path is technically fresh, but it duplicates data already in the vectorstore.

3. **`context_builder.py`** combines both paths. Even if the direct reader is fresh, stale vectorstore chunks pollute the context.

**Root cause**: `actualizar_memoria()` exists in `RAGOrchestrator` but is never invoked by `bot_service.py` or `main.py` during request processing.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- None (pure implementation fix, no spec-level behavior changes)

## Approach

**Option A — Call `actualizar_memoria()` per query (recommended)**:
- In `rag_orchestrator.preguntar()`, call `self.actualizar_memoria()` before delegating to `QueryProcessor`.
- Hash check is O(1) (MD5 of file names + mtimes). Only rebuilds if hash changed.
- Cost: one `stat()` call per query (negligible). Rebuild only on actual change.

**Option B — Background polling loop**:
- Add an `asyncio` task that calls `actualizar_memoria()` every N seconds.
- More complex, harder to reason about, unnecessary given the hash check is cheap.

**Recommended**: Option A. Simpler, deterministic, zero overhead when no change occurred.

Additionally, remove CSV data from the FAISS vectorstore entirely. CSV data is already served by `price_lookup.buscar_precios()` which reads files directly. Embedding CSVs into FAISS creates duplicate, stale-prone data. `context_builder.py` already combines both paths — the vectorstore should only contain PDF chunks.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/rag_orchestrator.py` | Modified | Call `actualizar_memoria()` before each query |
| `src/document_manager.py` | Modified | Remove CSV loading from `setup_retriever()` (PDFs only) |
| `src/vectorstore_manager.py` | Modified | Remove CSV folder from hash calculation |
| `src/context_builder.py` | No change | Already combines FAISS + direct CSV lookup |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Embedding rebuild latency on first query after upload | Medium | Hash check is fast; rebuild only triggers when files actually changed |
| Removing CSVs from vectorstore loses semantic search over prices | Low | `buscar_precios` already provides fuzzy search; CSV data is structured, not narrative |
| Race condition: upload in progress while query arrives | Low | File write completes before 200 response; hash check uses mtime |

## Rollback Plan

Revert the three changed files to their previous versions. The vectorstore metadata.json will have a stale hash, so the first query after rollback triggers a full rebuild (includes CSVs again). No data loss — source files are untouched.

## Dependencies

- None

## Success Criteria

- [ ] Upload CSV via admin UI → next bot query uses fresh data
- [ ] No restart required after CSV upload
- [ ] Hash check does not cause measurable latency on unchanged queries
- [ ] Existing tests pass without modification
