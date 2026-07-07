# Test Plan and Quality Validation (QA)
## Automated WhatsApp Assistance System

**Project**: RAG Chatbot with Gemini + Evolution API
**Version**: 1.0.0-Final
**Status**: Validation Document for Academic Delivery

---

## 1. Introduction and Test Strategy

The goal of this plan is to validate the robustness of the response system and ensure that the **Query Resolution Hierarchy** is strictly respected, which minimizes API cost and maximizes answer accuracy.

### 1.1 Resolution Hierarchy (Validation Target)
The system must process each input in the following order:
`Input` $\rightarrow$ `FAQ (Semantic)` $\rightarrow$ `CSV (Fuzzy)` $\rightarrow$ `RAG (FAISS + Gemini)` $\rightarrow$ `LLM Generation`

### 1.2 Types of Tests Applied
- **Functional Tests**: Validation that the bot responds as expected.
- **Stress Tests (Rate Limit)**: Validation of the 5 msg/60s limit per user.
- **Regression Tests**: Verification that updating PDFs does not break existing data retrieval.
- **Integration Tests**: Validation of the Audio $\rightarrow$ Transcription $\rightarrow$ Response flow.

---

## 2. Test Environment (Test Bed)

To guarantee the reproducibility of the results, the following environment is defined:

- **Infrastructure**: Docker Compose (v2.20+) on WSL2/Ubuntu.
- **Minimum Hardware**: 4GB RAM, 2 CPUs.
- **Knowledge Dataset**:
    - **PDFs**: `Manual_HP_Pavilion_Reducido.pdf`, `Manual_Samsung_A54_Reducido.pdf`, `Manual_Sony_WH1000XM6_Reducido.pdf`.
    - **CSV**: `precios.csv` (containing 5 products with prices and stock).
    - **FAQs**: Set of 10 frequently asked questions configured via the Admin UI.
- **AI Model**: `gemini-3.1-flash-lite` for generation and `gemini-embedding-2-preview` for vectors.

---

## 3. Traceability Matrix and Test Cases

### 3.1 Layer 1: FAQ Matcher (Semantic Validation)
**Objective**: Validate that predefined answers have absolute priority and minimal latency.

| ID | Requirement | Test Input | Expected Result | Acceptance Criteria | Priority |
|---|---|---|---|---|---|
| **T1.1** | Exact Answer | "¿Cuál es el horario de atención?" | Answer configured in FAQ. | Latency < 300ms. Zero Gemini Gen calls. | CRITICAL |
| **T1.2** | Semantic Match | "¿A qué hora abren?" | Schedule answer (even if words vary). | Cosine distance $\le 0.2$. Correct answer. | HIGH |
| **T1.3** | Correct Fallback | "Random question about weather" | The system does NOT return a FAQ. | Log: `matched_id=None`. Passes to Layer 2. | HIGH |

### 3.2 Layer 2: Price Lookup (Fuzzy Matching)
**Objective**: Validate that price search is tolerant to typos and omissions.

| ID | Requirement | Test Input | Expected Result | Acceptance Criteria | Priority |
|---|---|---|---|---|---|
| **T2.1** | Exact Match | "Precio de Samsung Galaxy A54" | Exact Price and Stock from CSV. | 1:1 match with CSV row. | CRITICAL |
| **T2.2** | Typo Tolerance | "Precio de Samung A54" | Finds the product despite the error. | `SequenceMatcher` ratio $> 0.6$. | HIGH |
| **T2.3** | Category Search | "¿Tienen Notebooks?" | List of products in the "Notebooks" category. | Returns $\ge 1$ valid product. | MEDIUM |
| **T2.4** | Non-existent Product | "Precio de iPhone 15" | No match found. | Log: `No price match found`. Passes to Layer 3. | HIGH |

### 3.3 Layer 3: RAG Pipeline (Document Retrieval)
**Objective**: Validate that Gemini generates answers strictly based on fragments retrieved from FAISS.

| ID | Requirement | Test Input | Expected Result | Acceptance Criteria | Priority |
|---|---|---|---|---|---|
| **T3.1** | Technical Retrieval | "¿Cómo configuro el Bluetooth de los Sony?" | Step-by-step instructions from the Sony manual. | Answer based on retrieved context. | CRITICAL |
| **T3.2** | Data Attribution | "¿Qué RAM tiene la HP Pavilion?" | Exact data from the HP manual. | The data matches the indexed PDF. | HIGH |
| **T3.3** | Knowledge Guardrail | "¿Quién ganó el mundial 78?" | Generic answer or notice of missing info. | Does NOT invent manual data to answer. | MEDIUM |

