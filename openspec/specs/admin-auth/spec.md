# admin-auth Specification

## Purpose

JWT-based authentication for the admin panel. Protects all API endpoints and restricts frontend access to authenticated users only.

## Requirements

### Requirement: User Login

The system MUST authenticate via `POST /api/auth/login` accepting `{username, password}` and returning `{token}`. Credentials MUST be read from `ADMIN_USER` and `ADMIN_PASS` env vars.

#### Scenario: Successful login

- GIVEN `ADMIN_USER=admin` and `ADMIN_PASS=secret123` in `.env`
- WHEN `POST /api/auth/login` with `{"username": "admin", "password": "secret123"}`
- THEN response is `200` with `{"token": "<JWT>"}`
- AND the JWT contains `exp` claim 24h from now, signed with HS256

#### Scenario: Invalid credentials

- GIVEN `ADMIN_USER=admin` and `ADMIN_PASS=secret123` in `.env`
- WHEN `POST /api/auth/login` with wrong password
- THEN response is `401` with `{"detail": "Credenciales inválidas"}`

#### Scenario: Missing fields

- WHEN `POST /api/auth/login` without username or password
- THEN response is `422`

### Requirement: Auth Middleware

The system MUST protect all `/api/*` routes with a middleware that validates the Bearer JWT. The only exception is `POST /api/auth/login`.

#### Scenario: Protected endpoint with valid token

- GIVEN a valid JWT token
- WHEN `GET /api/pdfs` with `Authorization: Bearer <token>`
- THEN response is `200` with the PDF list

#### Scenario: Protected endpoint without token

- GIVEN no `Authorization` header
- WHEN `GET /api/pdfs`
- THEN response is `401` with `{"detail": "No autenticado"}`

#### Scenario: Expired token

- GIVEN an expired JWT
- WHEN `GET /api/pdfs` with `Authorization: Bearer <expired_token>`
- THEN response is `401` with `{"detail": "Token expirado"}`

#### Scenario: Malformed token

- GIVEN an invalid JWT string
- WHEN `GET /api/pdfs` with `Authorization: Bearer <invalid>`
- THEN response is `401`

### Requirement: Frontend Route Guard

The frontend MUST show the login form when no valid token exists, and MUST NOT render any admin content.

#### Scenario: No token on page load

- GIVEN no token in `localStorage`
- WHEN the page loads
- THEN only the login form is visible
- AND no admin sections are rendered

#### Scenario: Logout

- GIVEN an authenticated session
- WHEN the user clicks "Cerrar sesión"
- THEN the token is removed from `localStorage`
- AND the page redirects to the login form
