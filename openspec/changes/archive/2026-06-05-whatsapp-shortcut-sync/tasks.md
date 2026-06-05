# Tasks: WhatsApp Shortcut Sync

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~30 (15 deletions, 15 modifications) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Backend — Remove `bot_phone` from ConfigManager

- [x] 1.1 Remove `"bot_phone": ""` from `ConfigManager.__init__` defaults dict (L50) in `src/ConfigManager.py`
- [x] 1.2 Remove `self.config.setdefault("bot_phone", "")` in `cargar()` (L67) in `src/ConfigManager.py`
- [x] 1.3 Remove fallback dict entry `"bot_phone": ""` in `cargar()` exception handler (L63) in `src/ConfigManager.py`
- [x] 1.4 Remove `nuevo_bot_phone` parameter and its assignment block from `guardar()` (L77-84) in `src/ConfigManager.py`
- [x] 1.5 Remove `bot_phone` form param and `guardar()` kwarg from `guardar_config()` endpoint (L156-158) in `src/interface.py`

## Phase 2: Frontend — Wire phone from Evolution instances

- [x] 2.1 In `instances.js`, add phone extraction after `loadInstances()`: find active instance, extract phone from `ownerJid` via `split("@")[0]`, set `Alpine.store('app').botPhone`. Handle null `ownerJid` gracefully (empty string).
- [x] 2.2 In `app.js`, remove `configBotPhone` state property (L29) in `adminPanel`
- [x] 2.3 In `app.js`, remove `this.configBotPhone = data.bot_phone || ''` from `loadContactConfig()` (L119)
- [x] 2.4 In `app.js`, remove `Alpine.store('app').botPhone = this.configBotPhone` from `loadContactConfig()` (L120) — now handled by instances.js
- [x] 2.5 In `app.js`, remove `formData.append("bot_phone", this.configBotPhone)` from `saveContactConfig()` (L134)
- [x] 2.6 In `app.js`, remove `Alpine.store('app').botPhone = this.configBotPhone` from `saveContactConfig()` (L142)

## Phase 3: HTML — Remove phone input, update button state

- [x] 3.1 Remove the phone input field block (L143-147) from config tab in `src/index.html`
- [x] 3.2 Update navbar button tooltip from `'Configurá el número del bot'` to `'Instancia no conectada o sin número'` (L81) in `src/index.html`
- [x] 3.3 Verify button `:disabled` and `:class` bindings work with `instances.js` populating `$store.app.botPhone` — no change needed, existing logic already handles empty/falsy botPhone

## Phase 4: Testing

- [x] 4.1 Add test: `ConfigManager.guardar()` called without `nuevo_bot_phone` — verify `bot_phone` not written
- [x] 4.2 Add test: phone extraction from `ownerJid` values (valid `"5491112345678@s.whatsapp.net"` → `"5491112345678"`, null → `""`, empty → `""`)
- [x] 4.3 Add test: `GET /api/config` response no longer contains `bot_phone` key
- [x] 4.4 Add test: `POST /api/config` with `bot_phone` param does not crash (param ignored)
- [x] 4.5 Run full test suite: `pytest` — confirm no regressions

## Phase 5: Cleanup

- [x] 5.1 Remove stale `bot_phone` key from `config_bot.json` default config (manual or auto on next save — no code action required, just verify)
