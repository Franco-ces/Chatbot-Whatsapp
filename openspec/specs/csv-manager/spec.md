# csv-manager Specification

## Purpose

CRUD operations over CSV knowledge-base files with inline cell editing. Files stored in `chatbotW/CSVs/`.

## Requirements

### Requirement: List CSV Files

The system MUST list all `.csv` files in `chatbotW/CSVs/` via `GET /api/csvs`.

#### Scenario: Directory has files

- GIVEN `chatbotW/CSVs/` contains `products.csv` and `faq.csv`
- WHEN `GET /api/csvs`
- THEN response is `200` with `{"csvs": ["products.csv", "faq.csv"]}`

#### Scenario: Empty directory

- GIVEN `chatbotW/CSVs/` is empty
- WHEN `GET /api/csvs`
- THEN response is `200` with `{"csvs": []}`

### Requirement: Upload CSV

The system MUST accept file uploads via `POST /api/csvs` (multipart, single or multiple files).

#### Scenario: Single file upload

- GIVEN a valid `products.csv` file
- WHEN `POST /api/csvs` with `files` containing the file
- THEN response is `200` with success message
- AND `products.csv` exists in `chatbotW/CSVs/`

#### Scenario: Multiple file upload

- WHEN `POST /api/csvs` with two files
- THEN both files are saved

### Requirement: Delete CSV

The system MUST delete a CSV file via `DELETE /api/csvs/{filename}`.

#### Scenario: Delete existing file

- GIVEN `products.csv` exists
- WHEN `DELETE /api/csvs/products.csv`
- THEN response is `200`
- AND the file is removed

#### Scenario: Delete non-existent file

- WHEN `DELETE /api/csvs/nonexistent.csv`
- THEN response is `404`

### Requirement: Download CSV

The system MUST serve a CSV file via `GET /api/csvs/{filename}`.

#### Scenario: Download existing file

- GIVEN `products.csv` exists
- WHEN `GET /api/csvs/products.csv`
- THEN response is `200` with `Content-Type: text/csv`
- AND the file content matches the stored file

### Requirement: Read CSV Data

The system MUST return parsed CSV content as JSON via `GET /api/csvs/{filename}/data`.

#### Scenario: Parse valid CSV

- GIVEN `products.csv` with headers `name,price` and one row `Widget,10`
- WHEN `GET /api/csvs/products.csv/data`
- THEN response is `200` with `{"headers": ["name", "price"], "rows": [["Widget", "10"]]}`

### Requirement: Write CSV Data

The system MUST overwrite a CSV file with new data via `PUT /api/csvs/{filename}/data`.

#### Scenario: Save edits

- GIVEN `products.csv` exists with `name,price\nWidget,10`
- WHEN `PUT /api/csvs/products.csv/data` with `{"headers": ["name","price"], "rows": [["Widget","15"]]}`
- THEN response is `200`
- AND the file now contains `Widget,15`

### Requirement: Inline Editable Table (Frontend)

The frontend MUST render CSV data as an editable HTML table using Alpine.js `x-model` on each cell.

#### Scenario: Render and edit

- GIVEN the user opens the CSV editor for `products.csv`
- THEN the table shows headers and rows as input fields
- WHEN the user changes a cell value and clicks "Guardar"
- THEN `PUT /api/csvs/products.csv/data` is called with updated data

### Requirement: Confirm Before Discard

The frontend SHOULD show a confirmation dialog when the user tries to leave the CSV editor with unsaved changes.

#### Scenario: Unsaved changes

- GIVEN the user has edited a cell
- WHEN the user clicks a different tab
- THEN a `confirm()` dialog appears asking "Hay cambios sin guardar. ¿Descartar?"
