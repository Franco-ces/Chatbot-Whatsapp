"""report_generator.py — Módulo de generación de reportes PDF.

Provee un registro de tipos de reporte (registry pattern) y funciones
para listar tipos y generar PDFs desde datos de telemetría PostgreSQL.

Patrón: BaseReport + __init_subclass__ auto-registro. Agregar un nuevo
reporte = agregar una subclase con `id`, `nombre`, `descripcion`,
`parametros` y `generar()`. No se necesita tocar endpoints.

Las consultas SQL leen de `telemetry.bot_messages`. Los PDFs se generan
con WeasyPrint (HTML → PDF, CSS @page para diseño de página).
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from weasyprint import HTML

# ─── Param Info ───────────────────────────────────────────────────────────


@dataclass
class ParamInfo:
    """Describe un parámetro que el usuario debe proveer al generar un reporte."""
    key: str
    label: str
    tipo: str  # "date" | "text" | "number"
    requerido: bool = True


# ─── Base Report ──────────────────────────────────────────────────────────

_report_types: dict[str, type["BaseReport"]] = {}


class BaseReport(ABC):
    """Clase base para todos los reportes. Las subclases se auto-registran
    en `_report_types` vía `__init_subclass__` usando el atributo `id`."""
    id: str = ""
    nombre: str = ""
    descripcion: str = ""
    parametros: list[ParamInfo] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.id:
            _report_types[cls.id] = cls

    @abstractmethod
    async def generar(self, pool, params: dict) -> bytes:
        """Genera el PDF del reporte y devuelve los bytes."""
        ...


# ─── Validation ───────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def _validate_parametros(cls: type[BaseReport], params: dict) -> None:
    """Valida los parámetros de un reporte.

    Raises:
        ValueError: Con mensaje en español si falla la validación.
    """
    # 1. Parámetros requeridos
    for p in cls.parametros:
        if p.requerido and p.key not in params:
            raise ValueError(f"Parámetro requerido: {p.key}")

    # 2. Formato de fecha (YYYY-MM-DD)
    for p in cls.parametros:
        if p.tipo == "date" and p.key in params:
            val = str(params[p.key])
            if val and not _DATE_RE.match(val):
                raise ValueError("Formato de fecha inválido. Use YYYY-MM-DD.")

    # 3. Rango de fechas: desde <= hasta
    desde_val = params.get("desde")
    hasta_val = params.get("hasta")
    if desde_val and hasta_val:
        desde_date = date.fromisoformat(str(desde_val))
        hasta_date = date.fromisoformat(str(hasta_val))
        if desde_date > hasta_date:
            raise ValueError("La fecha 'desde' no puede ser posterior a 'hasta'")
        # 4. Rango máximo 90 días para por-dia
        if cls.id == "por-dia" and (hasta_date - desde_date).days > 90:
            raise ValueError("Rango máximo permitido: 90 días")

    # 5. Formato de teléfono
    if "telefono" in params and params.get("telefono"):
        tel = str(params["telefono"])
        if not _PHONE_RE.match(tel):
            raise ValueError("Número de teléfono inválido")


# ─── WeasyPrint Helpers ──────────────────────────────────────────────────


def _escape(text: str | None) -> str:
    """Escapa caracteres HTML peligrosos. None → cadena vacía."""
    if text is None:
        return ""
    s = str(text)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    return s


def _wrap_html(title: str, subtitle: str, headers: list[str], rows_html: str, total: str = "") -> str:
    """Envuelve título, subtítulo, encabezados y filas en un documento HTML5 completo con CSS embebido."""
    th_cells = "\n".join(f"<th>{_escape(h)}</th>" for h in headers)
    total_row = ""
    if total:
        total_row = f'<tr class="total"><td colspan="{len(headers)}">{_escape(total)}</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<style>
@page {{
  size: A4 portrait;
  margin: 25mm;
  @top-left {{
    content: "NeuraDocs";
  }}
  @top-right {{
    content: "{_escape(title)}";
  }}
  @bottom-center {{
    content: "Página " counter(page) " de " counter(pages);
  }}
}}
body {{
  font-family: 'DejaVu Sans', Arial, Helvetica, sans-serif;
  font-size: 10pt;
  color: #333;
}}
h1 {{
  text-align: center;
  font-size: 16pt;
  margin-bottom: 4pt;
}}
.subtitle {{
  text-align: center;
  font-size: 9pt;
  color: #666;
  margin-bottom: 12pt;
}}
table {{
  width: 100%;
  border-collapse: collapse;
}}
th {{
  background-color: #1e40af;
  color: white;
  font-size: 9pt;
  text-align: left;
  padding: 6px;
}}
td {{
  font-size: 9pt;
  padding: 6px;
  border-bottom: 1px solid #ddd;
  word-wrap: break-word;
}}
tr.even {{
  background-color: #f9fafb;
}}
tr.odd {{
  background-color: #ffffff;
}}
tr.total td {{
  font-weight: bold;
  background-color: #e5e7eb;
  border-top: 2px solid #1e40af;
  text-align: left;
  padding: 6px;
}}
tr {{
  page-break-inside: avoid;
}}
</style>
</head>
<body>
<h1>{_escape(title)}</h1>
<p class="subtitle">{_escape(subtitle)}</p>
<table>
<thead><tr>{th_cells}</tr></thead>
<tbody>
{rows_html}
{total_row}
</tbody>
</table>
</body>
</html>"""


