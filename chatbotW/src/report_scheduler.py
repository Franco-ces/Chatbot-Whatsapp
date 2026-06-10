"""report_scheduler.py — Módulo de programación de informes PDF.

Ejecuta un loop en background cada 60 segundos que consulta
telemetry.report_schedules, genera PDFs vía report_generator,
y los envía vía WhatsApp usando enviar_documento.

El patrón sigue el mismo diseño que cleanup_loop en main.py:
- start_scheduler() crea un asyncio.Task
- stop_scheduler() cancela el task
- El loop se ejecuta indefinidamente con manejo de errores aislado
"""
import asyncio
import json
from datetime import date, datetime, time
from logging_config import get_logger

logger = get_logger("report_scheduler")

_scheduler_task: asyncio.Task | None = None

# ─── Due schedule query ─────────────────────────────────────────────────

_DUE_SCHEDULES_SQL = """
    SELECT * FROM telemetry.report_schedules
    WHERE activo = true
      AND hora_envio <= $1
      AND (ultimo_envio IS NULL OR ultimo_envio::date < CURRENT_DATE)
    ORDER BY hora_envio ASC
"""

# ─── Update ultimo_envio ────────────────────────────────────────────────

_UPDATE_ENVIO_SQL = """
    UPDATE telemetry.report_schedules SET ultimo_envio = NOW(), updated_at = NOW()
    WHERE id = $1
"""


# ─── Process single schedule ────────────────────────────────────────────

async def _process_schedule(schedule: dict, pool, wa_client, instance_name: str) -> None:
    """Process a single due schedule: generate PDF, send it, update ultimo_envio.

    Errors are isolated: this function never raises. If any step fails,
    it logs the error and returns without updating ultimo_envio.
    """
    try:
        if not instance_name:
            logger.error("No active instance for scheduler", schedule_id=schedule["id"])
            return

        # Generate PDF
        from report_generator import generar_reporte
        parametros = schedule.get("parametros") or {}
        if isinstance(parametros, str):
            parametros = json.loads(parametros)

        pdf_bytes = await generar_reporte(
            schedule["tipo"], pool, parametros
        )

        # Send via WhatsApp
        filename = f"reporte_{schedule['tipo']}_{date.today().isoformat()}.pdf"
        await wa_client.enviar_documento(
            schedule["destino"], pdf_bytes, filename, instance_name=instance_name
        )

        # Update ultimo_envio
        async with pool.acquire() as conn:
            await conn.execute(_UPDATE_ENVIO_SQL, schedule["id"])

        logger.info(
            "Scheduled report sent",
            schedule_id=schedule["id"],
            tipo=schedule["tipo"],
            destino=schedule["destino"],
        )

    except Exception as e:
        logger.error(
            "Failed to process schedule",
            schedule_id=schedule.get("id"),
            error=str(e),
        )


# ─── Schedule checking ──────────────────────────────────────────────────

async def _check_schedules(pool, wa_client, instance_name_resolver) -> None:
    """Query and process all due schedules for the current time."""
    logger.info("Scheduler tick: checking due schedules", current_time=str(datetime.now().time()))

    now = datetime.now()
    current_time = now.time()

    # Find due schedules
    async with pool.acquire() as conn:
        schedules = await conn.fetch(_DUE_SCHEDULES_SQL, current_time)

    if schedules:
        logger.info("Due schedules found", count=len(schedules))
        for sched in schedules:
            instance_name = instance_name_resolver() if callable(instance_name_resolver) else instance_name_resolver
            await _process_schedule(dict(sched), pool, wa_client, instance_name)
    else:
        logger.info("No due schedules at this time", current_time=str(current_time))


# ─── Scheduler loop ─────────────────────────────────────────────────────

async def _scheduler_loop(pool, wa_client, instance_name_resolver) -> None:
    """Main scheduler loop: runs every 60 seconds, queries due schedules, and processes them."""
    while True:
        try:
            if pool is None:
                logger.warning("Scheduler skipping: pool is None")
            else:
                await _check_schedules(pool, wa_client, instance_name_resolver)

            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Scheduler loop error", error=str(e))
            await asyncio.sleep(60)  # Don't tight-loop on error


# ─── Start / Stop ──────────────────────────────────────────────────────

async def start_scheduler(pool, wa_client, instance_name_resolver) -> asyncio.Task:
    """Start the scheduler background loop.

    Returns the asyncio.Task so callers can cancel it on shutdown.
    """
    global _scheduler_task
    _scheduler_task = asyncio.create_task(
        _scheduler_loop(pool, wa_client, instance_name_resolver)
    )
    logger.info("Report scheduler started")
    return _scheduler_task


async def stop_scheduler() -> None:
    """Stop the scheduler background loop gracefully."""
    global _scheduler_task
    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None
        logger.info("Report scheduler stopped")