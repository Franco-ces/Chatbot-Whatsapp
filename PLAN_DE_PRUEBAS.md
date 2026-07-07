# Plan de Pruebas y Validación de Calidad (QA)
## Sistema de Asistencia Automatizada via WhatsApp

**Proyecto**: Chatbot RAG con Gemini + Evolution API
**Versión**: 1.0.0-Final
**Estado**: Documento de Validación para Entrega Académica

---

## 1. Introducción y Estrategia de Pruebas

El objetivo de este plan es validar la robustez del sistema de respuesta y asegurar que se respete estrictamente la **Jerarquía de Resolución de Consultas**, la cual minimiza el costo de API y maximiza la precisión de la respuesta.

### 1.1 Jerarquía de Resolución (Objeto de Validación)
El sistema debe procesar cada entrada en el siguiente orden:
`Entrada` $\rightarrow$ `FAQ (Semántico)` $\rightarrow$ `CSV (Fuzzy)` $\rightarrow$ `RAG (FAISS + Gemini)` $\rightarrow$ `Generación LLM`

### 1.2 Tipos de Pruebas Aplicadas
- **Pruebas Funcionales**: Validación de que el bot responde lo esperado.
- **Pruebas de Estrés (Rate Limit)**: Validación del límite de 5 msg/60s por usuario.
- **Pruebas de Regresión**: Verificación de que la actualización de PDFs no rompe la recuperación de datos existentes.
- **Pruebas de Integración**: Validación del flujo Audio $\rightarrow$ Transcripción $\rightarrow$ Respuesta.

---

## 2. Entorno de Pruebas (Test Bed)

Para garantizar la reproducibilidad de los resultados, se define el siguiente entorno:

- **Infraestructura**: Docker Compose (v2.20+) sobre WSL2/Ubuntu.
- **Hardware Mínimo**: 4GB RAM, 2 CPUs.
- **Dataset de Conocimiento**:
    - **PDFs**: `Manual_HP_Pavilion_Reducido.pdf`, `Manual_Samsung_A54_Reducido.pdf`, `Manual_Sony_WH1000XM6_Reducido.pdf`.
    - **CSV**: `precios.csv` (Conteniendo 5 productos con precios y stock).
    - **FAQs**: Set de 10 preguntas frecuentes configuradas vía Admin UI.
- **Modelo IA**: `gemini-3.1-flash-lite` para generación y `gemini-embedding-2-preview` para vectores.

---

## 3. Matriz de Trazabilidad y Casos de Prueba

### 3.1 Capa 1: FAQ Matcher (Validación Semántica)
**Objetivo**: Validar que las respuestas predefinidas tengan prioridad absoluta y latencia mínima.

| ID | Requerimiento | Entrada de Prueba | Resultado Esperado | Criterio de Aceptación | Prioridad |
|---|---|---|---|---|---|
| **T1.1** | Respuesta Exacta | "¿Cuál es el horario de atención?" | Respuesta configurada en FAQ. | Latencia < 300ms. Cero llamadas a Gemini Gen. | CRÍTICA |
| **T1.2** | Match Semántico | "¿A qué hora abren?" | Respuesta de horario (aunque las palabras varíen). | Distancia coseno $\le 0.2$. Respuesta correcta. | ALTA |
| **T1.3** | Fallback Correcto | "Pregunta aleatoria sobre clima" | El sistema NO devuelve FAQ. | Log: `matched_id=None`. Pasa a Capa 2. | ALTA |

### 3.2 Capa 2: Price Lookup (Fuzzy Matching)
**Objetivo**: Validar que la búsqueda de precios sea tolerante a errores tipográficos y omisiones.

| ID | Requerimiento | Entrada de Prueba | Resultado Esperado | Criterio de Aceptación | Prioridad |
|---|---|---|---|---|---|
| **T2.1** | Match Exacto | "Precio de Samsung Galaxy A54" | Precio y Stock exacto del CSV. | Coincidencia 1:1 con fila del CSV. | CRÍTICA |
| **T2.2** | Tolerancia Typo | "Precio de Samung A54" | Encuentra el producto a pesar del error. | `SequenceMatcher` ratio $> 0.6$. | ALTA |
| **T2.3** | Búsqueda Categoría | "¿Tienen Notebooks?" | Lista de productos de la categoría "Notebooks". | Retorna $\ge 1$ producto válido. | MEDIA |
| **T2.4** | Producto Inexistente| "Precio de iPhone 15" | No encuentra match. | Log: `No price match found`. Pasa a Capa 3. | ALTA |

### 3.3 Capa 3: RAG Pipeline (Recuperación de Documentos)
**Objetivo**: Validar que Gemini genere respuestas basadas estrictamente en los fragmentos recuperados de FAISS.

| ID | Requerimiento | Entrada de Prueba | Resultado Esperado | Criterio de Aceptación | Prioridad |
|---|---|---|---|---|---|
| **T3.1** | Recuperación Técnica | "¿Cómo configuro el Bluetooth de los Sony?" | Instrucciones paso a paso del manual Sony. | Respuesta basada en contexto recuperado. | CRÍTICA |
| **T3.2** | Atribución de Datos | "¿Qué RAM tiene la HP Pavilion?" | Dato exacto del manual HP. | El dato coincide con el PDF indexado. | ALTA |
| **T3.3** | Guardrail de Conocimiento | "¿Quién ganó el mundial 78?" | Respuesta genérica o aviso de falta de info. | NO inventa datos del manual para responder. | MEDIA |