def _render_html_to_pdf(html: str) -> bytes:
    """Renderiza un string HTML a bytes PDF usando WeasyPrint."""
    return HTML(string=html).write_pdf()


# ─── Template Functions ─────────────────────────────────────────────────


def _template_diario(fecha: str, rows: list[dict]) -> str:
    """Genera HTML para el reporte Resumen Diario."""
    rows_html = "\n".join(
        f'<tr class="{"even" if i % 2 == 0 else "odd"}">'
        f'<td>{_escape(r["hora"])}</td>'
        f'<td>{_escape(r["usuario"])}</td>'
        f'<td>{_escape(r["estado"])}</td>'
        f'<td>{_escape(str(r["latencia_ms"]) if r["latencia_ms"] is not None else "-")}</td>'
        f'<td>{_escape(r["mensaje_preview"] or "")}</td></tr>'
        for i, r in enumerate(rows)
    )
    return _wrap_html(
        "Resumen Diario",
        fecha,
        ["Hora", "Remitente", "Estado", "Latencia (ms)", "Mensaje"],
        rows_html,
        total=f"Total: {len(rows)} mensajes",
    )


def _template_historial(telefono: str, desde, hasta, rows: list[dict], push_name: str | None = None) -> str:
    """Genera HTML para el reporte Historial por Número."""
    rows_html = "\n".join(
        f'<tr class="{"even" if i % 2 == 0 else "odd"}">'
        f'<td>{i + 1}</td>'
        f'<td>{_escape(r["fecha_hora"])}</td>'
        f'<td>{_escape(r["contenido_preview"])}</td>'
        f'<td>{_escape(r["estado"])}</td>'
        f'<td>{_escape(str(r["latencia_ms"]) if r["latencia_ms"] is not None else "-")}</td></tr>'
        for i, r in enumerate(rows)
    )
    desde_str = desde or "inicio"
    hasta_str = hasta or "ahora"
    return _wrap_html(
        f"Historial: {telefono}",
        f"Desde: {desde_str}  Hasta: {hasta_str}",
        ["#", "Fecha/Hora", "Mensaje", "Estado", "Latencia"],
        rows_html,
        total=f"Total: {len(rows)}",
    )


