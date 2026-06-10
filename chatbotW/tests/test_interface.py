"""Tests for admin interface endpoints (Evolution instance management, API keys).

Uses httpx ASGITransport to test FastAPI endpoints through middleware,
mocking the evolution_admin module-level variable.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from error_codes import ErrorCode
from exceptions import APIError


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def auth_token():
    """Devuelve un JWT válido contra la SECRET_KEY en uso de la app."""
    from jose import jwt
    import interface
    return jwt.encode({"sub": "admin"}, interface.SECRET_KEY, algorithm="HS256")


@pytest.fixture
async def client(auth_token):
    """AsyncClient ASGI contra interface.app."""
    import interface
    transport = httpx.ASGITransport(app=interface.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = f"Bearer {auth_token}"
        yield c


@pytest.fixture(autouse=True)
def _patch_evolution_admin():
    """Reemplaza evolution_admin en interface module con un MagicMock.

    Todos los endpoints de Evolution llaman a este objeto; cada test
    configura el mock especifico que necesita.
    """
    import interface
    fake = MagicMock()
    fake.list_instances = AsyncMock(return_value=[])
    fake.create_instance = AsyncMock()
    fake.get_qr = AsyncMock()
    fake.get_state = AsyncMock()
    fake.delete_instance = AsyncMock()
    fake.set_webhook = AsyncMock()
    fake.get_webhook = AsyncMock()
    with patch.object(interface, "evolution_admin", fake):
        yield fake


# ─── T11: POST /api/evolution/instances with 401 ───────────────────────────


class TestCreateInstance:
    async def test_create_instance_works_without_evolution(self, client, _patch_evolution_admin):
        """Happy path: creacion exitosa con mock."""
        from evolution_models import InstanceInfo, ConnectionState
        fake = _patch_evolution_admin
        fake.create_instance = AsyncMock()
        fake.create_instance.return_value = InstanceInfo.model_validate({
            "name": "bot_test", "connectionState": "close"
        })
        payload = {"name": "bot_test"}
        resp = await client.post("/api/evolution/instances", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "bot_test"

    async def test_401_from_evolution_raises_api_unauthorized(self, client, _patch_evolution_admin):
        """GIVEN Evolution returns 401 (unset API key)
        WHEN POST /api/evolution/instances
        THEN handler MUST catch API_UNAUTHORIZED."""
        fake = _patch_evolution_admin
        fake.create_instance = AsyncMock(
            side_effect=APIError(
                ErrorCode.API_UNAUTHORIZED,
                detail="API key de Evolution no configurada (create_instance(test))",
            )
        )

        payload = {"name": "test"}
        resp = await client.post("/api/evolution/instances", json=payload)

        # The global error handler returns API_UNAUTHORIZED.http_status (401)
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == ErrorCode.API_UNAUTHORIZED.value
        assert "API key" in body["error"]["detail"]

    async def test_400_duplicate_name_still_works(self, client, _patch_evolution_admin):
        """GIVEN Evolution returns 400 for duplicate name
        WHEN POST /api/evolution/instances
        THEN it MUST still return 409 con EVO_INSTANCE_ALREADY_EXISTS."""
        fake = _patch_evolution_admin
        fake.create_instance = AsyncMock(
            side_effect=APIError(
                ErrorCode.API_INVALID_PAYLOAD,
                detail="instance already exists",
            )
        )

        payload = {"name": "duplicate"}
        resp = await client.post("/api/evolution/instances", json=payload)

        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == ErrorCode.EVO_INSTANCE_ALREADY_EXISTS.value


# ─── T12: POST /api/evolution-apikey ──────────────────────────────────────


class TestEvolutionApiKeyEndpoint:
    async def test_saves_key_and_returns_success(self, client):
        """GIVEN a valid key string
        WHEN POST /api/evolution-apikey with form data
        THEN it MUST save the key and return 200 with restart instruction."""
        import interface

        with patch.object(interface, "_write_env") as mock_write:
            resp = await client.post(
                "/api/evolution-apikey",
                data={"key": "evo-key-123"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert "API key guardada" in body["message"]
        assert "contenedor" in body["message"]

        mock_write.assert_called_once_with("EVO_API_KEY", "evo-key-123")
        assert "EVO_API_KEY" in interface.os.environ
        assert interface.os.environ["EVO_API_KEY"] == "evo-key-123"

    async def test_returns_error_on_write_failure(self, client):
        """GIVEN _write_env raises an exception
        WHEN POST /api/evolution-apikey
        THEN it MUST return 500."""
        import interface

        with patch.object(interface, "_write_env", side_effect=OSError("permission denied")):
            resp = await client.post(
                "/api/evolution-apikey",
                data={"key": "evo-key-123"},
            )

        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == ErrorCode.CFG_WRITE_FAILED.value


# ─── T13: DELETE /api/evolution/instances con safety check activa ──────────


class TestDeleteEvolutionInstance:
    """TDD for fix-delete-active-check: validate state before blocking delete.

    All 7 tests: RED phase first — must fail because production code does
    NOT yet call get_state on the active instance check.
    """

    async def test_delete_active_close_allows_delete(self, client, _patch_evolution_admin):
        """GIVEN instance matches active name AND get_state returns CLOSE → 204."""
        import interface
        from evolution_models import ConnectionState
        fake = _patch_evolution_admin
        fake.get_state = AsyncMock(return_value=ConnectionState.CLOSE)
        fake.delete_instance = AsyncMock()

        with patch.object(interface.config_manager, 'cargar'), \
             patch.object(interface.config_manager, 'config', {"active_instance_name": "test-instance"}):
            resp = await client.delete("/api/evolution/instances/test-instance")

        assert resp.status_code == 204
        fake.get_state.assert_awaited_once_with("test-instance")

    async def test_delete_active_connecting_allows_delete(self, client, _patch_evolution_admin):
        """GIVEN instance matches active name AND get_state returns CONNECTING → 204."""
        import interface
        from evolution_models import ConnectionState
        fake = _patch_evolution_admin
        fake.get_state = AsyncMock(return_value=ConnectionState.CONNECTING)
        fake.delete_instance = AsyncMock()

        with patch.object(interface.config_manager, 'cargar'), \
             patch.object(interface.config_manager, 'config', {"active_instance_name": "test-instance"}):
            resp = await client.delete("/api/evolution/instances/test-instance")

        assert resp.status_code == 204
        fake.get_state.assert_awaited_once_with("test-instance")

    async def test_delete_active_unknown_allows_delete(self, client, _patch_evolution_admin):
        """GIVEN instance matches active name AND get_state returns UNKNOWN → 204."""
        import interface
        from evolution_models import ConnectionState
        fake = _patch_evolution_admin
        fake.get_state = AsyncMock(return_value=ConnectionState.UNKNOWN)
        fake.delete_instance = AsyncMock()

        with patch.object(interface.config_manager, 'cargar'), \
             patch.object(interface.config_manager, 'config', {"active_instance_name": "test-instance"}):
            resp = await client.delete("/api/evolution/instances/test-instance")

        assert resp.status_code == 204
        fake.get_state.assert_awaited_once_with("test-instance")

    async def test_delete_active_open_blocks_delete(self, client, _patch_evolution_admin):
        """GIVEN instance matches active name AND get_state returns OPEN → 409."""
        import interface
        from evolution_models import ConnectionState
        fake = _patch_evolution_admin
        fake.get_state = AsyncMock(return_value=ConnectionState.OPEN)

        with patch.object(interface.config_manager, 'cargar'), \
             patch.object(interface.config_manager, 'config', {"active_instance_name": "test-instance"}):
            resp = await client.delete("/api/evolution/instances/test-instance")

        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == ErrorCode.EVO_INSTANCE_ACTIVE.value
        fake.get_state.assert_awaited_once_with("test-instance")
        fake.delete_instance.assert_not_awaited()

    async def test_delete_get_state_communication_error_returns_503(self, client, _patch_evolution_admin):
        """GIVEN instance matches active name AND get_state raises CommunicationError → 503."""
        import interface
        from exceptions import CommunicationError
        fake = _patch_evolution_admin
        fake.get_state = AsyncMock(
            side_effect=CommunicationError(ErrorCode.SYS_UNEXPECTED, "connection failed")
        )

        with patch.object(interface.config_manager, 'cargar'), \
             patch.object(interface.config_manager, 'config', {"active_instance_name": "test-instance"}):
            resp = await client.delete("/api/evolution/instances/test-instance")

        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == ErrorCode.SYS_DEPENDENCY_MISSING.value
        fake.delete_instance.assert_not_awaited()

    async def test_delete_get_state_not_found_returns_404(self, client, _patch_evolution_admin):
        """GIVEN instance matches active name AND get_state raises APIError(API_NOT_FOUND) → 404."""
        import interface
        fake = _patch_evolution_admin
        fake.get_state = AsyncMock(
            side_effect=APIError(ErrorCode.API_NOT_FOUND, detail="not found")
        )

        with patch.object(interface.config_manager, 'cargar'), \
             patch.object(interface.config_manager, 'config', {"active_instance_name": "test-instance"}):
            resp = await client.delete("/api/evolution/instances/test-instance")

        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == ErrorCode.API_NOT_FOUND.value
        fake.delete_instance.assert_not_awaited()

    async def test_delete_non_active_instance_succeeds(self, client, _patch_evolution_admin):
        """GIVEN instance name DIFFERS from active name → 204 (get_state NOT called)."""
        import interface
        fake = _patch_evolution_admin
        fake.delete_instance = AsyncMock()

        with patch.object(interface.config_manager, 'cargar'), \
             patch.object(interface.config_manager, 'config', {"active_instance_name": "other-instance"}):
            resp = await client.delete("/api/evolution/instances/test-instance")

        assert resp.status_code == 204
        fake.get_state.assert_not_awaited()