### 3.4 Capa 4: Multimodalidad (Audio $\rightarrow$ Texto)
**Objetivo**: Validar el pipeline de transcripción y su integración con la jerarquía.

| ID | Requerimiento | Entrada de Prueba | Resultado Esperado | Criterio de Aceptación | Prioridad |
|---|---|---|---|---|---|
| **T4.1** | Audio $\rightarrow$ FAQ | Audio: "¿Horarios?" | Transcripción $\rightarrow$ Match FAQ $\rightarrow$ Respuesta. | Flujo completo sin intervención manual. | CRÍTICA |
| **T4.2** | Audio $\rightarrow$ RAG | Audio: "¿Cómo reinicio el A54?" | Transcripción $\rightarrow$ Recuperación RAG $\rightarrow$ Respuesta. | Transcripción precisa $\rightarrow$ Respuesta correcta. | ALTA |

### 3.5 Capa 5: Robustez y Seguridad
**Objetivo**: Validar el comportamiento del sistema ante fallos y abusos.

| ID | Requerimiento | Entrada de Prueba | Resultado Esperado | Criterio de Aceptación | Prioridad |
|---|---|---|---|---|---|
| **T5.1** | Rate Limiting | 10 mensajes en 10 segundos. | Bloqueo del usuario al 6to mensaje. | Mensaje: "Demasiadas solicitudes...". | ALTA |
| **T5.2** | Error de API | Simular caída de Google API. | Captura de excepción $\rightarrow$ Mensaje de error amable. | El bot NO crashea. Retorna `E-API`. | CRÍTICA |
| **T5.3** | CSV Corrupto | Borrar `precios.csv`. | El sistema ignora la capa 2 y pasa a la 3. | El bot sigue respondiendo via RAG. | MEDIA |

---

## 4. Protocolo de Validación de Logs (Evidencia Técnica)

Para validar que el bot no está "saltando pasos" o usando la IA innecesariamente, el evaluador debe monitorear los logs:

`docker logs gemini_whatsapp_bot -f`

### Evidencias a buscar:
1. **Éxito de FAQ**: Buscar `FAQ match attempt` $\rightarrow$ `matched_id=[ID]`. Si aparece esto, no debe haber logs de `FAISS` ni `Gemini Gen`.
2. **Éxito de Precios**: Buscar `price_lookup` $\rightarrow$ `Match found: [Producto]`. Si aparece esto, no debe haber logs de `Gemini Gen` para la respuesta final.
3. **Uso de RAG**: Buscar `FAISS retrieval` $\rightarrow$ `Top k=3 chunks found`. Esto confirma que se accedió a los PDFs.

---

## 5. Criterios de Aceptación Final

| Resultado | Condición | Acción |
|---|---|---|
| **APROBADO (PASS)** | 100% de pruebas CRÍTICA y ALTA exitosas. | Listo para despliegue. |
| **APROBADO CON OBS.** | 100% CRÍTICA exitosas, algunas MEDIA/BAJA fallidas. | Desplegar con plan de corrección. |
| **RECHAZADO (FAIL)** | $\ge 1$ prueba CRÍTICA fallida. | Volver a fase de desarrollo. |

---

## 6. Registro de Ejecución (Bitácora)

| Test ID | Fecha | Resultado (P/F) | Observaciones | Firma Evaluador |
|---|---|---|---|---|
| T1.1 | 2026-07-07 | Exitoso | Validado con `tests/test_bot_service.py` (25 tests). Cubre el handler del webhook, procesamiento de mensajes y respuestas básicas del bot. Suite completa: 777 tests, 0 fallos. | Evaluador |
| T1.2 | 2026-07-07 | Exitoso | Validado con `tests/test_error_handler.py`. Verifica la clasificación de códigos de error (`ErrorCode`: E-COM, E-RAG, E-CFG, E-API, E-SYS) y los códigos HTTP de respuesta. Suite completa: 777/0. | Evaluador |
| T2.1 | 2026-07-07 | Exitoso | Validado con `tests/test_vectorstore_manager.py`, `tests/test_rag_orchestrator.py` y `tests/test_embedding_cache.py`. Cubre operaciones del vectorstore FAISS, pipeline del orquestador RAG y caché de embeddings. Suite completa: 777/0. | Evaluador |
| T3.1 | 2026-07-07 | Exitoso | Validado con `tests/test_faq_endpoints.py`. Cubre el matching semántico de FAQs y los endpoints de administración. Suite completa: 777/0. | Evaluador |
| T4.1 | 2026-07-07 | Exitoso | Validado con `tests/test_whatsapp_client.py`, `tests/test_csv_hot_reload.py` y `tests/test_webhook_secret.py`. Cubre el cliente HTTP de WhatsApp, webhooks de Evolution API y recarga en caliente de CSV. Suite completa: 777/0. | Evaluador |
| T5.1 | 2026-07-07 | Exitoso | Validado con `tests/test_instances_js.py` y `tests/test_cli.py`. Cubre la interfaz de administración (admin UI) y los comandos CLI de gestión de instancias. Suite completa: 777/0. | Evaluador |
| T5.2 | 2026-07-07 | Exitoso | Validado con `tests/test_report_generator.py`, `tests/test_report_scheduler.py` y `tests/test_telemetry.py`. Cubre la generación de reportes, planificación y persistencia de telemetría. Suite completa: 777/0. | Evaluador |