def _template_por_dia(desde: str, hasta: str, rows: list[dict]) -> str:
    """Genera HTML para el reporte Mensajes por Día."""
    rows_html = "\n".join(
        f'<tr class="{"even" if i % 2 == 0 else "odd"}">'
        f'<td>{_escape(str(r["fecha"]))}</td>'
        f'<td>{_escape(str(r["total_mensajes"]))}</td>'
        f'<td>{_escape(str(r["exitos"]))}</td>'
        f'<td>{_escape(str(r["errores"]))}</td>'
        f'<td>{_escape(str(r["cache_hits"]))}</td>'
        f'<td>{_escape(str(r["faq_hits"]))}</td>'
        f'<td>{_escape(str(r["latencia_promedio_ms"]))}</td></tr>'
        for i, r in enumerate(rows)
    )
    total_msgs = sum(r["total_mensajes"] for r in rows) if rows else 0
    total_exitos = sum(r["exitos"] for r in rows) if rows else 0
    total_errores = sum(r["errores"] for r in rows) if rows else 0
    total_cache = sum(r["cache_hits"] for r in rows) if rows else 0
    total_faq = sum(r["faq_hits"] for r in rows) if rows else 0
    total_row = f"Total: {total_msgs} | Éxitos: {total_exitos} | Errores: {total_errores} | Cache: {total_cache} | FAQ: {total_faq}"
    return _wrap_html(
        "Mensajes por Día",
        f"Desde: {desde}  Hasta: {hasta}",
        ["Fecha", "Total", "Éxitos", "Errores", "Cache", "FAQ", "Latencia (ms)"],
        rows_html,
        total=total_row,
    )


def _template_completo(telefono: str, desde, hasta, rows: list[dict], push_name: str | None, overflow: bool) -> str:
    """Genera HTML para el reporte Historial Completo."""
    rows_html = "\n".join(
        f'<tr class="{"even" if i % 2 == 0 else "odd"}">'
        f'<td>{i + 1}</td>'
        f'<td>{_escape(r["fecha_hora"])}</td>'
        f'<td>{_escape(r["contenido"][:80] if r["contenido"] else "")}</td>'
        f'<td>{_escape(r["estado"])}</td>'
        f'<td>{_escape(str(r["latencia_ms"]) if r["latencia_ms"] is not None else "-")}</td></tr>'
        for i, r in enumerate(rows)
    )
    desde_str = desde or "inicio"
    hasta_str = hasta or "ahora"
    if push_name:
        title = f"Historial Completo: {push_name} ({telefono})"
    else:
        title = f"Historial Completo: {telefono}"

    total_text = f"Total: {len(rows)} mensajes"
    if overflow:
        total_text += " — Mostrando primeros 5000 de más de 5000 registros"

    return _wrap_html(
        title,
        f"Desde: {desde_str}  Hasta: {hasta_str}",
        ["#", "Fecha/Hora", "Mensaje", "Estado", "Latencia"],
        rows_html,
        total=total_text,
    )


# ─── Report Implementations ──────────────────────────────────────────────


class ReporteDiario(BaseReport):
    """Resumen diario: todos los mensajes del día anterior."""
    id = "diario"
    nombre = "Resumen Diario"
    descripcion = "Todos los mensajes del día anterior"
    parametros: list[ParamInfo] = []

    _sql = """
        SELECT to_char(created_at, 'HH24:MI') AS hora, remitente AS usuario,
          CASE WHEN error_code IS NOT NULL THEN 'error'
               WHEN cache_hit THEN 'cache' WHEN faq_hit THEN 'faq'
               ELSE 'exito' END AS estado,
          total_duration_ms AS latencia_ms,
          LEFT(texto, 50) AS mensaje_preview
        FROM telemetry.bot_messages
        WHERE created_at::date = CURRENT_DATE - 1
        ORDER BY created_at
    """

    async def generar(self, pool, params: dict) -> bytes:
        async with pool.acquire() as conn:
            rows = await conn.fetch(self._sql)

        rows_list = [
            {"hora": r["hora"], "usuario": r["usuario"], "estado": r["estado"],
             "latencia_ms": r["latencia_ms"], "mensaje_preview": r["mensaje_preview"] or ""}
            for r in rows
        ]

        html = _template_diario(
            f"Fecha: {(date.today() - timedelta(days=1)).isoformat()}",
            rows_list,
        )
        return _render_html_to_pdf(html)


