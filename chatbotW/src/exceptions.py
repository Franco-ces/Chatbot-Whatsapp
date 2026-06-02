from error_codes import ErrorCode


class AppError(Exception):
    def __init__(self, code: ErrorCode, detail: str = "", cause: Exception | None = None):
        self.code = code
        self.detail = detail or code.user_message
        self.cause = cause
        super().__init__(f"[{code.value}] {code.user_message}")


class CommunicationError(AppError):
    """Fallo de transporte o de respuesta HTTP de un servicio externo.

    Extiende `AppError` con dos campos opcionales: `status_code` y
    `response_body`, que el cliente HTTP (ver `evolution_http`) puebla
    cuando la respuesta vino del servidor pero con código no-2xx. Eso
    permite a las capas de arriba (admin) mapear 404 → `API_NOT_FOUND`,
    400 → `API_INVALID_PAYLOAD`, etc., sin volver a leer el response.
    """

    def __init__(
        self,
        code: ErrorCode,
        detail: str = "",
        cause: Exception | None = None,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        super().__init__(code, detail, cause)
        self.status_code = status_code
        self.response_body = response_body


class RAGError(AppError):
    pass


class ConfigError(AppError):
    pass


class APIError(AppError):
    pass
