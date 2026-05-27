# Design: Admin Frontend

## Technical Approach

Extend `interface.py` with JWT auth middleware + CSV/log-filtering endpoints. Rewrite `index.html` to Alpine.js+Tailwind CDN — reactive without build step. Auth guards all `/api/*` except login. Four tab sections: Documentos (PDFs+CSVs), Logs, Configuración.

```
Browser (Alpine.js)
  │ fetch() w/ Bearer token
  ▼
FastAPI (interface.py)
  ├─ POST /api/auth/login       → JWT (no middleware)
  ├─ AuthMiddleware              → guards all other /api/*
  ├─ CRUD /api/pdfs/*           (existing, now protected)
  ├─ CRUD /api/csvs/*           (new)
  ├─ GET  /api/logs/{f}?phone=  (enhanced)
  └─ GET/POST /api/config       (enhanced w/ bot_phone)
```

## Architecture Decisions

| Decision | Option | Tradeoff | Decision |
|----------|--------|----------|----------|
| Auth storage | localStorage vs httpOnly cookie | localStorage is XMR-able but simpler; cookie needs CSRF + backend read | **localStorage** — no build step, matches SPA pattern |
| CSV parse | csv.DictReader vs manual split | DictReader handles quoting, types; manual is brittle | **csv.DictReader/csv.writer** — stdlib, correct |
| Log filter | Server-side vs client-side | Server: smaller payload, one endpoint; Client: simple but loads full log | **Server via ?phone=** — scales to large logs |
| Log identifier | Use display_name (field 2) vs add field | display_name already exists; no log format change needed | **display_name** — backward-compatible |
| Confirmation | `confirm()` dialog vs Alpine watcher | confirm is blocking, simple; watcher is complex, UX-smooth | **confirm()** — pragmatic, no state machine needed |

## Data Flow

```
Login:
  LoginForm → POST /api/auth/login → 200 {token} → localStorage → x-show guard hides login

CSV Edit:
  Cell click → Alpine x-model → "Guardar" → PUT /api/csvs/{f}/data → 200 → refresh table

Log Filter:
  Select dropdown → GET /api/logs/{f}?phone=X → server filters lines → render bubbles
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `chatbotW/src/interface.py` | Modify | Add auth middleware + 6 new endpoints + CSV/log paths |
| `chatbotW/src/index.html` | Rewrite | Alpine.js SPA with 5 components, login guard, toasts |
| `chatbotW/chat_logger.py` | Modify | No change needed — display_name field already exists |
| `chatbotW/config_bot.json` | Modify | Add `bot_phone` field |
| `chatbotW/.env` | Modify | Add `ADMIN_USER`, `ADMIN_PASS`, `SECRET_KEY` |
| `chatbotW/requerimientos.txt` | Modify | Add `python-jose[cryptography]` |
| `chatbotW/CSVs/` | Create | CSV storage directory |

## Interfaces / Contracts

### JWT Payload
```python
{"sub": username, "exp": datetime.utcnow() + timedelta(hours=24)}
```

### New Endpoints (interface.py)
```python
from fastapi import Depends, HTTPException, Header
from jose import jwt, JWTError

# Auth
@app.post("/api/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    # validate against .env → {token: jwt}
    
# Dummy endpoint used solely for middleware verification at boot
# (no explicit /api/auth/verify needed — middleware does it)

# CSV CRUD
@app.get("/api/csvs")                                          # list .csv
@app.post("/api/csvs")                                          # upload multipart
@app.delete("/api/csvs/{filename}")                             # delete
@app.get("/api/csvs/{filename}")                                # download
@app.get("/api/csvs/{filename}/data")                           # {headers, rows}
@app.put("/api/csvs/{filename}/data")                           # {headers, rows} → rewrite

# Config (enhanced)
@app.get("/api/config")                                         # now includes bot_phone

# AuthMiddleware
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in EXCLUDED or not request.url.path.startswith("/api"):
            return await call_next(request)
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        try:
            jwt.decode(auth[7:], SECRET_KEY, algorithms=["HS256"])
        except JWTError:
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})
        return await call_next(request)
```

### CSV /data Response
```json
{
  "headers": ["col1", "col2", "col3"],
  "rows": [["val1", "val2", "val3"], ...]
}
```

### CSV /data PUT Body
```json
{
  "headers": ["col1", "col2"],
  "rows": [["a", "b"], ["c", "d"]]
}
```

### Log Filtering Logic
```python
# GET /api/logs/{filename}?phone=X
with open(path) as f:
    lines = f.readlines()
if phone:
    # Keep lines where display_name contains phone OR they are bot responses
    # adjacent to a matching user line
    filtered = []
    for i, line in enumerate(lines):
        parts = line.split("|||")
        if len(parts) >= 2 and phone in parts[1]:
            filtered.append(line)
            # Also include next bot line if exists
            if i + 1 < len(lines) and "id_bot" in lines[i + 1]:
                filtered.append(lines[i + 1])
    lines = filtered
```

## Alpine.js Component Structure

```html
<!-- Root: x-data="app()" where app initializes $store.auth -->
<body x-data="app()">
  <!-- LOGIN SCREEN: x-show="!$store.auth.token" -->
  <template x-if="!$store.auth.token">
    <form @submit.prevent="login">...</form>
  </template>

  <!-- MAIN APP: x-show="$store.auth.token" -->
  <template x-if="$store.auth.token">
    <div>
      <!-- Navbar: title + WhatsApp link + logout -->
      <!-- Tabs: Documentos / Logs / Configuración -->
      <!-- Content per tab -->
    </div>
  </template>
</body>

<!-- Alpine Stores -->
<script>
document.addEventListener('alpine:init', () => {
  Alpine.store('auth', {
    token: localStorage.getItem('token'),
    login(u, p) { fetch POST /api/auth/login → set token },
    logout() { localStorage.removeItem('token'); this.token = null }
  });
});
</script>
```

### Components (x-data)
| Component | Purpose | Key State |
|-----------|---------|-----------|
| `auth` | Login form, token store | `$store.auth.token` |
| `pdfManager` | List/upload/delete PDFs | `pdfs[]`, `loading` |
| `csvManager` | List/upload/edit/delete CSVs | `csvs[]`, `editing`, `dirty` |
| `logViewer` | List logs + view + filter | `logs[]`, `phones[]`, `selectedPhone` |
| `config` | Email, teléfono, bot_phone | `email`, `telefono`, `botPhone` |
| `toast` | Inline notifications | `message`, `type` |

## Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Manual | Auth flow | Login → access → logout → 401 on all endpoints |
| Manual | CSV CRUD | Upload → list → read → edit → delete |
| Manual | Log filter | Select phone → only matching bubbles visible |
| Manual | WhatsApp link | Link visible only when bot_phone set |

## Migration / Rollout

1. Add `ADMIN_USER`/`ADMIN_PASS`/`SECRET_KEY` to `.env` manually
2. Add `bot_phone` to `config_bot.json` manually
3. Deploy: old panel stops working (401 on all endpoints) until user logs in
4. Old PDF/log endpoints keep working behind auth — zero data loss

## Open Questions

- [ ] None — all decisions resolved from specs + codebase read
