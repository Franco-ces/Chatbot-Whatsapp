"""report_generator.py — Módulo de generación de reportes PDF.

Provee un registro de tipos de reporte (registry pattern) y funciones
para listar tipos y generar PDFs desde datos de telemetría PostgreSQL.

Patrón: BaseReport + __init_subclass__ auto-registro. Agregar un nuevo
reporte = agregar una subclase con `id`, `nombre`, `descripcion`,
`parametros` y `generar()`. No se necesita tocar endpoints.

Las consultas SQL leen de `telemetry.bot_messages`. Los PDFs se generan
con FPDF2 (Helvetica built-in, sin TTF externo).
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from fpdf import FPDF

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


# ─── PDF Builder ──────────────────────────────────────────────────────────


class PDFReport(FPDF):
    """FPDF subclass con header/footer para reportes."""

    def __init__(self):
        super().__init__()
        self.compress = False  # Uncompressed for testability; reports are small
        self._report_title = ""
        self._footer_text = ""

    def set_report_meta(self, title: str, footer_text: str = ""):
        self._report_title = title
        self._footer_text = footer_text

    def header(self):
        # Logo placeholder: 40×10mm bordered area
        self.set_font("Helvetica", "B", 9)
        self.cell(40, 10, "[LOGO]", border=1, align="C")
        # Report name + timestamp on the right
        self.set_font("Helvetica", "", 9)
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.cell(0, 10, f"{self._report_title} - {timestamp}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        # Footer text center
        self.cell(0, 10, self._footer_text, align="C")
        # Page number right
        self.cell(0, 10, f"Página {self.page_no()}/{{nb}}", align="R")

    def render_table(self, title: str, headers: list[str], rows: list[list[str]],
                     col_widths: list[float] | None = None,
                     totals_row: list[str] | None = None):
        """Render a title + table with alternating row colors and optional totals."""
        # Title
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 10, title, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(5)

        n_cols = len(headers)
        if col_widths is None:
            col_widths = [190 / n_cols] * n_cols

        # Header row (gray background)
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(200, 200, 200)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, align="C", fill=True)
        self.ln()

        # Data rows (alternating fill)
        self.set_font("Helvetica", "", 9)
        for i, row in enumerate(rows):
            if i % 2 == 0:
                self.set_fill_color(240, 240, 240)
            else:
                self.set_fill_color(255, 255, 255)
            for j, cell in enumerate(row):
                self.cell(col_widths[j], 6, str(cell), border=1, fill=True)
            self.ln()

        # Totals row
        if totals_row:
            self.set_font("Helvetica", "B", 9)
            self.set_fill_color(200, 200, 200)
            for j, cell in enumerate(totals_row):
                self.cell(col_widths[j], 7, str(cell), border=1, fill=True)
            self.ln()


def _build_pdf(titulo: str, headers: list[str], rows: list[list[str]],
               col_widths: list[float] | None = None,
               totals_row: list[str] | None = None,
               header_text: str = "",
               footer_text: str = "") -> bytes:
    """Construye un PDF con header, footer, título y tabla. Devuelve bytes."""
    pdf = PDFReport()
    pdf.alias_nb_pages()
    pdf.set_report_meta(titulo, footer_text)
    pdf.add_page()

    if header_text:
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, header_text)
        pdf.ln(5)

    pdf.render_table(titulo, headers, rows, col_widths, totals_row)

    return bytes(pdf.output())


# ─── Report Implementations ──────────────────────────────────────────────


class ReporteDiario(BaseReport):
    """Resumen diario: todos los mensajes del día anterior."""
    id = "diario"
    nombre = "Resumen Diario"
    descripcion = "Todos los mensajes del día anterior"
    parametros: list[ParamInfo] = []

    _sql = """
        SELECT created_at::time AS hora, remitente AS usuario,
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

        data = [
            [str(r["hora"]), str(r["usuario"]), str(r["estado"]),
             str(r["latencia_ms"]) if r["latencia_ms"] is not None else "-",
             str(r["mensaje_preview"] or "")]
            for r in rows
        ]

        total = len(rows)
        totals_row = [f"Total: {total} mensajes", "", "", "", ""]

        return _build_pdf(
            "Resumen Diario",
            ["Hora", "Usuario", "Estado", "Latencia (ms)", "Mensaje"],
            data,
            col_widths=[25, 45, 25, 30, 65],
            totals_row=totals_row,
            header_text=f"Informe del día anterior ({(date.today().offset if hasattr(date.today(), 'offset') else '')})",
        )


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
        WHERE remitente = $1
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

        async with pool.acquire() as conn:
            rows = await conn.fetch(self._sql, telefono, desde, hasta)

        data = [
            [str(i + 1), str(r["fecha_hora"]), str(r["contenido_preview"]),
              str(r["estado"]), str(r["latencia_ms"]) if r["latencia_ms"] is not None else "-"]
            for i, r in enumerate(rows)
        ]
        totals_row = [f"Total: {len(rows)}", "", "", "", ""]

        desde_str = desde or "inicio"
        hasta_str = hasta or "ahora"
        return _build_pdf(
            f"Historial: {telefono}",
            ["#", "Fecha/Hora", "Mensaje", "Estado", "Latencia"],
            data,
            col_widths=[10, 35, 75, 35, 35],
            totals_row=totals_row,
            header_text=f"Desde: {desde_str}  Hasta: {hasta_str}",
        )


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

        data = [
            [str(r["fecha"]), str(r["total_mensajes"]), str(r["exitos"]),
             str(r["errores"]), str(r["cache_hits"]), str(r["faq_hits"]),
             str(r["latencia_promedio_ms"])]
            for r in rows
        ]

        total_msgs = sum(r["total_mensajes"] for r in rows) if rows else 0
        total_exitos = sum(r["exitos"] for r in rows) if rows else 0
        total_errores = sum(r["errores"] for r in rows) if rows else 0
        total_cache = sum(r["cache_hits"] for r in rows) if rows else 0
        total_faq = sum(r["faq_hits"] for r in rows) if rows else 0
        totals_row = [
            "Total", str(total_msgs), str(total_exitos),
            str(total_errores), str(total_cache), str(total_faq), "-"
        ]

        return _build_pdf(
            "Mensajes por Día",
            ["Fecha", "Total", "Éxitos", "Errores", "Cache", "FAQ", "Latencia (ms)"],
            data,
            col_widths=[30, 25, 25, 25, 25, 25, 35],
            totals_row=totals_row,
            header_text=f"Desde: {desde}  Hasta: {hasta}",
        )


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
        WHERE remitente = $1
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

        async with pool.acquire() as conn:
            rows = await conn.fetch(self._sql, telefono, desde, hasta)

        overflow = len(rows) > 5000
        if overflow:
            rows = rows[:5000]

        push_name = rows[0]["push_name"] if rows else None

        data = [
            [str(i + 1), str(r["fecha_hora"]), str(r["contenido"])[:80],
             str(r["estado"]), str(r["latencia_ms"]) if r["latencia_ms"] is not None else "-"]
            for i, r in enumerate(rows)
        ]

        footer_text = ""
        if overflow:
            footer_text = f"Mostrando primeros 5000 de más de 5000 registros"

        totals_row = [f"Total: {len(rows)} mensajes", "", "", "", ""]

        desde_str = desde or "inicio"
        hasta_str = hasta or "ahora"
        titulo = f"Historial Completo: {push_name} ({telefono})" if push_name else f"Historial Completo: {telefono}"

        return _build_pdf(
            titulo,
            ["#", "Fecha/Hora", "Mensaje", "Estado", "Latencia"],
            data,
            col_widths=[10, 35, 75, 35, 35],
            totals_row=totals_row,
            header_text=f"Desde: {desde_str}  Hasta: {hasta_str}",
            footer_text=footer_text,
        )


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