"""
telemetry.py — Módulo de telemetría del chatbot.

Gestiona el pool de conexiones a PostgreSQL (asyncpg), el bootstrap
del esquema `telemetry` y la tabla `bot_messages`, y expone funciones
para registrar interacciones y consultar resúmenes agregados.

El pool se inicializa en el lifespan de FastAPI (main.py / interface.py)
y se cierra al apagar. `record_interaction` es fire-and-forget: nunca
propaga errores al caller. `get_summary` sí propaga errores como
AppError(TELEMETRY_DB_ERROR).
"""

# ─── Auditoría ────────────────────────────────────────────────────────
# El sistema de auditoría registra todas las acciones administrativas
# en la tabla `telemetry.admin_audit`. Esto incluye:
#   - Cambios de configuración (API keys, datos de contacto, modelos)
#   - CRUD de documentos (PDFs, CSVs, FAQs)
#   - Gestión de instancias de Evolution API (crear, activar, eliminar)
#   - Autenticación (logins exitosos/fallidos, cambio de contraseña)
#
# Cada registro contiene:
#   - action: Tipo de acción (ej. 'pdf.delete', 'instance.create')
#   - target: Elemento afectado (nombre de archivo, instancia, etc.)
#   - detail: Información adicional contextual
#   - created_at: Timestamp automático
#
# La auditoría es "fire-and-forget": si el pool de PostgreSQL no está
# disponible, las acciones del admin NO se bloquean — simplemente no
# se registra el evento. Esto evita que un fallo de DB impida operar
# el panel.
#
# Consultar desde la API: GET /api/audit?limit=50
# Consultar desde PostgreSQL: SELECT * FROM telemetry.admin_audit ORDER BY created_at DESC;

import asyncio
import os

import asyncpg

from error_codes import ErrorCode
from exceptions import AppError
from logging_config import get_logger

logger = get_logger("telemetry")

# ─── Module-level pool ───────────────────────────────────────────────
_pool: asyncpg.Pool | None = None

# ─── Schema DDL ──────────────────────────────────────────────────────

_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS telemetry;
"""

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS telemetry.bot_messages (
    id              BIGSERIAL PRIMARY KEY,
    remitente       TEXT NOT NULL,
    push_name       TEXT,
    texto           TEXT,
    es_audio        BOOLEAN NOT NULL DEFAULT false,
    respuesta       TEXT,
    cacheable       BOOLEAN NOT NULL DEFAULT false,
    cache_hit       BOOLEAN NOT NULL DEFAULT false,
    faq_hit         BOOLEAN NOT NULL DEFAULT false,
    error_code      TEXT,
    rag_duration_ms INTEGER,
    send_duration_ms INTEGER,
    total_duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_bot_messages_remitente ON telemetry.bot_messages (remitente);
CREATE INDEX IF NOT EXISTS idx_bot_messages_created_at ON telemetry.bot_messages (created_at);
CREATE INDEX IF NOT EXISTS idx_bot_messages_error_code ON telemetry.bot_messages (error_code) WHERE error_code IS NOT NULL;
"""

_SCHEDULES_DDL = """
CREATE TABLE IF NOT EXISTS telemetry.report_schedules (
    id              SERIAL PRIMARY KEY,
    tipo            TEXT NOT NULL,
    parametros      JSONB NOT NULL DEFAULT '{}',
    hora_envio      TIME NOT NULL,
    destino         TEXT NOT NULL,
    header_text     TEXT,
    footer_text     TEXT,
    activo          BOOLEAN NOT NULL DEFAULT true,
    ultimo_envio    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_SCHEDULES_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_report_schedules_activo ON telemetry.report_schedules (activo) WHERE activo = true;
CREATE INDEX IF NOT EXISTS idx_schedules_active_time ON telemetry.report_schedules (activo, hora_envio);
CREATE INDEX IF NOT EXISTS idx_schedules_tipo ON telemetry.report_schedules (tipo);
"""

