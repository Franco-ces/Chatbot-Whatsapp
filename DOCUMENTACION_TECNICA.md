# Documentación Técnica: Sistema de Asistencia Automatizada vía WhatsApp

## 1. Introducción
Este proyecto implementa un sistema de agente inteligente capaz de interactuar con usuarios a través de WhatsApp, proporcionando respuestas basadas en una base de conocimientos dinámica. El sistema utiliza la arquitectura **RAG (Retrieval-Augmented Generation)** para mitigar las alucinaciones de los modelos de lenguaje (LLMs) y asegurar que las respuestas estén ancladas en datos reales y actualizables.

## 2. Justificación Tecnológica

### 2.1 Modelo de Lenguaje: Google Gemini

Se seleccionó **Gemini** sobre otras alternativas (como GPT-4) por las siguientes razones fundamentales:

#### 2.1.1 Multimodalidad Nativa
Gemini permite procesar audios de voz directamente, eliminando la necesidad de un servicio de transcripción externo (como Whisper), lo que reduce la latencia y la complejidad de la infraestructura.

#### 2.1.2 Ventana de Contexto y Costo
Ofrece un equilibrio superior entre el costo de los tokens y la calidad de las respuestas para tareas de recuperación de información.

#### 2.1.3 Integración de Embeddings
El uso de `gemini-embedding-2-preview` permite una representación vectorial consistente tanto para la indexación de documentos como para la consulta del usuario.

#### 2.1.4 Alineación con los Objetivos del Proyecto
El uso de Gemini fue un requisito explícito del enunciado de la materia, lo que garantiza la alineación de la solución con los objetivos pedagógicos planteados por la cátedra.

### 2.2 Motor de Búsqueda: FAISS (Facebook AI Similarity Search)

Para la implementación del RAG, se utilizó **FAISS** en lugar de una base de datos vectorial en la nube (como Pinecone) debido a:

* **Baja Latencia**: Al ser una librería de búsqueda local, el acceso a los vectores es casi instantáneo.
* **Privacidad y Control**: Los datos no abandonan el entorno del servidor, garantizando la confidencialidad de los manuales PDF.
* **Simplicidad de Despliegue**: No requiere la gestión de clústeres externos, integrándose directamente en el volumen de datos de Docker.

### 2.3 Pasarela de Comunicación: Evolution API

Se optó por **Evolution API** por ser una solución robusta de código abierto que abstrae la complejidad del protocolo de WhatsApp, permitiendo una integración vía Webhooks y REST API, lo que desacopla la lógica del bot de la gestión de la conexión del dispositivo.

---

## 3. Diseño de la Solución

### 3.1 Jerarquía de Resolución de Consultas

Para optimizar la precisión y el costo de la API, el sistema no envía todas las consultas al LLM. Implementa una **cascada de resolución**:

1. **Capa de FAQs (Match Semántico)**: El sistema compara la consulta con una base de preguntas frecuentes. Se utiliza la similitud de coseno entre embeddings para detectar la intención, permitiendo respuestas instantáneas y exactas sin costo de generación de texto.
2. **Capa de Catálogo (Fuzzy Matching)**: Si la consulta se identifica como una búsqueda de producto, el sistema escanea archivos CSV utilizando un algoritmo de similitud de cadenas (*SequenceMatcher*). Esto permite tolerar errores tipográficos del usuario al buscar precios o stock.
3. **Capa RAG (Recuperación Contextual)**: Si las capas anteriores fallan, el sistema recupera los fragmentos más relevantes de los manuales PDF indexados en FAISS y los entrega a Gemini como contexto para generar una respuesta fundamentada.

### 3.2 Flujo de Procesamiento de Audio

El sistema implementa un pipeline de audio eficiente:

`Audio WhatsApp (OGG)` → `Carga en Memoria` → `Gemini Multimodal API` → `Transcripción de Texto` → `Flujo de Resolución`.

---

## 4. Infraestructura y Persistencia

### 4.1 Orquestación con Docker

La arquitectura se basa en microservicios para asegurar el aislamiento de responsabilidades:

* **Bot Service**: Lógica de negocio y orquestación de RAG.
* **Admin UI**: Gestión de activos y monitoreo.
* **Evolution API**: Capa de transporte de mensajería.
* **Postgres/Redis**: Soporte de estado para la pasarela de comunicación.

### 4.2 Estrategia de Persistencia

Se utilizaron **Named Volumes** de Docker para evitar la pérdida de datos entre reinicios de contenedores y solucionar problemas de bloqueo de archivos en entornos WSL2:

* `/app/faqs_data`: Almacena la base de FAQs.
* `/app/config_data`: Almacena la configuración del bot y la API Key.

---

## 5. Estrategia de Robustez y Manejo de Errores

El sistema implementa un framework de manejo de excepciones jerárquico basado en la clase `AppError` y la enumeración `ErrorCode`.

* **Aislamiento de Fallos**: Los errores en la API de embeddings o en la lectura de archivos no detienen la ejecución del bot; en su lugar, el sistema degrada la funcionalidad (ej. si falla el match de FAQ, pasa directamente al RAG).
* **Validación de Datos**: Se utilizan modelos de Pydantic para la validación de los payloads entrantes desde los webhooks de WhatsApp, previniendo errores de ejecución por datos mal formados.
