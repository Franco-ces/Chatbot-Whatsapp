from enum import Enum


class ErrorCode(str, Enum):
    # Communication errors (E-COM)
    COM_CONNECTION_FAILED = "E-COM-001"
    COM_SEND_MESSAGE_FAILED = "E-COM-002"
    COM_GET_AUDIO_FAILED = "E-COM-003"
    EVO_INSTANCE_NOT_LINKED = "E-COM-004"
    EVO_INSTANCE_ALREADY_EXISTS = "E-COM-005"
    EVO_INSTANCE_ACTIVE = "E-COM-006"
    EVO_WEBHOOK_FAILED = "E-COM-007"

    # RAG errors (E-RAG)
    RAG_NO_PDFS = "E-RAG-001"
    RAG_QUERY_FAILED = "E-RAG-002"
    RAG_AUDIO_FAILED = "E-RAG-003"

    # Config errors (E-CFG)
    CFG_READ_FAILED = "E-CFG-001"
    CFG_WRITE_FAILED = "E-CFG-002"

    # API errors (E-API)
    API_INVALID_PAYLOAD = "E-API-001"
    API_NOT_FOUND = "E-API-002"
    API_SERVER_ERROR = "E-API-003"
    API_UNAUTHORIZED = "E-API-004"

    # System errors (E-SYS)
    SYS_UNEXPECTED = "E-SYS-001"
    SYS_DEPENDENCY_MISSING = "E-SYS-002"

    # FAQ errors (E-FAQ)
    FAQ_INVALID_DATA = "E-FAQ-001"
    FAQ_WRITE_FAILED = "E-FAQ-002"
    FAQ_NOT_FOUND = "E-FAQ-003"

    @property
    def user_message(self) -> str:
        return _USER_MESSAGES[self]

    @property
    def http_status(self) -> int:
        return _HTTP_STATUSES.get(self, 500)


_USER_MESSAGES = {
    ErrorCode.COM_CONNECTION_FAILED: "No se pudo conectar con el servicio de mensajería.",
    ErrorCode.COM_SEND_MESSAGE_FAILED: "No se pudo enviar el mensaje. Intente de nuevo más tarde.",
    ErrorCode.COM_GET_AUDIO_FAILED: "No se pudo procesar el mensaje de audio.",
    ErrorCode.EVO_INSTANCE_NOT_LINKED: "La instancia no está vinculada. Escaneá el QR primero.",
    ErrorCode.EVO_INSTANCE_ALREADY_EXISTS: "Ya existe una instancia con ese nombre.",
    ErrorCode.EVO_INSTANCE_ACTIVE: "No podés eliminar la instancia activa. Primero activá otra.",
    ErrorCode.EVO_WEBHOOK_FAILED: "No se pudo desactivar el webhook de la instancia anterior.",
    ErrorCode.RAG_NO_PDFS: "El sistema no tiene manuales cargados para consultar.",
    ErrorCode.RAG_QUERY_FAILED: "Ocurrió un error al procesar su consulta.",
    ErrorCode.RAG_AUDIO_FAILED: "No se pudo procesar el audio.",
    ErrorCode.CFG_READ_FAILED: "Error interno de configuración.",
    ErrorCode.CFG_WRITE_FAILED: "Error interno al guardar configuración.",
    ErrorCode.API_INVALID_PAYLOAD: "Solicitud inválida.",
    ErrorCode.API_NOT_FOUND: "Recurso no encontrado.",
    ErrorCode.API_SERVER_ERROR: "Error interno del servidor.",
    ErrorCode.API_UNAUTHORIZED: "Acceso no autorizado.",
    ErrorCode.SYS_UNEXPECTED: "Ocurrió un error inesperado.",
    ErrorCode.SYS_DEPENDENCY_MISSING: "El sistema no está correctamente inicializado.",
    ErrorCode.FAQ_INVALID_DATA: "Datos inválidos para la FAQ.",
    ErrorCode.FAQ_WRITE_FAILED: "No se pudo guardar la FAQ en disco.",
    ErrorCode.FAQ_NOT_FOUND: "FAQ no encontrada.",
}

_HTTP_STATUSES = {
    ErrorCode.API_INVALID_PAYLOAD: 400,
    ErrorCode.API_NOT_FOUND: 404,
    ErrorCode.API_SERVER_ERROR: 500,
    ErrorCode.API_UNAUTHORIZED: 401,
    ErrorCode.EVO_INSTANCE_NOT_LINKED: 409,
    ErrorCode.EVO_INSTANCE_ALREADY_EXISTS: 409,
    ErrorCode.EVO_INSTANCE_ACTIVE: 409,
    ErrorCode.RAG_NO_PDFS: 503,
    ErrorCode.SYS_DEPENDENCY_MISSING: 503,
    ErrorCode.FAQ_INVALID_DATA: 400,
    ErrorCode.FAQ_WRITE_FAILED: 500,
    ErrorCode.FAQ_NOT_FOUND: 404,
}
