# WhatsApp Link Specification

## Purpose

The WhatsApp shortcut button in the admin navbar opens a `wa.me` chat link. It requires a phone number to construct the link. This spec defines how the phone number is sourced from the active Evolution instance and how the button behaves when no number is available.

## Requirements

### Requirement: Phone Number Source

The WhatsApp button MUST derive its phone number from the active Evolution instance's `ownerJid` field. The phone number MUST be extracted by splitting `ownerJid` on `@` and taking the leading digits (e.g., `5491112345678@s.whatsapp.net` → `5491112345678`).

#### Scenario: Active instance has ownerJid

- GIVEN an active Evolution instance exists with `ownerJid` = `5491112345678@s.whatsapp.net`
- WHEN the admin panel loads or the active instance changes
- THEN `$store.app.botPhone` SHALL be set to `5491112345678`
- AND the WhatsApp button SHALL construct a valid `wa.me/5491112345678` link

#### Scenario: Active instance has null ownerJid

- GIVEN an active Evolution instance exists but `ownerJid` is null (disconnected)
- WHEN the admin panel loads or the active instance changes
- THEN `$store.app.botPhone` SHALL be set to an empty string
- AND the WhatsApp button SHALL be disabled

#### Scenario: No active instance

- GIVEN no active Evolution instance is configured
- WHEN the admin panel loads
- THEN `$store.app.botPhone` SHALL be set to an empty string
- AND the WhatsApp button SHALL be disabled

### Requirement: Button Disabled State

The WhatsApp button MUST be visually disabled (greyed out, non-interactive) and display a tooltip when no phone number is available. The tooltip SHOULD explain that no active instance or connected session exists.

#### Scenario: Button disabled with no phone

- GIVEN `$store.app.botPhone` is an empty string
- WHEN the admin renders the navbar
- THEN the WhatsApp button SHALL have a disabled visual state
- AND the button SHALL NOT navigate to `wa.me` on click
- AND a tooltip SHALL indicate the instance is disconnected or inactive

#### Scenario: Button enabled with phone

- GIVEN `$store.app.botPhone` is a non-empty string (e.g., `5491112345678`)
- WHEN the admin renders the navbar
- THEN the WhatsApp button SHALL be enabled and clickable
- AND clicking the button SHALL open `https://wa.me/{botPhone}` in a new tab

### Requirement: Phone Sync on Instance Change

The phone number MUST update automatically when the admin switches the active Evolution instance, without requiring a page reload.

#### Scenario: Instance swap updates phone

- GIVEN instance A is active with `ownerJid` = `5491111111111@s.whatsapp.net`
- AND the WhatsApp button shows phone `5491111111111`
- WHEN the admin activates instance B with `ownerJid` = `5492222222222@s.whatsapp.net`
- THEN `$store.app.botPhone` SHALL update to `5492222222222`
- AND the WhatsApp button link SHALL change to `https://wa.me/5492222222222`

#### Scenario: Instance deactivation clears phone

- GIVEN instance A is active with a valid `ownerJid`
- WHEN the admin deactivates instance A (no active instance remains)
- THEN `$store.app.botPhone` SHALL be set to an empty string
- AND the WhatsApp button SHALL become disabled

### Requirement: Remove Manual bot_phone Config

The `bot_phone` field MUST be removed from `config_bot.json` defaults, the `ConfigManager.guardar()` signature, and the admin config UI. No manual phone input SHALL be exposed to the operator.

#### Scenario: bot_phone absent from config

- GIVEN a fresh `config_bot.json` is created
- WHEN the file is read
- THEN it SHALL NOT contain a `bot_phone` key
- AND `ConfigManager.guardar()` SHALL NOT accept a `nuevo_bot_phone` parameter

#### Scenario: Config endpoint excludes bot_phone

- GIVEN the admin calls `GET /api/config`
- WHEN the response is returned
- THEN the response SHALL NOT contain a `bot_phone` field
