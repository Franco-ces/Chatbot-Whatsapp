# Technical Documentation: Automated Assistance System via WhatsApp

## 1. Introduction
This project implements an intelligent agent system capable of interacting with users through WhatsApp, providing answers based on a dynamic knowledge base. The system uses the **RAG (Retrieval-Augmented Generation)** architecture to mitigate hallucinations of language models (LLMs) and ensure that answers are grounded in real, updatable data.

## 2. Technological Justification

### 2.1 Language Model: Google Gemini

**Gemini** was selected over other alternatives (such as GPT-4) for the following fundamental reasons:

#### 2.1.1 Native Multimodality
Gemini can process voice audio directly, eliminating the need for an external transcription service (such as Whisper), which reduces latency and infrastructure complexity.

#### 2.1.2 Context Window and Cost
It offers a superior balance between token cost and response quality for information retrieval tasks.

#### 2.1.3 Embedding Integration
The use of `gemini-embedding-2-preview` enables a consistent vector representation for both document indexing and user queries.

#### 2.1.4 Alignment with Project Objectives
The use of Gemini was an explicit requirement of the course assignment, which guarantees the alignment of the solution with the pedagogical objectives set by the faculty.

### 2.2 Search Engine: FAISS (Facebook AI Similarity Search)

For the RAG implementation, **FAISS** was used instead of a cloud vector database (such as Pinecone) due to:

* **Low Latency:** Being a local search library, vector access is nearly instantaneous.
* **Privacy and Control:** Data never leaves the server environment, guaranteeing the confidentiality of the PDF manuals.
* **Deployment Simplicity:** It does not require managing external clusters, integrating directly into the Docker data volume.

### 2.3 Communication Gateway: Evolution API

**Evolution API** was chosen as a robust open-source solution that abstracts the complexity of the WhatsApp protocol, enabling integration via Webhooks and REST API, which decouples the bot logic from device connection management.

---

## 3. Solution Design

### 3.1 Query Resolution Hierarchy

To optimize accuracy and API cost, the system does not send all queries to the LLM. It implements a **resolution cascade**:

1. **FAQ Layer (Semantic Matching):** The system compares the query with a base of frequently asked questions. Cosine similarity between embeddings is used to detect intent, enabling instant and exact answers at no text generation cost.
2. **Catalog Layer (Fuzzy Matching):** If the query is identified as a product search, the system scans CSV files using a string similarity algorithm (*SequenceMatcher*). This allows tolerating user typos when searching for prices or stock.
3. **RAG Layer (Contextual Retrieval):** If the previous layers fail, the system retrieves the most relevant fragments from the PDF manuals indexed in FAISS and feeds them to Gemini as context to generate a grounded answer.

### 3.2 Audio Processing Flow

The system implements an efficient audio pipeline:

`WhatsApp Audio (OGG)` → `In-memory Load` → `Gemini Multimodal API` → `Text Transcription` → `Resolution Flow`.

---

## 4. Infrastructure and Persistence

### 4.1 Docker Orchestration

The architecture is based on microservices to ensure responsibility isolation:

* **Bot Service:** Business logic and RAG orchestration.
* **Admin UI:** Asset management and monitoring.
* **Evolution API:** Messaging transport layer.
* **Postgres/Redis:** State support for the communication gateway.

### 4.2 Persistence Strategy

Docker **Named Volumes** were used to prevent data loss between container restarts and to solve file locking issues in WSL2 environments:

* `/app/faqs_data`: Stores the FAQ base.
* `/app/config_data`: Stores the bot configuration and API Key.

---

## 5. Robustness and Error Handling Strategy

The system implements a hierarchical exception handling framework based on the `AppError` class and the `ErrorCode` enumeration.

* **Fault Isolation:** Errors in the embeddings API or file reading do not halt bot execution; instead, the system degrades functionality (e.g. if FAQ matching fails, it falls through directly to RAG).
* **Data Validation:** Pydantic models are used to validate incoming payloads from WhatsApp webhooks, preventing execution errors from malformed data.

---

## 6. Audit of Administrative Actions

### 6.1 Purpose

The system automatically records all actions performed from the administration panel in the `telemetry.admin_audit` table of PostgreSQL. This enables:

- Traceability: knowing who did what and when.
- Debugging: identifying the cause of unwanted changes.
- Security: detecting unauthorized access or anomalous behavior.

### 6.2 Recorded Actions

| Category | Actions |
|---|---|
| **Authentication** | Successful login, failed login (with IP), password change |
| **Configuration** | Saving Google API Key, Evolution API Key, contact details |
| **PDF Documents** | File upload and deletion |
| **CSV Files** | File upload, deletion, and editing |
| **FAQs** | Creation, update, and deletion of frequently asked questions |
| **Instances** | Creation, activation, deactivation, and deletion of Evolution API instances |

### 6.3 Table Structure

```sql
CREATE TABLE telemetry.admin_audit (
    id              BIGSERIAL PRIMARY KEY,
    action          TEXT NOT NULL,       -- e.g.: 'pdf.delete', 'instance.create'
    actor           TEXT DEFAULT 'admin', -- always 'admin' (single user)
    target          TEXT,                -- affected item (file, instance, FAQ id)
    detail          TEXT,                -- additional contextual information
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.4 How to Access the Records

**From the API** (requires authentication):
```bash
# Last 50 records
curl -H "Authorization: Bearer <TOKEN>" http://localhost:8000/api/audit?limit=50

# Last 10 records
curl -H "Authorization: Bearer <TOKEN>" http://localhost:8000/api/audit?limit=10
```

**From PostgreSQL directly**:
```bash
# Enter the PostgreSQL container
docker compose exec evolution_postgres psql -U evo -d evolution

# Query the last 20 records
SELECT action, target, detail, created_at
FROM telemetry.admin_audit
ORDER BY created_at DESC
LIMIT 20;

# Filter by action type
SELECT * FROM telemetry.admin_audit
WHERE action = 'pdf.delete'
ORDER BY created_at DESC;

# Filter by date
SELECT * FROM telemetry.admin_audit
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
```

### 6.5 Fire-and-Forget Design

The audit follows the same pattern as `record_interaction` (bot telemetry): if the database is unavailable, **administrator actions are not blocked**. The system simply skips the audit record and continues. This guarantees that a PostgreSQL failure does not prevent operating the administration panel.
