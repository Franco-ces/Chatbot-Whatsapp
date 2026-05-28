import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sesionLoggerManager import SessionManager


class TestSessionManagerAsyncInteraction:

    def test_agregar_mensaje_creates_session(self):
        """REQ-8: Session manager creates session on first message."""
        sm = SessionManager(timeout_seconds=300, max_mensajes=6)

        sm.agregar_mensaje("54911", "Hola", es_bot=False, push_name="TestUser")

        sesion = sm.obtener_sesion("54911")
        assert sesion is not None
        assert sesion["contact_name"] == "TestUser"

    def test_agregar_mensaje_appends_context(self):
        """REQ-8: Messages are added to session context."""
        sm = SessionManager(timeout_seconds=300, max_mensajes=6)

        sm.agregar_mensaje("54911", "Hola", es_bot=False, push_name="User")
        sm.agregar_mensaje("54911", "Respuesta", es_bot=True)

        contexto = sm.obtener_contexto("54911")
        assert "Hola" in contexto
        assert "Respuesta" in contexto

    def test_session_context_respects_max_messages(self):
        """REQ-8: Context window respects max_mensajes limit."""
        sm = SessionManager(timeout_seconds=300, max_mensajes=3)

        for i in range(5):
            sm.agregar_mensaje("54911", f"msg-{i}", es_bot=False)

        contexto = sm.obtener_contexto("54911")
        lines = contexto.strip().split("\n")
        assert len(lines) <= 3

    def test_limpieza_sesiones_expiradas(self):
        """REQ-8: Expired sessions are cleaned up."""
        sm = SessionManager(timeout_seconds=0, max_mensajes=6)

        sm.agregar_mensaje("54911", "Hola", es_bot=False)
        sm.limpiar_sesiones_expiradas()

        assert sm.obtener_sesion("54911") is None

    def test_sesion_activa_no_se_limpia(self):
        """REQ-8: Active sessions are not cleaned up."""
        sm = SessionManager(timeout_seconds=300, max_mensajes=6)

        sm.agregar_mensaje("54911", "Hola", es_bot=False)
        sm.limpiar_sesiones_expiradas()

        assert sm.obtener_sesion("54911") is not None

    def test_multiple_sessions_independent(self):
        """REQ-8: Different phone numbers have independent sessions."""
        sm = SessionManager(timeout_seconds=300, max_mensajes=6)

        sm.agregar_mensaje("54911", "Hola uno", es_bot=False)
        sm.agregar_mensaje("54922", "Hola dos", es_bot=False)

        ctx1 = sm.obtener_contexto("54911")
        ctx2 = sm.obtener_contexto("54922")

        assert "uno" in ctx1
        assert "dos" in ctx2
        assert "dos" not in ctx1
