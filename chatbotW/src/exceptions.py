from error_codes import ErrorCode


class AppError(Exception):
    def __init__(self, code: ErrorCode, detail: str = "", cause: Exception | None = None):
        self.code = code
        self.detail = detail or code.user_message
        self.cause = cause
        super().__init__(f"[{code.value}] {code.user_message}")


class CommunicationError(AppError):
    pass


class RAGError(AppError):
    pass


class ConfigError(AppError):
    pass


class APIError(AppError):
    pass
