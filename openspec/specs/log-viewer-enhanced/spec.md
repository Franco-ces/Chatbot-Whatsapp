# log-viewer-enhanced Specification

## Purpose

Enhanced chat log viewer with phone-number filtering, preserving the existing WhatsApp-bubble rendering for conversations.

## Requirements

### Requirement: List Log Files

The system MUST list all `.txt` log files (excluding `temp_` prefix) via `GET /api/logs`.

#### Scenario: Logs exist

- GIVEN `chat_wpp_2024-01-01.txt` exists
- WHEN `GET /api/logs`
- THEN response is `200` with `{"logs": ["chat_wpp_2024-01-01.txt"]}`

### Requirement: Read Log with Phone Filter

The system MUST filter log content by phone number when `?phone=` query param is provided. Must return only lines matching that phone (as `display_name` in the `|||` format) AND bot responses immediately following those messages.

#### Scenario: Filter by phone

- GIVEN a log with messages from `549111234` and `549115678`
- WHEN `GET /api/logs/chat.txt?phone=549111234`
- THEN response contains only lines where `display_name` is `549111234` plus subsequent bot replies

#### Scenario: No phone filter

- WHEN `GET /api/logs/chat.txt` without `?phone`
- THEN response contains the full file content

#### Scenario: Phone with no matches

- WHEN `GET /api/logs/chat.txt?phone=999`
- THEN response is `200` with empty or minimal filtered content

### Requirement: Frontend Phone Filter Dropdown

The frontend MUST extract unique phone numbers from the loaded log and show them as a filter dropdown.

#### Scenario: Populate filter

- GIVEN a log contains messages from `549111234` and `549115678`
- WHEN the log loads
- THEN the filter dropdown shows "Todos", "549111234", "549115678"

#### Scenario: Apply filter

- WHEN the user selects "549111234" from the dropdown
- THEN only messages from that user and corresponding bot replies are visible in the viewer

### Requirement: Backward-Compatible Parsing

The system MUST render old-format log lines (pre-`|||` delimiter) as system messages in gray bubbles.

#### Scenario: Old format line

- GIVEN a log line `Chat iniciado el 01/01/2024`
- WHEN the log is rendered
- THEN the line appears as a centered gray system bubble

### Requirement: WhatsApp Bubble Rendering

The system MUST preserve the existing WhatsApp-style bubble layout: user messages right-aligned in green (`#dcf8c6`), bot messages left-aligned in white, with display name and timestamp.

#### Scenario: User message render

- GIVEN a `|||` line with `internal_id=id_usuario`
- WHEN rendered
- THEN the bubble is right-aligned with green background

#### Scenario: Bot message render

- GIVEN a `|||` line with `internal_id=id_bot`
- WHEN rendered
- THEN the bubble is left-aligned with white background
