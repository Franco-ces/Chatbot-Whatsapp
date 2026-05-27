# Tasks: Admin Frontend

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~550-660 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (Auth) → PR 2 (CSV) → PR 3 (Config+Logs+Polish) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Auth foundation | PR 1 | main branch; login flow + middleware + app shell |
| 2 | CSV CRUD | PR 2 | PR 1 branch; CSV endpoints + editable table |
| 3 | Config + Logs + UI | PR 3 | PR 2 branch; bot_phone, log filter, toasts, loading |

## Phase 1: Auth

- [ ] 1.1 Add `python-jose[cryptography]` to `chatbotW/requerimientos.txt`
- [ ] 1.2 Add `ADMIN_USER`, `ADMIN_PASS`, `SECRET_KEY` to `chatbotW/.env`
- [ ] 1.3 Add `AuthMiddleware` and `POST /api/auth/login` to `chatbotW/src/interface.py`
- [ ] 1.4 Rewrite `chatbotW/src/index.html` with Alpine store `auth`, login form, navbar + tabs shell

## Phase 2: CSV CRUD

- [ ] 2.1 Create `chatbotW/CSVs/` directory
- [ ] 2.2 Add CSV endpoints (list, upload, download, delete) to `interface.py`
- [ ] 2.3 Add CSV data endpoints (GET/PUT `/data`) with DictReader/Writer to `interface.py`
- [ ] 2.4 Add `csvManager` component to `index.html` — list, upload, editable table, delete

## Phase 3: Config + WhatsApp Link

- [x] 3.1 Add `bot_phone` to `chatbotW/config_bot.json`
- [x] 3.2 Enhance `GET /api/config` in `interface.py` to return `bot_phone`
- [x] 3.3 Add `config` component + WhatsApp link in navbar to `index.html`

## Phase 4: Log Viewer Enhanced

- [x] 4.1 Add `?phone=` filter support to `GET /api/logs/{filename}` in `interface.py`
- [x] 4.2 Add `logViewer` component — phone dropdown, server-filtered bubbles — to `index.html`

## Phase 5: Polish

- [x] 5.1 Add loading states to all async operations in `index.html`
- [x] 5.2 Add toast notifications (success/error) in `index.html`
- [x] 5.3 Add confirm dialog on unsaved CSV edits in `index.html`