_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS telemetry.admin_audit (
    id              BIGSERIAL PRIMARY KEY,
    action          TEXT NOT NULL,
    actor           TEXT NOT NULL DEFAULT 'admin',
    target          TEXT,
    detail          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_AUDIT_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_admin_audit_action ON telemetry.admin_audit (action);
CREATE INDEX IF NOT EXISTS idx_admin_audit_created_at ON telemetry.admin_audit (created_at DESC);
"""


# ─── Helpers ──────────────────────────────────────────────────────────

def _build_dsn() -> str | None:
    """Construye el DSN de PostgreSQL desde variables de entorno.

    Requiere POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB.
    POSTGRES_HOST defaultea a 'evolution_postgres'.
    Si falta algún campo obligatorio, devuelve None.
    """
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    dbname = os.environ.get("POSTGRES_DB")
    host = os.environ.get("POSTGRES_HOST", "evolution_postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")

    if not user or not password or not dbname:
        return None

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


# ─── Pool lifecycle ──────────────────────────────────────────────────

async def init_pool(dsn: str | None = None) -> asyncpg.Pool | None:
    """Crea el pool de conexiones y ejecuta el bootstrap del esquema.

    Args:
        dsn: Connection string. Si es None, se construye desde env vars.

    Returns:
        El pool creado, o None si falta configuración o falla la conexión.
    """
    global _pool

    connection_dsn = dsn or _build_dsn()
    if not connection_dsn:
        logger.warning("Telemetría deshabilitada: faltan POSTGRES_USER/PASSWORD/DB")
        return None

    try:
        pool = await asyncpg.create_pool(
            dsn=connection_dsn,
            min_size=1,
            max_size=5,
            command_timeout=5,
            ssl="disable",
        )

        # Bootstrap del esquema
        async with pool.acquire() as conn:
            await conn.execute(_SCHEMA_DDL)
            await conn.execute(_TABLE_DDL)
            await conn.execute(_INDEX_DDL)
            await conn.execute(_SCHEDULES_DDL)
            await conn.execute(_SCHEDULES_INDEX_DDL)
            await conn.execute(_AUDIT_DDL)
            await conn.execute(_AUDIT_INDEX_DDL)

        _pool = pool
        logger.info("Pool de telemetría inicializado y esquema verificado")
        return pool

    except Exception as e:
        logger.error("Fallo al inicializar pool de telemetría", detail=str(e))
        _pool = None
        return None


async def close_pool():
    """Cierra el pool de conexiones si existe."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Pool de telemetría cerrado")


# ─── Record interaction ───────────────────────────────────────────────

_INSERT_SQL = """
INSERT INTO telemetry.bot_messages (
    remitente, push_name, texto, es_audio, respuesta,
    cacheable, cache_hit, faq_hit, error_code,
    rag_duration_ms, send_duration_ms, total_duration_ms
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
"""


async def record_interaction(
    pool: asyncpg.Pool | None,
    *,
    remitente: str,
    push_name: str | None,
    texto: str | None,
    es_audio: bool,
    respuesta: str | None,
    cacheable: bool,
    cache_hit: bool,
    faq_hit: bool,
    error_code: str | None,
    rag_duration_ms: int | None,
    send_duration_ms: int | None,
    total_duration_ms: int,
) -> None:
    """Fire-and-forget: registra una interacción en la base de datos.

    Si el pool es None (telemetría deshabilitada), no hace nada.
    Si falla la escritura, loggea un warning pero NO propaga la excepción.
    """
    if pool is None:
        return

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                _INSERT_SQL,
                remitente, push_name, texto, es_audio, respuesta,
                cacheable, cache_hit, faq_hit, error_code,
                rag_duration_ms, send_duration_ms, total_duration_ms,
            )
    except Exception as e:
        logger.warning(
            "Fallo al registrar telemetría",
            error=str(e),
            remitente=remitente,
        )


# ─── Summary query ────────────────────────────────────────────────────

_TOTALS_SQL = """
SELECT
    COUNT(*) AS total_messages,
    COUNT(*) FILTER (WHERE faq_hit) AS faq_hits,
    COUNT(*) FILTER (WHERE cache_hit) AS cache_hits,
    COALESCE(ROUND(AVG(rag_duration_ms)), 0) AS avg_rag_ms,
    COALESCE(ROUND(AVG(send_duration_ms)), 0) AS avg_send_ms,
    COUNT(*) FILTER (WHERE error_code IS NOT NULL) AS error_count,
    COUNT(DISTINCT remitente) AS unique_users
FROM telemetry.bot_messages
WHERE created_at >= NOW() - INTERVAL '{days} days'
"""