class ReporteHistorialPorNumero(BaseReport):
    """Historial por número: diálogos de un teléfono en un rango de fechas."""
    id = "historial"
    nombre = "Historial por Número"
    descripcion = "Diálogos de un número en un rango de fechas"
    parametros = [
        ParamInfo("telefono", "Número de teléfono", "text", requerido=True),
        ParamInfo("desde", "Fecha desde", "date", requerido=False),
        ParamInfo("hasta", "Fecha hasta", "date", requerido=False),
    ]

    _sql = """
        SELECT to_char(created_at, 'DD/MM/YYYY HH24:MI') AS fecha_hora,
               'inbound' AS direccion,
               CASE WHEN error_code IS NOT NULL THEN 'error'
                    WHEN cache_hit THEN 'cache' WHEN faq_hit THEN 'faq'
                    ELSE 'exito' END AS estado,
               LEFT(COALESCE(texto, ''), 80) AS contenido_preview,
               total_duration_ms AS latencia_ms
        FROM telemetry.bot_messages
        WHERE (remitente LIKE '%' || $1 || '%' OR remitente LIKE '%' || $4 || '%')
          AND ($2::date IS NULL OR created_at >= $2::timestamptz)
          AND ($3::date IS NULL OR created_at <= $3::timestamptz + interval '1 day')
        ORDER BY created_at
    """

    async def generar(self, pool, params: dict) -> bytes:
        telefono = params["telefono"]
        desde_raw = params.get("desde") or None
        hasta_raw = params.get("hasta") or None
        desde = date.fromisoformat(desde_raw) if isinstance(desde_raw, str) else desde_raw
        hasta = date.fromisoformat(hasta_raw) if isinstance(hasta_raw, str) else hasta_raw

        # Normalize phone: strip "+" prefix and compute alternate form (with/without "549")
        tel_clean = telefono.lstrip("+")
        tel_alt = tel_clean[3:] if tel_clean.startswith("549") and len(tel_clean) > 3 else "549" + tel_clean

        async with pool.acquire() as conn:
            rows = await conn.fetch(self._sql, tel_clean, desde, hasta, tel_alt)

        html = _template_historial(telefono, desde, hasta, rows)
        return _render_html_to_pdf(html)


class ReporteMensajesPorDia(BaseReport):
    """Mensajes por día: conteo y latencia promedio por día."""
    id = "por-dia"
    nombre = "Mensajes por Día"
    descripcion = "Cantidad de mensajes atendidos por día en un rango"
    parametros = [
        ParamInfo("desde", "Fecha desde", "date", requerido=True),
        ParamInfo("hasta", "Fecha hasta", "date", requerido=True),
    ]

    _sql = """
        SELECT created_at::date AS fecha,
          COUNT(*) AS total_mensajes,
          COUNT(*) FILTER (WHERE error_code IS NULL AND NOT cache_hit AND NOT faq_hit) AS exitos,
          COUNT(*) FILTER (WHERE error_code IS NOT NULL) AS errores,
          COUNT(*) FILTER (WHERE cache_hit) AS cache_hits,
          COUNT(*) FILTER (WHERE faq_hit) AS faq_hits,
          COALESCE(ROUND(AVG(total_duration_ms)), 0) AS latencia_promedio_ms
        FROM telemetry.bot_messages
        WHERE created_at::date >= $1::date
          AND created_at::date <= $2::date
        GROUP BY 1 ORDER BY 1
    """

    async def generar(self, pool, params: dict) -> bytes:
        desde_raw = params["desde"]
        hasta_raw = params["hasta"]
        desde = date.fromisoformat(desde_raw) if isinstance(desde_raw, str) else desde_raw
        hasta = date.fromisoformat(hasta_raw) if isinstance(hasta_raw, str) else hasta_raw

        async with pool.acquire() as conn:
            rows = await conn.fetch(self._sql, desde, hasta)

        html = _template_por_dia(str(desde), str(hasta), rows)
        return _render_html_to_pdf(html)


