# general-ui Specification

## Purpose

Shared UI structure and behavior across the entire admin panel: navigation, tabs, loading states, error handling, responsive layout.

## Requirements

### Requirement: Navbar

The frontend MUST render a persistent navbar/header with the panel title, a WhatsApp link, and a logout button when authenticated.

#### Scenario: Authenticated navbar

- GIVEN a valid JWT token
- WHEN the page renders
- THEN the navbar is visible at the top with: title, "Abrir WhatsApp" link, "Cerrar sesión" button

### Requirement: Tab Navigation

The frontend MUST provide tab navigation between Documentos (PDFs + CSVs), Logs, and Configuración sections.

#### Scenario: Switch tabs

- GIVEN the user is on the Configuración tab
- WHEN the user clicks "Logs"
- THEN the Configuración section hides and the Logs section shows
- AND the active tab is visually highlighted

### Requirement: Loading States

The frontend MUST show a loading indicator (spinner or skeleton) during all async fetch operations.

#### Scenario: Loading during fetch

- GIVEN the user clicks "Cargar" to upload a file
- WHEN the upload request is in-flight
- THEN a spinner or "⏳ Cargando..." message is visible
- AND the submit button is disabled

### Requirement: Error/Success Feedback

The frontend MUST display success (green) and error (red) messages for all operations. Messages SHOULD auto-dismiss after 3 seconds.

#### Scenario: Success feedback

- GIVEN a file upload completes successfully
- THEN a green success message appears
- AND it disappears after 3 seconds

#### Scenario: Error feedback

- GIVEN a network failure during an API call
- THEN a red error message is shown
- AND it disappears after 3 seconds

### Requirement: Responsive Layout

The layout MUST adapt to mobile viewports using Tailwind CDN responsive classes.

#### Scenario: Mobile viewport

- GIVEN the viewport is 375px wide
- THEN the layout stacks vertically, tabs are full-width, and content is readable without horizontal scroll

### Requirement: Route Protection

The frontend MUST show only the login form when no valid JWT token exists. No admin content MUST be accessible.

#### Scenario: Unauthenticated view

- GIVEN no token in localStorage
- WHEN the page loads
- THEN only the login form is rendered
- AND tabs, navbar, and admin content are hidden
