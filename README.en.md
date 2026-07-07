# Neuradocs — WhatsApp Chatbot with RAG (Gemini + Evolution API)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/Franco-ces/Chatbot-Whatsapp/actions/workflows/ci.yml/badge.svg)](https://github.com/Franco-ces/Chatbot-Whatsapp/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

Neuradocs is an automated response system for WhatsApp based on the **RAG (Retrieval-Augmented Generation)** architecture. The system allows querying knowledge bases stored in PDF documents and local CSV files, processing text and voice audio inputs through Google's Gemini model.

The solution is fully containerized using **Docker**, ensuring portability and consistency of the execution environment.

---

## 🛠️ Installation and Deployment Guide

The system was designed for simplified deployment, where the communication instance is configured directly from the administrative interface.

### 📋 Prerequisites

The following infrastructure must be installed and running:
* **Docker Desktop** (including Docker Compose).
  * [Official Docker documentation](https://www.docker.com/products/docker-desktop/)

---

### 📥 1. Container Deployment

The project includes scripts that automate the provisioning of the required infrastructure. If the `.env` file does not exist, the script will create it automatically from the included template.

#### On Windows (PowerShell):
Run from the project root:
```powershell
./primera_instalacion.ps1
```

#### On Linux / macOS (Bash):
Run from the project root:
```bash
sudo bash primera_instalacion.sh
```

The script will check port availability and, upon completion, report which port each service is running on.

---

### 🔑 2. Configure the Gemini API Key

For the Artificial Intelligence engine (the RAG flow and audio transcription) to work, you need to configure your Google Gemini key:

1. Go to [Google AI Studio](https://aistudio.google.com/) and obtain a new API Key.
2. Access the Admin Panel (by default `http://localhost:8000`).
3. Go to the **Settings** tab in the top menu.
4. Enter your Gemini API Key in the corresponding field and click save. The bot will detect the key automatically without needing to restart the services.

---

### 📱 3. Instance Configuration and Linking

WhatsApp configuration is done centrally from the Admin Panel:

1. Access the Admin Panel (the URL is shown at the end of the installation, by default `http://localhost:8000`).
2. Go to the **Instances** section.
3. Create a new instance (e.g. `rag_bot`).
4. Generate and scan the **QR Code** from the WhatsApp app on your mobile device (**Linked devices** → **Link a device**).
5. Once the account is linked, the bot will start processing messages automatically.

---

## 🖥️ System Operation

The Neuradocs ecosystem consists of two main interfaces:

### 1. Admin Panel (Admin UI)
* **Access:** URL reported at the end of the installation (by default `http://localhost:8000`).
* **Administrative Capabilities:**
  * **Document Management:** Upload and manage PDF files for the knowledge base.
  * **Price and Stock Control:** CSV file editor for product catalog management.
  * **FAQ Management:** Configuration of predefined answers with semantic matching.
  * **Instance Management:** Creation, linking, and deactivation of WhatsApp accounts.
  * **Monitoring:** Real-time conversation log viewing and bot parameter tuning.

### 2. User Interface (WhatsApp)
The bot processes requests following a resolution hierarchy:
1. **Frequent Questions (FAQs):** If the query semantically matches a FAQ, the predefined answer is returned.
2. **Product Lookup (CSV):** If a product search intent is detected, a *fuzzy matching* algorithm is used to locate the price and stock in the CSV files.
3. **RAG Generation (PDFs):** If no prior match is found, the system retrieves relevant fragments from the PDFs using FAISS and generates a contextualized answer with Gemini.
4. **Audio Processing:** Voice messages are transcribed to text using the Gemini API before entering the resolution flow.

---

## 💡 Best Practices for the Knowledge Base

The bot's response performance and accuracy depend directly on the quality of the uploaded files. Make sure to follow these guidelines to optimize behavior:

### 📄 PDF Documents (RAG Flow)
* **Digital and selectable text:** Avoid uploading PDFs that are scanned images. Documents must contain real selectable text so that FAISS and Gemini can index and retrieve the information. If you use scans of physical documents, apply an OCR process before uploading them.
* **Structured information:** Write the content in a clear and direct way. Using hierarchical titles helps the text splitting process (*chunking*) preserve the context of each paragraph optimally.

### 📊 CSV Catalogs (Prices and Stock)
* **Consistent structure:** The CSV file must always maintain the columns expected by the system to ensure correct reading of prices and stock.
* **Descriptive names:** The approximate search algorithm (*fuzzy matching*) works better when product names are clear and legible (e.g. `"Black Cotton T-Shirt"` performs much better than confusing abbreviations like `"Bk Ctn TSh"`).

---

## 🔍 Monitoring and Diagnostics (Health Checks)

The bot has an integrated diagnostics endpoint to verify that all services and connections in the ecosystem are in optimal condition.

### 🩺 Health Endpoint (Deep Health Check)
You can query the system's detailed status by making a `GET` request to the bot (port `5000`):

* **Query URL:** `http://localhost:5000/health`
* **What does it check internally?**
  * **RAG (`rag`):** Checks whether the FAISS and Gemini-based knowledge base initialized and loaded correctly.
  * **Evolution API (`evolution_api`):** Evaluates the latency and direct connectivity with the WhatsApp API, ensuring that the instance the bot is using responds correctly.

#### Example of a healthy response (`status: ok`):
```json
{
  "status": "ok",
  "components": {
    "rag": {
      "status": "ok",
      "duration_ms": 0
    },
    "evolution_api": {
      "status": "ok",
      "duration_ms": 145
    }
  }
}
```

*If any of the components fails, the global status will change to `degraded` or `unhealthy`, returning specific error details (such as connection failures or incorrect credentials), ideal for integrating with monitoring systems.*

---

## 🏗️ Technical Architecture

The system is implemented under a microservices architecture orchestrated by Docker Compose:

```
┌────────────────────────────────────────────────────────┐
│                      DOCKER COMPOSE                    │
│                                                        │
│   ┌──────────────┐     REST API     ┌──────────────┐   │
│   │  Admin UI    │◄────────────────►│ Whatsapp Bot │   │
│   │ (FastAPI:8000│                  │ (FastAPI:5000│   │
│   └──────┬───────┘                  └──────┬───────┘   │
│          │                                 │           │
│          │ Shared                          │ Uses      │
│          ▼ Named Volumes                   ▼           │
│     ┌──────────┐                    ┌──────────────┐   │
│     │ PDFs,    │                    │ FAISS Vector │   │
│     │ Configs, │                    │ Store        │   │
│     │ FAQs     │                    └──────┬───────┘   │
│     └──────────┘                           │           │
│                                            │           │
│   ┌──────────────────┐    Webhook          │           │
│   │  Evolution API   ├─────────────────────┘           │
│   │  (Node.js:8080)  │◄────────────────────┐           │
│   └────────┬─────────┘                     │           │
│            │                               │           │
│      ┌─────┴──────┐                        │           │
│      ▼            ▼                        ▼           │
│ ┌──────────┐ ┌─────────┐            ┌──────────────┐   │
│ │ Postgres │ │  Redis  │            │  Google      │   │
│ │   (DB)   │ │ (Cache) │            │  Gemini API  │   │
│ └──────────┘ └─────────┘            └──────────────┘   │
└────────────────────────────────────────────────────────┘
```

* **Whatsapp Bot:** Orchestration engine. Implements RAG logic, audio processing, and Gemini API integration.
* **Admin UI:** Interface for managing knowledge assets, configuration, and WhatsApp instance control.
* **Evolution API:** Abstraction layer for the WhatsApp communication interface.
* **FAISS:** Library for efficient vector (embedding) search in the semantic space.
* **Fuzzy Matching:** String similarity implementation for data retrieval in CSVs.

---

## 📂 Directory Structure

* **`chatbotW/src/`**: Business logic, services, and controllers.
* **`chatbotW/PDFs/`**: Repository of base documents for information retrieval.
* **`chatbotW/CSVs/`**: Price and stock database.
* **`chatbotW/vectorstore/`**: Automatically generated vector indexes.
* **`chatbotW/cache/`**: Embedding persistence for latency and cost optimization.
* **`chatbotW/logs/`**: Detailed record of transactions and conversations.

---

## 🛑 Service Management (Docker)

Operational commands for system administration from the `chatbotW/` root:

* **Monitor bot logs:**
  ```bash
  docker logs gemini_whatsapp_bot -f
  ```
* **Stop services (preserving data):**
  ```bash
  docker compose down
  ```
* **Start services:**
  ```bash
  docker compose up -d
  ```
* **Full restart (removes FAQs and configurations):**
  ```bash
  docker compose down -v && docker compose up -d --build
  ```

---

If you experience problems during installation or execution, consult the [Troubleshooting Guide](TROUBLESHOOTING.en.md).
