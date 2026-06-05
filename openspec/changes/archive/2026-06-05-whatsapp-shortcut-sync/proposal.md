# Proposal: WhatsApp Shortcut Sync

## Intent

The WhatsApp shortcut button in the admin navbar requires manual phone number entry via `config_bot.json.bot_phone`. The number is already available from the active Evolution instance's `ownerJid` field (format `{phone}@s.whatsapp.net`). Eliminating the manual config removes a redundant step and prevents stale numbers when instances change.

## Scope

### In Scope
- Extract phone from active instance's `ownerJid` (`{phone}@s.whatsapp.net` → phone digits)
- Auto-populate `$store.app.botPhone` from instance data on load and on instance swap
- Disable the button (greyed out, tooltip) when no active instance or `ownerJid` is null
- Remove `bot_phone` field from `config_bot.json` defaults and `ConfigManager.guardar()` signature
- Remove the phone input field from the config tab in the admin UI
- Update the existing `whatsapp-link/spec.md` to reflect new behavior

### Out of Scope
- Multiple instance management
- Phone number format validation
- WhatsApp Web integration beyond `wa.me` link
- Evolution API response format changes

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `whatsapp-link`: Remove manual `bot_phone` config requirement. Button now reads phone from active Evolution instance's `ownerJid`. Disabled state when instance disconnected or `ownerJid` is null.

## Approach

**No new endpoint needed.** The `/api/evolution/instances` endpoint already returns `ownerJid` per instance. The frontend `instances.js` already loads this data.

1. **Backend** (`ConfigManager.py`): Remove `bot_phone` from default config dict, remove `nuevo_bot_phone` parameter from `guardar()`, remove `setdefault("bot_phone", "")`.
2. **Backend** (`interface.py`): Remove `bot_phone` from `guardar_config()` form params and the `guardar()` call. Remove `bot_phone` from `GET /api/config` response.
3. **Frontend** (`instances.js`): In `loadInstances()`, after loading instances and active name, find the active instance, extract phone from `ownerJid` (`split("@")[0]`), and set `Alpine.store('app').botPhone`.
4. **Frontend** (`app.js`): Remove `configBotPhone` state and its load/save logic. Remove `bot_phone` from `saveContactConfig()` FormData.
5. **Frontend** (`index.html`): Remove the bot phone input field from the config tab.
6. **Frontend** (`store.js`): No change — `botPhone` stays in the Alpine store, now populated by `instances.js`.

**Phone extraction**: `ownerJid` format is `5491112345678@s.whatsapp.net`. Split on `@`, take index 0. If `ownerJid` is null/empty, button stays disabled.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `chatbotW/src/ConfigManager.py` | Modified | Remove `bot_phone` from defaults and `guardar()` |
| `chatbotW/src/interface.py` | Modified | Remove `bot_phone` from config endpoint |
| `chatbotW/src/static/js/instances.js` | Modified | Set `botPhone` store from active instance `ownerJid` |
| `chatbotW/src/static/js/app.js` | Modified | Remove `configBotPhone` state and save logic |
| `chatbotW/src/index.html` | Modified | Remove phone input from config tab |
| `openspec/specs/whatsapp-link/spec.md` | Modified | Update specs to reflect auto-sync behavior |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `ownerJid` is null for disconnected instances | High | Button disables with tooltip (existing pattern) |
| Stale `ownerJid` after instance swap | Low | `loadInstances()` already refreshes on swap |
| Users with custom `bot_phone` lose the override | Low | Accept tradeoff; the number should come from the connected instance |

## Rollback Plan

Revert the six changed files. Restoring `bot_phone` to `ConfigManager`, `interface.py`, `app.js`, and `index.html` re-enables manual config. No database migration involved.

## Dependencies

- Evolution API `ownerJid` field (already used in `InstanceInfo` model and rendered in instances table)

## Success Criteria

- [ ] WhatsApp button shows the active instance's phone number automatically
- [ ] Button is greyed out with tooltip when no active instance or `ownerJid` is null
- [ ] No `bot_phone` field in config tab or `config_bot.json`
- [ ] Button updates when switching active instances (without page reload)
