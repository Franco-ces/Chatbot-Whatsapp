import time as time_module

import pytest

from sesionLoggerManager import SessionManager


NOW = 1000.0


@pytest.fixture
def manager(mocker):
    mocker.patch("sesionLoggerManager.ChatLogger")
    mocker.patch("sesionLoggerManager.time.time", return_value=NOW)
    return SessionManager(timeout_seconds=300)


class TestCrearSesion:

    def test_crea_entrada_con_logger_y_contexto(self, manager):
        sesion = manager.crear_sesion("54911")
        assert "logger" in sesion
        assert sesion["contexto"] == []
        assert sesion["last_activity"] == NOW

    def test_sobrescribe_sesion_existente(self, manager):
        manager.crear_sesion("54911")
        sesion2 = manager.crear_sesion("54911")
        assert manager.sessions["54911"] is sesion2


class TestObtenerSesion:

    def test_retorna_sesion_existente(self, manager):
        manager.crear_sesion("54911")
        sesion = manager.obtener_sesion("54911")
        assert sesion is not None

    def test_retorna_none_si_no_existe(self, manager):
        assert manager.obtener_sesion("999") is None


class TestAgregarMensaje:

    def test_crea_sesion_si_no_existe(self, manager):
        manager.agregar_mensaje("54911", "hola")
        assert "54911" in manager.sessions

    def test_agrega_al_contexto(self, manager):
        manager.agregar_mensaje("54911", "hola", es_bot=False)
        contexto = manager.obtener_contexto("54911")
        assert "USER: hola" in contexto

    def test_contexto_bot(self, manager):
        manager.agregar_mensaje("54911", "respuesta", es_bot=True)
        contexto = manager.obtener_contexto("54911")
        assert "BOT: respuesta" in contexto

    def test_resetea_timer(self, mocker, manager):
        manager.agregar_mensaje("54911", "msg1")
        mocker.patch("sesionLoggerManager.time.time", return_value=NOW + 10)
        manager.agregar_mensaje("54911", "msg2")
        assert manager.sessions["54911"]["last_activity"] == NOW + 10

    def test_limite_max_mensajes(self, manager):
        manager.max_mensajes = 2
        manager.agregar_mensaje("54911", "msg1")
        manager.agregar_mensaje("54911", "msg2")
        manager.agregar_mensaje("54911", "msg3")
        contexto = manager.obtener_contexto("54911")
        assert "msg1" not in contexto
        assert "msg2" in contexto
        assert "msg3" in contexto


class TestObtenerContexto:

    def test_vacio_si_no_hay_sesion(self, manager):
        assert manager.obtener_contexto("999") == ""

    def test_vacio_si_contexto_vacio(self, manager):
        manager.crear_sesion("54911")
        assert manager.obtener_contexto("54911") == ""

    def test_une_mensajes_con_newline(self, manager):
        manager.agregar_mensaje("54911", "primero")
        manager.agregar_mensaje("54911", "segundo")
        ctx = manager.obtener_contexto("54911")
        assert ctx.endswith("\n")
        assert "USER: primero" in ctx
        assert "USER: segundo" in ctx


class TestLimpiarSesionesExpiradas:
    # Usar un manager SIN patch global de time.time para manipular last_activity directamente
    def test_elimina_sesion_expirada(self, mocker):
        mocker.patch("sesionLoggerManager.ChatLogger")
        fixed_time = 2000.0
        mocker.patch("sesionLoggerManager.time.time", return_value=fixed_time)
        m = SessionManager(timeout_seconds=300)
        m.crear_sesion("54911")
        m.sessions["54911"]["last_activity"] = fixed_time - 400

        m.limpiar_sesiones_expiradas()

        assert "54911" not in m.sessions

    def test_conserva_sesion_activa(self, mocker):
        mocker.patch("sesionLoggerManager.ChatLogger")
        fixed_time = 2000.0
        mocker.patch("sesionLoggerManager.time.time", return_value=fixed_time)
        m = SessionManager(timeout_seconds=300)
        m.crear_sesion("54911")
        m.sessions["54911"]["last_activity"] = fixed_time - 100

        m.limpiar_sesiones_expiradas()

        assert "54911" in m.sessions

    def test_solo_elimina_expiradas_en_mezcla(self, mocker):
        mocker.patch("sesionLoggerManager.ChatLogger")
        fixed_time = 2000.0
        mocker.patch("sesionLoggerManager.time.time", return_value=fixed_time)
        m = SessionManager(timeout_seconds=300)
        m.crear_sesion("activo")
        m.crear_sesion("expirado")
        m.crear_sesion("otro_activo")
        m.sessions["expirado"]["last_activity"] = fixed_time - 400
        m.sessions["activo"]["last_activity"] = fixed_time - 50
        m.sessions["otro_activo"]["last_activity"] = fixed_time - 200

        m.limpiar_sesiones_expiradas()

        assert "activo" in m.sessions
        assert "otro_activo" in m.sessions
        assert "expirado" not in m.sessions

    def test_finaliza_log_al_limpiar(self, mocker):
        mocker.patch("sesionLoggerManager.ChatLogger")
        fixed_time = 2000.0
        mocker.patch("sesionLoggerManager.time.time", return_value=fixed_time)
        m = SessionManager(timeout_seconds=300)
        m.crear_sesion("54911")
        m.sessions["54911"]["last_activity"] = fixed_time - 400
        logger_mock = m.sessions["54911"]["logger"]

        m.limpiar_sesiones_expiradas()

        logger_mock.finalizar_log.assert_called_once()

    def test_no_finaliza_log_de_activas(self, mocker):
        mocker.patch("sesionLoggerManager.ChatLogger")
        fixed_time = 2000.0
        mocker.patch("sesionLoggerManager.time.time", return_value=fixed_time)
        m = SessionManager(timeout_seconds=300)
        m.crear_sesion("54911")
        m.sessions["54911"]["last_activity"] = fixed_time - 100
        logger_mock = m.sessions["54911"]["logger"]

        m.limpiar_sesiones_expiradas()

        logger_mock.finalizar_log.assert_not_called()
