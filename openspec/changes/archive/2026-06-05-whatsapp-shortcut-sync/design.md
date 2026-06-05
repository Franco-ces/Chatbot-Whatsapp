# Design: WhatsApp Shortcut Sync

## Technical Approach

Replace the manual `bot_phone` config field with auto-detection from the active Evolution instance's `ownerJid`. The phone number is extracted client-side in `instances.js` when instances load, and the existing `Alpine.store('app').botPhone` store is populated from that data. The `ownerJid` field (`{phone}@s.whatsapp.net`) is already returned by `/api/evolution/instances` and modeled in `InstanceInfo.owner_jid`.

## Architecture Decisions

### Decision: Client-side phone extraction vs backend endpoint

**Choice**: Extract phone from `ownerJid` in `instances.js` (frontend)
**Alternatives considered**: New `/api/evolution/active-phone` endpoint
**Rationale**: The `ownerJid` is already fetched by `loadInstances()` — no extra API call. Phone extraction is trivial string splitting (`split("@")[0]`). A backend endpoint adds complexity for zero benefit.

### Decision: Keep `Alpine.store('app').botPhone` in store.js

**Choice**: Keep the store property; populate it from `instances.js`
**Alternatives considered**: Remove store and compute phone directly in the navbar template
**Rationale**: The navbar button uses `$store.app.botPhone` in index.html. Keeping the store means only `instances.js` and the navbar need to know about phone — `app.js` and config tab are completely decoupled.

### Decision: Remove `bot_phone` from ConfigManager entirely

**Choice**: Delete `bot_phone` from defaults, `cargar()`, and `guardar()` signature
**Alternatives considered**: Keep `guardar()` param for backward compat, just ignore it
**Rationale**: Dead code is worse than no code. The parameter was never used externally — only by `interface.py`'s endpoint. Removing it prevents accidental re-introduction. `config_bot.json` files with `bot_phone` will keep the stale key (harmless) until next write.

## Data Flow

```
Evolution API ──GET /instances──→ instances.js
                                      │
                                      ├─ find active instance (name matches $store.activeName)
                                      ├─ extract phone: inst.ownerJid.split("@")[0]
                                      └─ Alpine.store('app').botPhone = phone
                                              │
                                              ▼
                                      navbar button (index.html)
                                      uses $store.app.botPhone for link + disabled state
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/ConfigManager.py` | Modify | Remove `bot_phone` from defaults dict (L50), `cargar()` setdefault (L67), and `guardar()` signature (L77-84) |
| `src/interface.py` | Modify | Remove `bot_phone` param from `guardar_config()` (L156) and `guardar()` call (L158) |
| `src/static/js/app.js` | Modify | Remove `configBotPhone` state (L29), remove load from `loadContactConfig()` (L119-120), remove save from `saveContactConfig()` (L134, L142) |
| `src/static/js/instances.js` | Modify | After `loadInstances()`, find active instance, extract phone from `ownerJid`, set `Alpine.store('app').botPhone` |
| `src/index.html` | Modify | Remove phone input field (L143-147), update button tooltip text (L81) |
| `config_bot.json` | Modify | Remove `bot_phone` key (current value is `""` — no user impact) |

## Interfaces / Contracts

No new endpoints or contracts. The existing `/api/evolution/instances` response already includes `ownerJid` per instance. The phone extraction logic:

```javascript
// In instances.js, after loadInstances():
const active = this.instances.find(i => i.name === this.activeName);
const phone = active?.ownerJid?.split('@')[0] || '';
Alpine.store('app').botPhone = phone;
```

Button disabled state in `index.html` changes from:
```html
:title="$store.app.botPhone ? 'Abrir WhatsApp' : 'Configurá el número del bot'"
```
to:
```html
:title="$store.app.botPhone ? 'Abrir WhatsApp' : 'Instancia no conectada o sin número'"
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Phone extraction from `ownerJid` | Mock `instances` array with various `ownerJid` values (null, empty, valid). Assert `$store.app.botPhone` |
| Integration | Button disabled when no active instance | Mock `loadInstances()` returning empty or disconnected instances |
| E2E | Button shows correct phone on page load | Not needed — relies on existing mock infrastructure |

## Migration / Rollout

No migration required. Existing `config_bot.json` files retain the stale `bot_phone` key — it is inert after the code change. On next config save (e.g., email edit), the key disappears naturally because `guardar()` no longer writes it.

## Open Questions

None. The approach is fully scoped and follows existing patterns (client-side store population from `instances.js`).
