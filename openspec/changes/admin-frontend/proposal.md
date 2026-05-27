# Proposal: Admin Frontend

## Intent

The admin panel (`interface.py` + `index.html`) is public, unauthenticated, and limited to PDF CRUD + config. Owners cannot manage CSV knowledge bases, filter conversations, or securely access the panel. This change makes it a proper authenticated admin interface.

## Scope

### In Scope
- JWT auth: login/logout, protected routes & endpoints
- CSV CRUD: list, upload, download, delete + inline cell editing
- Enhanced logs: filter by phone number
- WhatsApp link: button from config phone number
- Visual refresh: Alpine.js reactivity, same Tailwind CDN

### Out of Scope
- Multi-role auth, persistent DB, WebSockets, build-step SPA

## Capabilities

### New
- `admin-auth`: JWT login/logout, auth middleware, protected routes
- `csv-manager`: CSV CRUD + inline cell editing
- `log-viewer-enhanced`: Filter by phone number, WhatsApp rendering
- `whatsapp-link`: wa.me button from bot_phone config

### Modified
- None (no existing specs)

## Approach

**Frontend**: Alpine.js + Tailwind CDN — reactivity without build step, tiny (~14KB), fits existing vanilla+CDN stack.
**Auth**: JWT (python-jose) + .env JSON — no DB needed for 1-2 owners, stateless.
**Backend**: Enhanced `interface.py` with auth middleware + CSV endpoints + log filtering.

```
Browser (Alpine.js + Tailwind)
  │ fetch() with Bearer token
  ▼
FastAPI (interface.py)
  ├─ POST /api/auth/login      → JWT
  ├─ GET  /api/auth/verify     → validate token
  ├─ CRUD /api/pdfs/*          (existing)
  ├─ CRUD /api/csvs/*          (new)
  ├─ GET  /api/logs/*          (enhanced with ?phone= filter)
  └─ AuthMiddleware guards all except /login
```

## Key Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Frontend | Alpine.js + Tailwind CDN | Reactive CRUD, no build step |
| Auth | JWT + .env JSON | Stateless, no DB for 1-2 owners |
| CSV editing | Inline Alpine + fetch | Immediate feedback, no modals |
| Log identifier | Persist `remoteJid` | Enables phone-based filtering |
| Config phone | Add `bot_phone` to config_bot.json | Bot doesn't know own number |

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `interface.py` | Modified | Auth, CSV, log filter endpoints |
| `index.html` | Rewritten | Alpine.js, 4 sections (login, docs, logs, config) |
| `chat_logger.py` | Modified | Log `remoteJid` instead of "USER" |
| `config_bot.json` | Modified | Add `bot_phone` field |
| `chatbotW/CSVs/` | New | CSV knowledge base directory |
| `requerimientos.txt` | Modified | Add `python-jose[cryptography]` |
| `.env` | Modified | Add `ADMIN_USER`, `ADMIN_PASS` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| JWT XSS exposure | Low | httpOnly cookie option, CSP |
| Log format change breaks parser | Medium | Backward-compatible (old logs still render) |
| CSV edit overwrites | Low | Auto-backup, confirm dialog |

## Rollback Plan

1. Revert `interface.py` to remove auth + new endpoints
2. Revert `chat_logger.py` to hardcoded "USER"
3. Delete `CSVs/` directory
4. Remove `python-jose` from requirements

## Dependencies

- `python-jose[cryptography]` for JWT
- Existing: FastAPI, uvicorn, python-multipart

## Success Criteria

- [ ] Login: valid creds → access panel, invalid → rejection
- [ ] PDF endpoints work post-auth (same behavior)
- [ ] CSV upload → list → edit cell → download → delete cycle works
- [ ] Logs filter by phone number shows only that user's messages
- [ ] WhatsApp link opens `wa.me/{bot_phone}`