### 3.4 Layer 4: Multimodality (Audio $\rightarrow$ Text)
**Objective**: Validate the transcription pipeline and its integration with the hierarchy.

| ID | Requirement | Test Input | Expected Result | Acceptance Criteria | Priority |
|---|---|---|---|---|---|
| **T4.1** | Audio $\rightarrow$ FAQ | Audio: "¿Horarios?" | Transcription $\rightarrow$ FAQ Match $\rightarrow$ Answer. | Complete flow without manual intervention. | CRITICAL |
| **T4.2** | Audio $\rightarrow$ RAG | Audio: "¿Cómo reinicio el A54?" | Transcription $\rightarrow$ RAG Retrieval $\rightarrow$ Answer. | Accurate transcription $\rightarrow$ Correct answer. | HIGH |

### 3.5 Layer 5: Robustness and Security
**Objective**: Validate system behavior against failures and abuse.

| ID | Requirement | Test Input | Expected Result | Acceptance Criteria | Priority |
|---|---|---|---|---|---|
| **T5.1** | Rate Limiting | 10 messages in 10 seconds. | User blocked on the 6th message. | Message: "Demasiadas solicitudes...". | HIGH |
| **T5.2** | API Error | Simulate Google API outage. | Exception caught $\rightarrow$ Friendly error message. | The bot does NOT crash. Returns `E-API`. | CRITICAL |
| **T5.3** | Corrupt CSV | Delete `precios.csv`. | The system ignores layer 2 and passes to layer 3. | The bot keeps answering via RAG. | MEDIUM |

---

## 4. Log Validation Protocol (Technical Evidence)

To validate that the bot is not "skipping steps" or using the AI unnecessarily, the evaluator must monitor the logs:

`docker logs gemini_whatsapp_bot -f`

### Evidence to look for:
1. **FAQ Success**: Search for `FAQ match attempt` $\rightarrow$ `matched_id=[ID]`. If this appears, there should be no `FAISS` or `Gemini Gen` logs.
2. **Price Success**: Search for `price_lookup` $\rightarrow$ `Match found: [Product]`. If this appears, there should be no `Gemini Gen` logs for the final answer.
3. **RAG Usage**: Search for `FAISS retrieval` $\rightarrow$ `Top k=3 chunks found`. This confirms that the PDFs were accessed.

---

## 5. Final Acceptance Criteria

| Result | Condition | Action |
|---|---|---|
| **APPROVED (PASS)** | 100% of CRITICAL and HIGH tests successful. | Ready for deployment. |
| **APPROVED WITH NOTES** | 100% CRITICAL successful, some MEDIUM/LOW failed. | Deploy with a remediation plan. |
| **REJECTED (FAIL)** | $\ge 1$ CRITICAL test failed. | Return to development phase. |

---

## 6. Execution Log (Bitácora)

| Test ID | Date | Result (P/F) | Observations | Evaluator Signature |
|---|---|---|---|---|
| T1.1 | 2026-07-07 | Successful | Validated with `tests/test_bot_service.py` (25 tests). Covers the webhook handler, message processing, and basic bot responses. Full suite: 777 tests, 0 failures. | Evaluator |
| T1.2 | 2026-07-07 | Successful | Validated with `tests/test_error_handler.py`. Verifies error code classification (`ErrorCode`: E-COM, E-RAG, E-CFG, E-API, E-SYS) and HTTP response codes. Full suite: 777/0. | Evaluator |
| T2.1 | 2026-07-07 | Successful | Validated with `tests/test_vectorstore_manager.py`, `tests/test_rag_orchestrator.py`, and `tests/test_embedding_cache.py`. Covers FAISS vectorstore operations, RAG orchestrator pipeline, and embedding cache. Full suite: 777/0. | Evaluator |
| T3.1 | 2026-07-07 | Successful | Validated with `tests/test_faq_endpoints.py`. Covers semantic FAQ matching and administration endpoints. Full suite: 777/0. | Evaluator |
| T4.1 | 2026-07-07 | Successful | Validated with `tests/test_whatsapp_client.py`, `tests/test_csv_hot_reload.py`, and `tests/test_webhook_secret.py`. Covers the WhatsApp HTTP client, Evolution API webhooks, and CSV hot reload. Full suite: 777/0. | Evaluator |
| T5.1 | 2026-07-07 | Successful | Validated with `tests/test_instances_js.py` and `tests/test_cli.py`. Covers the administration interface (admin UI) and instance management CLI commands. Full suite: 777/0. | Evaluator |
| T5.2 | 2026-07-07 | Successful | Validated with `tests/test_report_generator.py`, `tests/test_report_scheduler.py`, and `tests/test_telemetry.py`. Covers report generation, scheduling, and telemetry persistence. Full suite: 777/0. | Evaluator |
