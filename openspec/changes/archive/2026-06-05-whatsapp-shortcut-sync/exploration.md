# Exploration: WhatsApp Shortcut Button Sync

## Current State

### How the Button Works Today

The WhatsApp shortcut button lives in the admin UI navbar (`src/index.html` line 78-85). When clicked, it opens `https://wa.me/{botPhone}` in a new tab. The phone number comes from `config_bot.json.bot_phone`, loaded via the Alpine.js store.

**Button rendering**: Green button with 📱 icon. Shows "WhatsApp" when `botPhone` is set, "Sin configurar" when empty. Disabled (opacity-50, cursor-not-allowed) when no phone number is configured.

**Phone number source**: The admin must manually type the phone number in the Config tab (line 144-147). It's saved to `config_bot.json.bot_phone` via `POST /api/config`.

### The Disconnect

The bot's phone number IS known to the system — it's the `ownerJid` of the active Evolution instance (format: `{phone}@s.whatsapp.net`). But the button doesn't use it. The admin has to manually type the same number that Evolution already knows.

### Phone Number Flow (Current)

```
User types phone → POST /api/config → config_bot.json.bot_phone
                                            ↓
Alpine store ← GET /api/config ← ConfigManager.cargar()
                                            ↓
Button: https://wa.me/{botPhone}
```

### Evolution API Instance Relationship

- **Active instance**: `config_bot.json.active_instance_name` (set by `instance_activation.py`)
- **InstanceWatcher**: Polls mtime of `config_bot.json` every ~1s, hot-swaps active instance name
- **InstanceInfo model** (`evolution_models.py` line 29-65): Has `owner_jid` field (format: `{phone}@s.whatsapp.net`)
- **Evolution API**: `GET /instance/fetchInstances` returns instance info including `owner` field
- **Current `InstanceInfo` model**: Missing `owner_jid` in the actual Evolution response (Evolution uses `owner`, not `ownerJid`)

## Affected Areas

| File | Role | Why Affected |
|------|------|-------------|
| `src/interface.py` | Admin UI API endpoints | Needs new endpoint to expose active instance's phone number |
| `src/static/js/app.js` | Frontend config loading | Needs to auto-populate `botPhone` from active instance |
| `src/static/js/store.js` | Alpine store | May need new state for instance-derived phone |
| `src/index.html` | Button HTML | May need UI changes to show source (manual vs auto) |
| `src/evolution_models.py` | Pydantic models | `InstanceInfo.owner_jid` mapping needs verification |
| `src/ConfigManager.py` | Config persistence | No changes needed (already handles `bot_phone`) |
| `src/instance_watcher.py` | Active instance tracking | No changes needed (already tracks active name) |
| `src/evolution_admin.py` | Evolution API client | No changes needed (already fetches `ownerJid`) |

## Approaches

### Approach 1: Backend-Driven Auto-Sync

Add a backend endpoint that returns the active instance's phone number. The frontend loads it on startup and saves it to `config_bot.json` if `bot_phone` is empty.

**Flow**:
```
GET /api/evolution/active/phone
  → InstanceWatcher.get_active_name()
  → EvolutionAdmin.list_instances() (or get by name)
  → Extract phone from ownerJid
  → Return {phone: "5491112345678"}

Frontend loads this on startup
  → If config_bot.json.bot_phone is empty, auto-fill
  → Show in navbar button
```

**Pros**:
- Single source of truth (Evolution API)
- No manual entry needed for basic use case
- Works across container restarts

**Cons**:
- Extra API call on page load
- Tight coupling between config and instance state
- Migration: existing manual `bot_phone` values must be preserved

### Approach 2: Frontend-Only Sync

The frontend fetches the active instance's phone number and uses it directly for the button, without modifying `config_bot.json`.

**Flow**:
```
Frontend loads
  → GET /api/config (gets bot_phone if set)
  → GET /api/evolution/active (gets active instance name)
  → GET /api/evolution/instances (gets ownerJid)
  → Extract phone from ownerJid
  → Use: manual bot_phone > instance ownerJid
```

**Pros**:
- No backend changes needed
- Immediate sync on page load
- Preserves manual override capability

**Cons**:
- Multiple API calls on load
- Phone number not persisted (re-derived each time)
- More complex frontend logic

### Approach 3: Hybrid — Backend exposes phone, frontend auto-fills config

The backend adds a helper that derives the phone from the active instance. The frontend uses this to auto-fill `config_bot.json.bot_phone` on first load (if empty).

**Flow**:
```
GET /api/config → returns bot_phone (may be empty)
GET /api/evolution/active → returns active instance name
GET /api/evolution/instances/{name} → returns ownerJid
  → Backend extracts phone, includes in response

Frontend:
  → If bot_phone is empty AND instance has phone, auto-save
  → Button uses bot_phone (now populated)
```

**Pros**:
- Best of both worlds: auto-fill + persistence
- Manual override still works
- Single source of truth after first sync

**Cons**:
- Slightly more complex implementation
- Need to handle the "first load" case carefully

## Recommendation

**Approach 3: Hybrid — Backend exposes phone, frontend auto-fills config**

This is the cleanest solution because:
1. It maintains the existing `config_bot.json` as the source of truth for the button
2. It auto-fills from Evolution when the admin hasn't manually set it
3. It preserves manual override capability (admin can still type a different number)
4. It works across restarts (phone is persisted in config)

## Technical Details

### Evolution API `ownerJid` Format

The `ownerJid` field from Evolution API is in the format: `{phone}@s.whatsapp.net`

To extract the phone number: `ownerJid.split('@')[0]`

### Current `InstanceInfo` Model Issue

The `InstanceInfo` model in `evolution_models.py` has `owner_jid` with alias `ownerJid`, but Evolution API v2.x actually returns the field as `owner` (not `ownerJid`). The model needs to accept both aliases.

### Phone Number Format for wa.me

The `wa.me` link expects the phone number in international format without `+` or spaces. Example: `https://wa.me/5491112345678`

The `ownerJid` already provides this format (e.g., `5491112345678@s.whatsapp.net` → `5491112345678`).

## Risks

1. **Evolution API field naming**: The `owner` vs `ownerJid` inconsistency between Evolution versions. Need to handle both in the model.
2. **Instance not connected**: If the active instance is in `close` state, `ownerJid` may be null. Button should fall back to manual config or show "Sin conectar".
3. **Multiple instances**: If the admin switches instances, the phone number changes. The auto-sync should re-check on each page load.
4. **Manual override preserved**: If the admin manually sets `bot_phone`, it should NOT be overwritten by the auto-sync. Only auto-fill when `bot_phone` is empty.

## Ready for Proposal

Yes — the exploration is complete. The orchestrator should:
1. Confirm the hybrid approach with the user
2. Clarify if manual override preservation is important
3. Proceed to sdd-propose
