# src/health.py
"""
Health check probes for the chatbot application.

Provides deep health checks for:
- Application initialization (RAG loaded)
- Evolution API reachability

All probes timeout at 5 seconds.
"""
import time
import httpx_idle_client
from logging_config import get_logger

logger = get_logger("health")

PROBE_TIMEOUT = 5.0  # seconds


async def check_evolution_api(api_url: str, api_key: str, instance_name: str) -> dict:
    """
    Probe Evolution API reachability by hitting a lightweight endpoint.
    Returns: {"status": "ok"|"unhealthy", "duration_ms": int, "detail": str|None}
    """
    start = time.perf_counter()
    url = f"{api_url}/instance/fetchInstances"
    headers = {"apikey": api_key, "Content-Type": "application/json"}

    try:
        client = httpx_idle_client.IdleTimeoutClient()
        response = await client.request("GET", url, headers=headers, timeout=PROBE_TIMEOUT)
        duration_ms = int((time.perf_counter() - start) * 1000)
        if response.status_code in (200, 201):
            return {"status": "ok", "duration_ms": duration_ms}
        return {"status": "unhealthy", "duration_ms": duration_ms, "detail": f"HTTP {response.status_code}"}
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return {"status": "unhealthy", "duration_ms": duration_ms, "detail": str(e)[:200]}


async def check_rag_loaded(rag_instance) -> dict:
    """
    Check if RAG was initialized successfully.
    Returns: {"status": "ok"|"unhealthy", "duration_ms": 0}
    """
    if rag_instance is not None:
        return {"status": "ok", "duration_ms": 0}
    return {"status": "unhealthy", "duration_ms": 0, "detail": "RAG not initialized"}


async def run_health_probes(wa_client, rag_instance) -> dict:
    """
    Run all health probes and return aggregated status.
    Status logic: ok if all pass, degraded if any fail, unhealthy if all fail.
    """
    probes = {}

    # Probe: RAG loaded
    probes["rag"] = await check_rag_loaded(rag_instance)

    # Probe: Evolution API
    if wa_client:
        probes["evolution_api"] = await check_evolution_api(
            wa_client.api_url, wa_client.api_key, wa_client.instance_name
        )
    else:
        probes["evolution_api"] = {"status": "unhealthy", "duration_ms": 0, "detail": "WhatsApp client not initialized"}

    # Aggregate status
    statuses = [p["status"] for p in probes.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif all(s == "unhealthy" for s in statuses):
        overall = "unhealthy"
    else:
        overall = "degraded"

    return {
        "status": overall,
        "components": probes,
    }
