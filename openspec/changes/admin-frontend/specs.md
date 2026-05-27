# Admin Frontend — Combined Specification

All capabilities are NEW (no existing specs). Each domain is a full specification.

---

## 1. admin-auth

**Purpose**: JWT authentication protecting the admin panel.

| Req | Statement | Strength |
|-----|-----------|----------|
| A1 | POST /api/auth/login accepts {username, password}, returns {token}. Creds from ADMIN_USER/ADMIN_PASS env. | MUST |
| A2 | JWT MUST include exp (24h), signed HS256 with SECRET_KEY from env. | MUST |
| A3 | AuthMiddleware MUST guard ALL /api/* routes except /api/auth/login. | MUST |
| A4 | Frontend MUST hide all content and render only login form if no valid token. | MUST |
| A5 | Logout SHOULD remove token from localStorage and redirect to login. | SHOULD |

#### Scenarios

- GIVEN valid creds WHEN POST /api/auth/login THEN 200 + JWT
- GIVEN wrong password WHEN POST /api/auth/login THEN 401
- GIVEN no token WHEN GET /api/pdfs THEN 401
- GIVEN expired JWT WHEN GET /api/pdfs THEN 401
- GIVEN no token on page load THEN only login form visible

---

## 2. csv-manager

**Purpose**: CRUD + inline editing for CSV files in chatbotW/CSVs/.

| Req | Statement | Strength |
|-----|-----------|----------|
| C1 | GET /api/csvs lists .csv files in CSVs/ dir. | MUST |
| C2 | POST /api/csvs accepts multipart upload (single/multiple). | MUST |
| C3 | DELETE /api/csvs/{filename} removes file or 404. | MUST |
| C4 | GET /api/csvs/{filename} returns file download. | MUST |
| C5 | GET /api/csvs/{filename}/data returns {headers, rows} parsed. | MUST |
| C6 | PUT /api/csvs/{filename}/data accepts {headers, rows} and overwrites file. | MUST |
| C7 | Frontend renders editable table with Alpine.js x-model on cells. | MUST |
| C8 | Frontend SHOULD confirm before discarding unsaved edits. | SHOULD |

#### Scenarios

- GIVEN 2 CSVs in dir WHEN GET /api/csvs THEN 200 with list
- GIVEN valid CSV WHEN GET /api/csvs/{f}/data THEN {headers, rows}
- GIVEN edited cell WHEN PUT with new data THEN file updated on disk
- GIVEN unsaved edits WHEN navigating away THEN confirm() dialog

---

## 3. log-viewer-enhanced

**Purpose**: Log viewer with phone-number filtering, preserving WhatsApp bubbles.

| Req | Statement | Strength |
|-----|-----------|----------|
| L1 | GET /api/logs lists .txt files excluding temp_ prefix. | MUST |
| L2 | GET /api/logs/{filename} returns full raw content. | MUST |
| L3 | GET /api/logs/{filename}?phone=X filters lines by display_name. | MUST |
| L4 | Frontend extracts unique phone numbers into filter dropdown. | MUST |
| L5 | Filter shows only matching user messages + adjacent bot replies. | MUST |
| L6 | Old format (no |||) renders as gray system bubbles. | MUST |
| L7 | WhatsApp bubble styling preserved (user right/green, bot left/white). | MUST |

#### Scenarios

- GIVEN phone "54911..." selected THEN only that conversation visible
- GIVEN old-format log line THEN renders as centered gray bubble
- GIVEN no phone filter THEN all messages shown as-before

---

## 4. whatsapp-link

**Purpose**: wa.me link from the bot's configured phone number.

| Req | Statement | Strength |
|-----|-----------|----------|
| W1 | config_bot.json includes bot_phone field. | MUST |
| W2 | GET /api/config returns bot_phone alongside existing fields. | MUST |
| W3 | Frontend config section includes bot_phone input. | MUST |
| W4 | Navbar shows "Abrir WhatsApp" link to https://wa.me/{bot_phone}. | MUST |
| W5 | Link opens in new tab (target="_blank"). | MUST |

#### Scenarios

- GIVEN bot_phone=5491112345678 THEN link is wa.me/5491112345678
- GIVEN no bot_phone set THEN link hidden or disabled

---

## 5. General UI

| Req | Statement | Strength |
|-----|-----------|----------|
| G1 | Navbar with: title, WhatsApp link, logout button. | MUST |
| G2 | Tabs: Documentos (PDFs+CSVs), Logs, Configuración. | MUST |
| G3 | Loading states (spinner/skeleton) on all async operations. | MUST |
| G4 | Toast/inline messages for success/error feedback. | MUST |
| G5 | Responsive layout via Tailwind CDN. | MUST |
| G6 | No valid token → render login form ONLY. | MUST |

#### Scenarios

- GIVEN async operation in-flight THEN loading indicator visible
- GIVEN failed upload THEN red error message displayed
- GIVEN mobile viewport THEN layout adapts via Tailwind responsive classes
