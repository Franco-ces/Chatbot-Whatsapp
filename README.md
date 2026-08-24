# Neuradocs — Chatbot de WhatsApp con RAG (Gemini + Evolution API)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/Franco-ces/Chatbot-Whatsapp/actions/workflows/ci.yml/badge.svg)](https://github.com/Franco-ces/Chatbot-Whatsapp/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

[English](README.en.md)

Neuradocs es un sistema de respuesta automatizada para WhatsApp basado en la arquitectura **RAG (Retrieval-Augmented Generation)**. El sistema permite la consulta de bases de conocimiento almacenadas en documentos PDF y archivos CSV locales, procesando entradas de texto y audio de voz mediante el modelo Gemini de Google.

La solución se encuentra totalmente contenedorizada mediante **Docker**, asegurando la portabilidad y la consistencia del entorno de ejecución.

---

## 🛠️ Guía de Instalación y Despliegue

El sistema ha sido diseñado para un despliegue simplificado, donde la configuración de la instancia de comunicación se realiza directamente desde la interfaz administrativa.

### 📋 Prerrequisitos

Es necesario contar con la siguiente infraestructura instalada y corriendo:
* **Docker Desktop** (incluyendo Docker Compose).
  * [Documentación oficial de Docker](https://www.docker.com/products/docker-desktop/)

---

### 📥 1. Despliegue de Contenedores

El proyecto incluye scripts que automatizan el levantamiento de la infraestructura necesaria. Si el archivo `.env` no existe, el script lo creará automáticamente a partir de la plantilla incluida.

#### En Windows (PowerShell):
Ejecutar en la raíz del proyecto:
```powershell
./scripts/primera_instalacion.ps1
```

#### En Linux / macOS (Bash):
Ejecutar en la raíz del proyecto:
```bash
sudo bash scripts/primera_instalacion.sh
```

El script verificará la disponibilidad de puertos y, al finalizar, informará en cuáles está operativo cada servicio.

---

### 🔑 2. Configuración de la API Key de Gemini

Para que el motor de Inteligencia Artificial (el flujo RAG y la transcripción de audio) pueda funcionar, necesitás configurar tu clave de Google Gemini:

1. Dirigirse a [Google AI Studio](https://aistudio.google.com/) y obtener una nueva API Key.
2. Acceder al Panel de Administración (por defecto `http://localhost:8000`).
3. Dirigirse a la pestaña **Configuración** en el menú superior.
4. Ingresar tu API Key de Gemini en el campo correspondiente y presioná guardar. El bot detectará la clave automáticamente sin necesidad de reiniciar los servicios.

---

### 📱 3. Configuración de la Instancia y Vinculación

La configuración de WhatsApp se realiza de manera centralizada desde el Panel de Administración:

1. Acceder al Panel de Administración (la URL se muestra al finalizar la instalación, por defecto `http://localhost:8000`).
2. Dirigirse a la sección de **Instancias**.
3. Crear una nueva instancia (ej. `rag_bot`).
4. Generar y escanear el **Código QR** desde la aplicación de WhatsApp en el dispositivo móvil (**Dispositivos vinculados** $\rightarrow$ **Vincular un dispositivo**).
5. Una vez vinculada la cuenta, el bot comenzará a procesar mensajes automáticamente.

---

## 🖥️ Operación del Sistema

El ecosistema Neuradocs se compone de dos interfaces principales:

### 1. Panel de Administración (Admin UI)
* **Acceso:** URL informada al finalizar la instalación (por defecto `http://localhost:8000`).
* **Capacidades Administrativas:**
  * **Gestión de Documentación:** Carga y depuración de archivos PDF para la base de conocimientos.
  * **Control de Precios y Stock:** Editor de archivos CSV para la gestión de catálogos de productos.
  * **Administración de FAQs:** Configuración de respuestas predefinidas con match semántico.
  * **Gestión de Instancias:** Creación, vinculación y desactivación de cuentas de WhatsApp.
  * **Monitoreo:** Visualización de logs de conversación en tiempo real y ajuste de parámetros del bot.

### 2. Interfaz de Usuario (WhatsApp)
El bot procesa las solicitudes siguiendo una jerarquía de resolución:
1. **Consultas Frecuentes (FAQs):** Si la consulta coincide semánticamente con una FAQ, se devuelve la respuesta predefinida.
2. **Consulta de Productos (CSV):** Si se detecta una intención de búsqueda de producto, se utiliza un algoritmo de *fuzzy matching* para localizar el precio y stock en los archivos CSV.
3. **Generación RAG (PDFs):** En caso de no hallar un match previo, el sistema recupera fragmentos relevantes de los PDFs mediante FAISS y genera una respuesta contextualizada con Gemini.
4. **Procesamiento de Audio:** Los mensajes de voz son transcritos a texto mediante la API de Gemini antes de ingresar al flujo de resolución.

---

## 💡 Buenas Prácticas para la Base de Conocimiento

El rendimiento y la precisión de las respuestas del bot dependen directamente de la calidad de los archivos cargados. Asegurate de seguir estas pautas para optimizar el comportamiento:

### 📄 Documentos PDF (Flujo RAG)
* **Texto digital y seleccionable:** Evitá subir PDFs que sean imágenes escaneadas. Los documentos deben contener texto real seleccionable para que FAISS y Gemini puedan indexar y recuperar la información. Si usás escaneos de documentos físicos, aplicales un proceso de OCR antes de subirlos.
* **Información estructurada:** Redactá el contenido de forma clara y directa. El uso de títulos jerárquicos ayuda a que el proceso de partición de texto (*chunking*) conserve el contexto de cada párrafo de manera óptima.

### 📊 Catálogos en CSV (Precios y Stock)
* **Estructura consistente:** El archivo CSV debe mantener siempre las columnas esperadas por el sistema para asegurar la correcta lectura de precios y stock.
* **Nombres descriptivos:** El algoritmo de búsqueda aproximada (*fuzzy matching*) funciona mejor si los nombres de los productos son claros y legibles (ej: `"Remera de Algodón Negra"` rinde mucho mejor que abreviaciones confusas como `"Rem Alg Neg"`).

---

## 🔍 Monitoreo y Diagnóstico (Health Checks)

El bot cuenta con un endpoint de diagnóstico integrado para verificar que todos los servicios y conexiones del ecosistema estén en condiciones óptimas.

### 🩺 Endpoint de Salud (Deep Health Check)
Podés consultar el estado detallado del sistema realizando una petición `GET` al bot (puerto `5000`):

* **URL de consulta:** `http://localhost:5000/health`
* **¿Qué verifica internamente?**
  * **RAG (`rag`):** Comprueba si la base de conocimientos basada en FAISS y Gemini se inicializó y cargó correctamente.
  * **Evolution API (`evolution_api`):** Evalúa la latencia y la conectividad directa con la API de WhatsApp, asegurando que la instancia que el bot está usando responda correctamente.

#### Ejemplo de respuesta saludable (`status: ok`):
```json
{
  "status": "ok",
  "components": {
    "rag": {
      "status": "ok",
      "duration_ms": 0
    },
    "evolution_api": {
      "status": "ok",
      "duration_ms": 145
    }
  }
}
```

*Si alguno de los componentes falla, el estado global pasará a `degraded` o `unhealthy`, devolviendo detalles específicos del error (como fallas de conexión o credenciales incorrectas), ideal para integrarlo con sistemas de monitoreo.*

---

## 🏗️ Arquitectura Técnica

El sistema se implementa bajo una arquitectura de microservicios orquestados por Docker Compose:

```
┌────────────────────────────────────────────────────────┐
│                      DOCKER COMPOSE                    │
│                                                        │
│   ┌──────────────┐     REST API     ┌──────────────┐   │
│   │  Admin UI    │◄────────────────►│ Whatsapp Bot │   │
│   │ (FastAPI:8000│                  │ (FastAPI:5000│   │
│   └──────┬───────┘                  └──────┬───────┘   │
│          │                                 │           │
│          │ Comparten                       │ Usa       │
│          ▼ Named Volumes                   ▼           │
│     ┌──────────┐                    ┌──────────────┐   │
│     │ PDFs,    │                    │ FAISS Vector │   │
│     │ Configs, │                    │ Store        │   │
│     │ FAQs     │                    └──────┬───────┘   │
│     └──────────┘                           │           │
│                                            │           │
│   ┌──────────────────┐    Webhook          │           │
│   │  Evolution API   ├─────────────────────┘           │
│   │  (Node.js:8080)  │◄────────────────────┐           │
│   └────────┬─────────┘                     │           │
│            │                               │           │
│      ┌─────┴──────┐                        │           │
│      ▼            ▼                        ▼           │
│ ┌──────────┐ ┌─────────┐            ┌──────────────┐   │
│ │ Postgres │ │  Redis  │            │  Google      │   │
│ │   (DB)   │ │ (Cache) │            │  Gemini API  │   │
│ └──────────┘ └─────────┘            └──────────────┘   │
└────────────────────────────────────────────────────────┘
```

* **Whatsapp Bot:** Motor de orquestación. Implementa la lógica de RAG, el procesamiento de audio y la integración con la API de Gemini.
* **Admin UI:** Interfaz de gestión de activos de conocimiento, configuración y control de instancias de WhatsApp.
* **Evolution API:** Capa de abstracción para la interfaz de comunicación de WhatsApp.
* **FAISS:** Biblioteca para la búsqueda eficiente de vectores (embeddings) en el espacio semántico.
* **Fuzzy Matching:** Implementación de similitud de cadenas para la recuperación de datos en CSVs.

---

## 📂 Estructura de Directorios

* **`chatbotW/src/`**: Lógica de negocio, servicios y controladores.
* **`chatbotW/PDFs/`**: Almacén de documentos base para la recuperación de información.
* **`chatbotW/CSVs/`**: Base de datos de precios y stock.
* **`chatbotW/vectorstore/`**: Índices vectoriales generados automáticamente.
* **`chatbotW/cache/`**: Persistencia de embeddings para optimización de latencia y costos.
* **`chatbotW/logs/`**: Registro detallado de transacciones y conversaciones.

---

## 🛑 Gestión de Servicios (Docker)

Comandos operativos para la administración del sistema desde la raíz de `chatbotW/`:

* **Monitoreo de logs del Bot:**
  ```bash
  docker logs gemini_whatsapp_bot -f
  ```
* **Detención de servicios (preservando datos):**
  ```bash
  docker compose down
  ```
* **Inicio de servicios:**
  ```bash
  docker compose up -d
  ```
* **Reinicio completo (Elimina FAQs y configuraciones):**
  ```bash
  docker compose down -v && docker compose up -d --build
  ```

---

Si presenta problemas durante la instalación o ejecución, consulte la [Guía de Resolución de Problemas](docs/TROUBLESHOOTING.md).

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.
