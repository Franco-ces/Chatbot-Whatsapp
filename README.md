# Chatbot de WhatsApp con RAG (Gemini + Evolution API)

Este proyecto implementa un sistema de respuesta automatizada para WhatsApp basado en la arquitectura **RAG (Retrieval-Augmented Generation)**. El sistema permite la consulta de bases de conocimiento almacenadas en documentos PDF y archivos CSV locales, procesando entradas de texto y audio de voz mediante el modelo Gemini de Google.

La solución se encuentra totalmente contenedorizada mediante **Docker**, asegurando la portabilidad y la consistencia del entorno de ejecución.

---

## 🛠️ Guía de Instalación y Despliegue

El sistema ha sido diseñado para un despliegue simplificado, donde la configuración de la instancia de comunicación se realiza directamente desde la interfaz administrativa.

### 📋 Prerrequisitos

Es necesario contar con la siguiente infraestructura instalada:
* **Docker Desktop** (incluyendo Docker Compose).
  * [Documentación oficial de Docker](https://www.docker.com/products/docker-desktop/)

---

### 📥 1. Despliegue de Contenedores

El proyecto incluye scripts que automatizan el levantamiento de la infraestructura necesaria. Si el archivo `.env` no existe, el script lo creará automáticamente a partir de la plantilla incluida.

#### En Windows (PowerShell):
Ejecutar en la raíz del proyecto:
```powershell
./primera_instalacion.ps1
```

#### En Linux / macOS (Bash):
Ejecutar en la raíz del proyecto:
```bash
chmod +x primera_instalacion.sh
./primera_instalacion.sh
```

El script verificará la disponibilidad de puertos y, al finalizar, informará en cuáles está operativo cada servicio.

---

### 📱 2. Configuración de la Instancia y Vinculación

A diferencia de versiones anteriores, la configuración de WhatsApp se realiza ahora de manera centralizada desde el Panel de Administración:

1. Acceder al Panel de Administración (la URL se muestra al finalizar la instalación, por defecto `http://localhost:8000`).
2. Dirigirse a la sección de **Instancias**.
3. Crear una nueva instancia (ej. `rag_bot`).
4. Generar y escanear el **Código QR** desde la aplicación de WhatsApp en el dispositivo móvil (**Dispositivos vinculados** $\rightarrow$ **Vincular un dispositivo**).
5. Una vez vinculada la cuenta, el bot comenzará a procesar mensajes automáticamente.

---

## 🖥️ Operación del Sistema

El ecosistema se compone de dos interfaces principales:

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

Si presenta problemas durante la instalación o ejecución, consulte la [Guía de Resolución de Problemas](TROUBLESHOOTING.md).
