# CSV Hot-Reload Specification

## Purpose

Ensure the bot uses up-to-date CSV data (prices, products) after admin upload without requiring a Docker restart. The bot MUST detect CSV file changes and rebuild the vectorstore transparently during normal request processing.

## Requirements

### Requirement: CSV Change Detection

The system MUST detect CSV file changes by comparing the current file hash against the stored hash before processing each user message.

#### Scenario: CSV file changed since last build

- GIVEN the admin uploaded a new `precios.csv` via the interface
- WHEN the next user message arrives at the bot webhook
- THEN the system detects the hash mismatch between current files and stored metadata
- AND triggers a vectorstore rebuild before responding

#### Scenario: No CSV changes detected

- GIVEN no files have changed since the last vectorstore build
- WHEN a user message arrives
- THEN the hash check completes in under 50ms
- AND the existing vectorstore is used without rebuild

#### Scenario: First startup with no vectorstore

- GIVEN no `metadata.json` exists in the vectorstore directory
- WHEN the bot starts and receives its first message
- THEN the system builds the vectorstore from all PDFs and CSVs
- AND stores the hash for future change detection

### Requirement: Pre-Query Reload

The system SHALL call `actualizar_memoria()` at the start of each message processing cycle, before the RAG query is executed.

#### Scenario: Reload before RAG query

- GIVEN a user sends a message to the bot
- WHEN `procesar_mensaje_bot()` begins processing
- THEN `rag_instance.actualizar_memoria()` is called before `rag_instance.preguntar()`
- AND the retriever reflects the latest file state

#### Scenario: Reload failure does not block responses

- GIVEN `actualizar_memoria()` encounters an error during rebuild (e.g., API rate limit, corrupt file)
- WHEN the rebuild fails
- THEN the system logs the error with the relevant error code
- AND falls back to the previous retriever (stale but functional)
- AND the user receives a normal response, not an error

### Requirement: No-Downtime Rebuild

The system MUST rebuild the vectorstore without blocking other requests or serving stale data during the transition.

#### Scenario: Concurrent requests during rebuild

- GIVEN two user messages arrive within 2 seconds of each other
- WHEN the first triggers a vectorstore rebuild
- THEN the second request waits for the rebuild to complete
- AND both requests receive responses based on the new vectorstore

#### Scenario: Rebuild takes longer than expected

- GIVEN a vectorstore rebuild is in progress and exceeds 30 seconds
- WHEN the rebuild is still running
- THEN the system continues serving from the old retriever for pending requests
- AND logs a warning with the elapsed time

### Requirement: Embedding Cache Preservation

The system MUST preserve the embedding cache across rebuilds so that unchanged text chunks are not re-embedded.

#### Scenario: Partial CSV change

- GIVEN `precios.csv` has 50 rows and 10 rows changed
- WHEN the vectorstore is rebuilt
- THEN only the chunks derived from changed rows generate new embeddings
- AND chunks from unchanged rows use cached embeddings from `cache/embeddings_cache.json`

#### Scenario: Cache miss on new content

- GIVEN a new CSV file is uploaded with no prior embeddings in cache
- WHEN the vectorstore is rebuilt
- THEN new embeddings are generated with the configured rate-limit delay (`time.sleep(0.5)`)
- AND the new embeddings are persisted to the cache

### Requirement: Price Lookup Independence

CSV product data MUST be served exclusively through `price_lookup.buscar_precios()`, which reads CSV files directly from disk. CSV files are currently included in the FAISS vectorstore for change detection purposes; excluding them from FAISS is deferred to a future cleanup change.

#### Scenario: Price query uses direct CSV read

- GIVEN the user asks about product prices
- WHEN the RAG pipeline processes the query
- THEN `price_lookup.buscar_precios()` reads the current CSV files from disk
- AND returns results from the latest file content, regardless of vectorstore state

#### Scenario: Vectorstore contains PDFs and CSVs

- GIVEN both PDFs and CSVs exist in the data folders
- WHEN the vectorstore is built or rebuilt
- THEN both PDF documents and CSV files are indexed in FAISS
- AND CSVs are included for change detection but price queries use direct CSV read

### Requirement: Change Detection Scope

The system MUST include CSV files in the hash calculation used for change detection. CSV files are included in the vectorstore for now; excluding them is deferred.

#### Scenario: CSV-only change triggers rebuild

- GIVEN only a CSV file was modified (no PDF changes)
- WHEN the hash is recalculated
- THEN the hash differs from the stored value
- AND the vectorstore rebuild is triggered (to pick up any PDF changes that may have co-occurred)

#### Scenario: PDF-only change triggers rebuild

- GIVEN only a PDF file was modified (no CSV changes)
- WHEN the hash is recalculated
- THEN the hash differs from the stored value
- AND the vectorstore rebuild is triggered

## Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Hash check latency | < 50ms (file stat calls only) |
| Rebuild blocking | Requests queue, do not fail |
| Embedding cache hit rate | > 90% for unchanged content |
| Downtime during rebuild | 0 seconds (old retriever serves until new one is ready) |