class ReporteHistorialCompleto(BaseReport):
    """Historial completo: todos los mensajes de un teléfono, con cap de 5000 filas."""
    id = "completo"
    nombre = "Historial Completo de Cliente"
    descripcion = "Todos los mensajes intercambiados con un número"
    parametros = [
        ParamInfo("telefono", "Número de teléfono", "text", requerido=True),
        ParamInfo("desde", "Fecha desde", "date", requerido=False),
        ParamInfo("hasta", "Fecha hasta", "date", requerido=False),
    ]

    _sql = """
        SELECT to_char(created_at, 'DD/MM/YYYY HH24:MI') AS fecha_hora,
               'inbound' AS direccion,
               CASE WHEN error_code IS NOT NULL THEN 'error'
                    WHEN cache_hit THEN 'cache' WHEN faq_hit THEN 'faq'
                    ELSE 'exito' END AS estado,
               COALESCE(texto, '') AS contenido,
               total_duration_ms AS latencia_ms,
               push_name,
               error_code
        FROM telemetry.bot_messages
        WHERE (remitente LIKE '%' || $1 || '%' OR remitente LIKE '%' || $4 || '%')
          AND ($2::date IS NULL OR created_at >= $2::timestamptz)
          AND ($3::date IS NULL OR created_at <= $3::timestamptz + interval '1 day')
        ORDER BY created_at
        LIMIT 5001
    """

    async def generar(self, pool, params: dict) -> bytes:
        telefono = params["telefono"]
        desde_raw = params.get("desde") or None
        hasta_raw = params.get("hasta") or None
        desde = date.fromisoformat(desde_raw) if isinstance(desde_raw, str) else desde_raw
        hasta = date.fromisoformat(hasta_raw) if isinstance(hasta_raw, str) else hasta_raw

        # Normalize phone: strip "+" prefix and compute alternate form (with/without "549")
        tel_clean = telefono.lstrip("+")
        tel_alt = tel_clean[3:] if tel_clean.startswith("549") and len(tel_clean) > 3 else "549" + tel_clean

        async with pool.acquire() as conn:
            rows = await conn.fetch(self._sql, tel_clean, desde, hasta, tel_alt)

        overflow = len(rows) > 5000
        if overflow:
            rows = rows[:5000]

        push_name = rows[0]["push_name"] if rows else None

        html = _template_completo(telefono, desde, hasta, rows, push_name, overflow)
        return _render_html_to_pdf(html)


# ─── Public API ───────────────────────────────────────────────────────────


def listar_tipos() -> list[dict]:
    """Devuelve la lista de tipos de reporte disponibles con sus metadatos."""
    return [
        {
            "id": tipo_id,
            "nombre": cls.nombre,
            "descripcion": cls.descripcion,
            "parametros": [
                {"key": p.key, "label": p.label, "tipo": p.tipo, "requerido": p.requerido}
                for p in cls.parametros
            ],
        }
        for tipo_id, cls in _report_types.items()
    ]


async def generar_reporte(tipo: str, pool, params: dict) -> bytes:
    """Genera un reporte por tipo. Valida params antes de consultar la DB.

    Raises:
        ValueError: Si el tipo no existe o los params son inválidos.
    """
    cls = _report_types.get(tipo)
    if not cls:
        raise ValueError(f"Tipo de reporte '{tipo}' no encontrado")
    _validate_parametros(cls, params)
    return await cls().generar(pool, params)