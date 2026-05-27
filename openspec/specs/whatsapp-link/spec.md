# whatsapp-link Specification

## Purpose

Provide a direct clickable link to chat with the bot on WhatsApp from the admin panel.

## Requirements

### Requirement: bot_phone Configuration

The system MUST support a `bot_phone` field in `config_bot.json` that stores the bot's WhatsApp number (without `+` or special chars, just digits).

#### Scenario: Config has bot_phone

- GIVEN `config_bot.json` contains `{"bot_phone": "5491112345678"}`
- WHEN `GET /api/config`
- THEN response includes `"bot_phone": "5491112345678"` alongside existing fields

#### Scenario: Config without bot_phone

- GIVEN `config_bot.json` has no `bot_phone` field
- WHEN `GET /api/config`
- THEN response omits `bot_phone` or returns `null`

### Requirement: Update bot_phone via Frontend

The system MUST allow updating `bot_phone` via the config section in the admin panel.

#### Scenario: Save bot phone

- GIVEN the config tab shows a `bot_phone` input field
- WHEN the user enters `5491112345678` and clicks "Guardar"
- THEN `config_bot.json` is updated
- AND the WhatsApp link reflects the new number

### Requirement: WhatsApp Link in Navbar

The frontend MUST render a clickable link in the navbar/header that opens `https://wa.me/{bot_phone}` in a new tab.

#### Scenario: Link renders

- GIVEN `bot_phone` is `5491112345678`
- THEN the navbar contains `<a href="https://wa.me/5491112345678" target="_blank">Abrir WhatsApp</a>`

#### Scenario: Link visible from any tab

- GIVEN the user is on the Logs, Docs, or Config tab
- THEN the WhatsApp link is always visible in the navbar

#### Scenario: No bot_phone configured

- GIVEN `bot_phone` is not set
- THEN the WhatsApp link is hidden or shows a disabled state
