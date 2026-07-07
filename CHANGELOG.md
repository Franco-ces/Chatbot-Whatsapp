# Changelog

All notable changes to NeuraDocs will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-07

### Added
- WhatsApp chatbot with Gemini RAG pipeline (FAISS + Google Gemini)
- Multi-layer query resolution: FAQ → CSV catalog → RAG
- Audio message transcription via Gemini multimodal
- Admin web panel (FastAPI + Alpine.js): document upload, instance management, telemetry
- Docker Compose deployment (5 services: bot, admin-ui, evolution-api, postgres, redis)
- One-click install scripts for Linux (Bash) and Windows (PowerShell)
- Automated test suite (777 tests, pytest)
- GitHub Actions CI pipeline
- Rate limiting, guardrails (input/output), human handoff detection
- Structured logging (structlog), health checks, telemetry persistence
- Report generation (WeasyPrint HTML→PDF) with scheduling
- Audit logging for admin actions
- Hot-reload for PDF vectorstore and CSV catalog
- Configurable Gemini models and bot tone via admin UI
- Dark mode admin UI
- Granular error codes (E-COM, E-RAG, E-CFG, E-API, E-SYS, E-FAQ)
- MIT License

### Documentation
- README (Spanish + English)
- Technical documentation (Spanish + English)
- AGENTS.md for developer/AI onboarding
- Test plan with execution log (Spanish + English)
- Troubleshooting guide (Spanish + English)
- CONTRIBUTING.md

[1.0.0]: https://github.com/Franco-ces/Chatbot-Whatsapp/releases/tag/v1.0.0