_DAILY_SQL = """
SELECT
    DATE(created_at) AS date,
    COUNT(*) AS total_messages,
    COUNT(*) FILTER (WHERE faq_hit) AS faq_hits,
    COUNT(*) FILTER (WHERE cache_hit) AS cache_hits,
    COALESCE(ROUND(AVG(rag_duration_ms)), 0) AS avg_rag_ms,
    COALESCE(ROUND(AVG(send_duration_ms)), 0) AS avg_send_ms,
    COUNT(*) FILTER (WHERE error_code IS NOT NULL) AS error_count,
    COUNT(DISTINCT remitente) AS unique_users
FROM telemetry.bot_messages
WHERE created_at >= NOW() - INTERVAL '{days} days'
GROUP BY DATE(created_at)
ORDER BY DATE(created_at) ASC
"""

_ERROR_CATEGORIES_SQL = """
SELECT
    SUBSTRING(error_code, 1, 5) AS category,
    COUNT(*) AS count
FROM telemetry.bot_messages
WHERE error_code IS NOT NULL
    AND created_at >= NOW() - INTERVAL '{days} days'
GROUP BY SUBSTRING(error_code, 1, 5)
ORDER BY count DESC
"""

_ERROR_TYPES_SQL = """
SELECT
    error_code,
    COUNT(*) AS count
FROM telemetry.bot_messages
WHERE error_code IS NOT NULL
    AND created_at >= NOW() - INTERVAL '{days} days'
GROUP BY error_code
ORDER BY count DESC
"""


async def get_summary(pool: asyncpg.Pool | None, days: int = 7) -> dict:
    """Devuelve datos agregados para el dashboard de telemetría.

    Args:
        pool: Pool de conexiones asyncpg. If None, raises AppError.
        days: Número de días hacia atrás para la agregación.

    Returns:
        Dict con la estructura TS-2 del spec.

    Raises:
        AppError(TELEMETRY_DB_ERROR): Si falla la consulta.
    """
    if pool is None:
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="Pool de telemetría no inicializado")

    try:
        async with pool.acquire() as conn:
            totals = await conn.fetchrow(
                _TOTALS_SQL.format(days=days)
            )
            daily_rows = await conn.fetch(
                _DAILY_SQL.format(days=days)
            )
            category_rows = await conn.fetch(
                _ERROR_CATEGORIES_SQL.format(days=days)
            )
            type_rows = await conn.fetch(
                _ERROR_TYPES_SQL.format(days=days)
            )

        if totals is None:
            totals = {
                "total_messages": 0, "faq_hits": 0, "cache_hits": 0,
                "avg_rag_ms": 0, "avg_send_ms": 0,
                "error_count": 0, "unique_users": 0,
            }

        daily = [
            {
                "date": str(row["date"]),
                "total_messages": row["total_messages"],
                "faq_hits": row["faq_hits"],
                "cache_hits": row["cache_hits"],
                "avg_rag_ms": row["avg_rag_ms"] or 0,
                "avg_send_ms": row["avg_send_ms"] or 0,
                "error_count": row["error_count"],
                "unique_users": row["unique_users"],
            }
            for row in daily_rows
        ]

        error_categories = {
            row["category"]: row["count"]
            for row in category_rows
        }

        error_types = [
            {"code": row["error_code"], "count": row["count"]}
            for row in type_rows
        ]

        return {
            "total_messages": totals["total_messages"] or 0,
            "faq_hits": totals["faq_hits"] or 0,
            "cache_hits": totals["cache_hits"] or 0,
            "avg_rag_ms": int(totals["avg_rag_ms"] or 0),
            "avg_send_ms": int(totals["avg_send_ms"] or 0),
            "error_count": totals["error_count"] or 0,
            "unique_users": totals["unique_users"] or 0,
            "daily": daily,
            "error_categories": error_categories,
            "error_types": error_types,
        }

    except AppError:
        raise
    except Exception as e:
        logger.error("Fallo al consultar resumen de telemetría", detail=str(e))
        raise AppError(ErrorCode.TELEMETRY_DB_ERROR, detail=str(e))


# ─── Audit ────────────────────────────────────────────────────────────

async def record_audit(action: str, target: str = None, detail: str = None) -> None:
    """Registra una acción administrativa en el log de auditoría.

    Fire-and-forget: nunca propaga errores al caller. Si el pool no
    está disponible, simplemente no registra (no es crítico).

    Args:
        action: Tipo de acción (ej. 'pdf.delete', 'config.save', 'instance.create').
        target: Qué fue afectado (nombre de archivo, instancia, etc.).
        detail: Información adicional (ej. nombre del campo cambiado).
    """
    pool = _pool
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO telemetry.admin_audit (action, target, detail) "
                "VALUES ($1, $2, $3)",
                action, target, detail,
            )
    except Exception:
        pass  # Nunca fallar por auditoría