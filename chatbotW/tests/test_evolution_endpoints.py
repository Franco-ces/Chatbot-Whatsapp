"""Tests para los 5 endpoints admin de Evolution (`/api/evolution/*`).

Cubre los escenarios del spec evolution-instance-admin (PR 4):
- GET /api/evolution/instances: 200 con lista, vacia, 401 sin auth.
- POST /api/evolution/instances: 201 happy, 409 duplicate, 400 regex fail.
- GET /api/evolution/instances/{name}/qr: 200 con qr+state.
- GET /api/evolution/instances/{name}/state: 200 con state.
- POST /api/evolution/active: 200 happy (re-verify + bridge), 409 drift.

Estrategia: mockeamos `interface.evolution_admin` (instancia a nivel
de modulo, expuesta para tests) y `interface.config_manager`. El
bridge `instance_activation.set_active` se mockea en los tests del
endpoint /active. No tocamos disco: la escritura atomica va por el
mismo path mockeado.

Como el AuthMiddleware corre real (mismo fixture que test_faq_endpoints),
los tests de 'sin auth -> 401' son una regresion viva del path
namespace: si alguien mueve el prefijo fuera de /api/*, estos tests
fallan y el contrato se rompe.
"""
import importlib
import os
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from jose import jwt

import interface


# ---------------------------------------------------------------------------
# Fixtures compartidos
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_token():
    """JWT valido contra la SECRET_KEY del modulo interface."""
    return jwt.encode({"sub": "admin"}, interface.SECRET_KEY, algorithm="HS256")


@pytest.fixture
def bot_url(monkeypatch):
    """Setea BOT_URL en el env del proceso para que el endpoint
    configure el webhook al crear instancias. Sin esto, el codigo
    skipea el setup (ver `create_evolution_instance` en interface.py)
    y los tests de webhook quedan mudos."""
    monkeypatch.setenv("BOT_URL", "http://bot.local:5000")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret-xyz")
    return "http://bot.local:5000"


@pytest.fixture
async def client():
    """AsyncClient ASGI contra interface.app. AuthMiddleware corre real."""
    transport = httpx.ASGITransport(app=interface.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_instance(name, state="close"):
    """Helper rapido: contruye un InstanceInfo minimo sin HTTP."""
    from evolution_models import ConnectionState, InstanceInfo
    return InstanceInfo.model_validate({"name": name, "connectionState": state})


def _patch_admin(mocker, *, list_return=None, create_return=None,
                 create_side_effect=None, qr_return=None, state_return=None,
                 set_webhook_side_effect=None):
    """Reemplaza `interface.evolution_admin` por un mock controlable.

    Devuelve el mock para que cada test inspeccione los call_args.
    Solo se asignan los metodos que el test usa; el resto queda como
    MagicMock generico (no se invoca).

    `set_webhook_side_effect` (opcional) deja que el test fuerce un
    fallo del setup de webhook para verificar la rama de warning.
    """
    fake = MagicMock()
    fake.list_instances = AsyncMock(return_value=list_return if list_return is not None else [])
    if create_side_effect is not None:
        fake.create_instance = AsyncMock(side_effect=create_side_effect)
    else:
        fake.create_instance = AsyncMock(return_value=create_return)
    fake.get_qr = AsyncMock(return_value=qr_return)
    fake.get_state = AsyncMock(return_value=state_return)
    if set_webhook_side_effect is not None:
        fake.set_webhook = AsyncMock(side_effect=set_webhook_side_effect)
    else:
        # Por default el setup de webhook "funciona" (AsyncMock no-op).
        # Asi los tests viejos no fallan por un mock que no se invoca.
        fake.set_webhook = AsyncMock(return_value=None)
    mocker.patch.object(interface, "evolution_admin", fake)
    return fake


# ---------------------------------------------------------------------------
# GET /api/evolution/instances
# ---------------------------------------------------------------------------

class TestListInstances:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.get("/api/evolution/instances")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_lista_poblada_devuelve_200(self, mocker, client, auth_token):
        _patch_admin(mocker, list_return=[
            _make_instance("a", "open"),
            _make_instance("b", "close"),
        ])
        resp = await client.get(
            "/api/evolution/instances", headers=_auth(auth_token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "instances" in body
        assert len(body["instances"]) == 2
        assert body["instances"][0]["name"] == "a"
        # Alias camelCase: connectionState (no connection_state)
        assert body["instances"][0]["connectionState"] == "open"

    @pytest.mark.asyncio
    async def test_lista_vacia_devuelve_200_con_array(self, mocker, client, auth_token):
        _patch_admin(mocker, list_return=[])
        resp = await client.get(
            "/api/evolution/instances", headers=_auth(auth_token)
        )
        assert resp.status_code == 200
        assert resp.json() == {"instances": []}


# ---------------------------------------------------------------------------
# POST /api/evolution/instances
# ---------------------------------------------------------------------------

class TestCreateInstance:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.post("/api/evolution/instances", json={"name": "bot_2"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_happy_path_devuelve_201_con_name_y_state(
        self, mocker, client, auth_token
    ):
        _patch_admin(mocker, create_return=_make_instance("bot_2", "close"))
        resp = await client.post(
            "/api/evolution/instances",
            json={"name": "bot_2"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "bot_2"
        assert body["connectionState"] == "close"

    @pytest.mark.asyncio
    async def test_nombre_duplicado_devuelve_409(self, mocker, client, auth_token):
        """Evolution rechaza duplicados con 400; el admin lo mapea a
        API_INVALID_PAYLOAD, y el endpoint lo re-traduce a 409
        EVO_INSTANCE_ALREADY_EXISTS para que la UI muestre el mensaje
        correcto."""
        from error_codes import ErrorCode
        from exceptions import APIError

        _patch_admin(
            mocker,
            create_side_effect=APIError(
                ErrorCode.API_INVALID_PAYLOAD,
                detail="Bad name (Evolution rejected)",
            ),
        )
        resp = await client.post(
            "/api/evolution/instances",
            json={"name": "bot_2"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "E-COM-005"

    @pytest.mark.asyncio
    async def test_nombre_invalido_regex_devuelve_400(self, mocker, client, auth_token):
        """La regex ^[A-Za-z0-9_-]+$ rechaza espacios y simbolos. La
        validacion via Pydantic dispara el validation_error_handler que
        devuelve 400 (convencion del proyecto, no 422)."""
        _patch_admin(mocker)  # admin no se invoca, falla antes
        resp = await client.post(
            "/api/evolution/instances",
            json={"name": "has space"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_nombre_vacio_devuelve_400(self, mocker, client, auth_token):
        _patch_admin(mocker)
        resp = await client.post(
            "/api/evolution/instances",
            json={"name": ""},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_nombre_demasiado_largo_devuelve_400(self, mocker, client, auth_token):
        _patch_admin(mocker)
        resp = await client.post(
            "/api/evolution/instances",
            json={"name": "x" * 65},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_crea_y_setea_webhook_atomico(
        self, mocker, client, auth_token, bot_url
    ):
        """Bug fix: al crear una instancia, el endpoint debe configurar
        el webhook hacia el bot. Sin esto, Evolution no le pasa los
        mensajes al bot y queda como 'huérfana' hasta que el admin
        pulse 'Activar' (que era el único path que lo hacía)."""
        from evolution_models import WebhookConfig
        from exceptions import APIError

        fake = _patch_admin(
            mocker, create_return=_make_instance("bot_2", "close")
        )
        resp = await client.post(
            "/api/evolution/instances",
            json={"name": "bot_2"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 201
        # create_instance fue llamado una vez con el nombre correcto.
        fake.create_instance.assert_awaited_once_with("bot_2")
        # set_webhook fue llamado una vez con un WebhookConfig cuya URL
        # no es vacia (sino el webhook queda apuntando a "" y el bot
        # nunca recibe nada — exactamente el bug que arreglamos).
        fake.set_webhook.assert_awaited_once()
        call_args = fake.set_webhook.await_args
        assert call_args.args[0] == "bot_2"
        cfg = call_args.args[1]
        assert isinstance(cfg, WebhookConfig)
        assert cfg.url, "Webhook URL no puede quedar vacia"
        # Por default usa MESSAGES_UPSERT, que es el unico evento que
        # el bot procesa hoy.
        assert "MESSAGES_UPSERT" in cfg.events

    @pytest.mark.asyncio
    async def test_si_set_webhook_falla_devuelve_warning_sin_romper(
        self, mocker, client, auth_token, bot_url
    ):
        """Si Evolution rechaza el set_webhook (red caida, 500, etc.),
        el create NO debe fallar: la instancia YA existe, el admin ya
        la ve en la lista, y revertirla seria peor que dejarla con un
        warning visible. La UI muestra el warning como banner no-bloqueante."""
        from error_codes import ErrorCode
        from exceptions import APIError

        fake = _patch_admin(
            mocker,
            create_return=_make_instance("bot_2", "close"),
            set_webhook_side_effect=APIError(
                ErrorCode.API_SERVER_ERROR,
                detail="Evolution 500",
            ),
        )
        resp = await client.post(
            "/api/evolution/instances",
            json={"name": "bot_2"},
            headers=_auth(auth_token),
        )
        # Igual 201: la instancia se creo, solo no se le pudo apuntar
        # el webhook.
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "bot_2"
        # El warning esta presente y menciona que el webhook no se configuro.
        assert "warning" in body
        assert "webhook" in body["warning"].lower()

    @pytest.mark.asyncio
    async def test_instancia_close_sin_vincular_devuelve_warning(
        self, mocker, client, auth_token, bot_url
    ):
        """Toda instancia nueva arranca en `close` (aun no escaneada).
        El endpoint debe avisarle al admin que tiene que escanear el QR
        para que empiecen a llegar mensajes — sino el operador asume
        que 'ya esta' y se come el silencio del bot."""
        _patch_admin(
            mocker, create_return=_make_instance("bot_2", "close")
        )
        resp = await client.post(
            "/api/evolution/instances",
            json={"name": "bot_2"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["connectionState"] == "close"
        # Warning presente con pista accionable (escanear QR / activar).
        assert "warning" in body
        warning_lower = body["warning"].lower()
        assert "qr" in warning_lower or "escan" in warning_lower or "activ" in warning_lower


# ---------------------------------------------------------------------------
# GET /api/evolution/instances/{name}/state
# ---------------------------------------------------------------------------

class TestGetState:
    @pytest.mark.asyncio
    async def test_devuelve_200_con_state(self, mocker, client, auth_token):
        from evolution_models import ConnectionState
        _patch_admin(mocker, state_return=ConnectionState.OPEN)
        resp = await client.get(
            "/api/evolution/instances/bot_2/state", headers=_auth(auth_token)
        )
        assert resp.status_code == 200
        assert resp.json() == {"state": "open"}


# ---------------------------------------------------------------------------
# POST /api/evolution/active
# ---------------------------------------------------------------------------

class TestDeleteInstance:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.delete("/api/evolution/instances/bot_2")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_happy_path_devuelve_204_y_llama_admin(
        self, mocker, client, auth_token
    ):
        """Si la instancia NO es la activa, el endpoint llama a
        `evolution_admin.delete_instance(name)` y devuelve 204 (no body).

        Importante: monkey-patcheamos `config_manager.cargar` para que
        el `cargar()` que el endpoint hace al inicio (defensa contra
        swaps del watcher) NO pise el valor que seteamos en memoria."""
        fake = _patch_admin(mocker)
        fake.delete_instance = AsyncMock(return_value=None)
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = "other_bot"
        resp = await client.delete(
            "/api/evolution/instances/bot_2", headers=_auth(auth_token)
        )
        assert resp.status_code == 204
        assert resp.content == b""
        fake.delete_instance.assert_awaited_once_with("bot_2")

    @pytest.mark.asyncio
    async def test_borrar_la_activa_devuelve_409_EVO_INSTANCE_ACTIVE(
        self, mocker, client, auth_token
    ):
        """Safety check: borrar la activa dejaria al bot sin outbound.
        El endpoint rechaza con 409 + `EVO_INSTANCE_ACTIVE` y NO toca
        Evolution (la llamada a `admin.delete_instance` no debe ocurrir)."""
        fake = _patch_admin(mocker)
        fake.delete_instance = AsyncMock(return_value=None)
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = "bot_2"
        resp = await client.delete(
            "/api/evolution/instances/bot_2", headers=_auth(auth_token)
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "E-COM-006"
        # Mensaje le da al operador la salida: "activá otra antes".
        assert "activ" in body["error"]["detail"].lower()
        fake.delete_instance.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_borrar_la_activa_via_env_var_devuelve_409(
        self, mocker, client, auth_token, monkeypatch
    ):
        """Si `config.active_instance_name` esta vacio en disco (caso
        comun: el operador NUNCA swapeo manualmente), el safety check
        tiene que caer al fallback `EVOLUTION_INSTANCE_NAME` de env.
        Si no, borrariamos la instancia que el bot esta usando y queda
        sin outbound."""
        fake = _patch_admin(mocker)
        fake.delete_instance = AsyncMock(return_value=None)
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = ""
        monkeypatch.setenv("EVOLUTION_INSTANCE_NAME", "rag_bot")
        resp = await client.delete(
            "/api/evolution/instances/rag_bot", headers=_auth(auth_token)
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "E-COM-006"
        fake.delete_instance.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_nombre_invalido_regex_devuelve_400(
        self, mocker, client, auth_token
    ):
        """El path param pasa por `_validate_instance_name` (que re-corre
        la regex). Sin auth ya filtra antes; con auth, la regex."""
        fake = _patch_admin(mocker)
        fake.delete_instance = AsyncMock(return_value=None)
        resp = await client.delete(
            "/api/evolution/instances/has%20space", headers=_auth(auth_token)
        )
        assert resp.status_code == 400
        fake.delete_instance.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_404_de_evolution_se_propaga_como_404(
        self, mocker, client, auth_token
    ):
        """Si Evolution no la tiene (404), `evolution_admin` mapea a
        `APIError(API_NOT_FOUND)`, y el error_handler devuelve 404."""
        from error_codes import ErrorCode
        from exceptions import APIError

        fake = _patch_admin(mocker)
        fake.delete_instance = AsyncMock(
            side_effect=APIError(
                ErrorCode.API_NOT_FOUND,
                detail="Instancia no encontrada (delete_instance(x))",
            )
        )
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = ""
        resp = await client.delete(
            "/api/evolution/instances/missing", headers=_auth(auth_token)
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "E-API-002"


class TestGetActiveInstance:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.get("/api/evolution/active")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_devuelve_200_con_nombre_activa(
        self, mocker, client, auth_token
    ):
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = "rag_bot"
        resp = await client.get(
            "/api/evolution/active", headers=_auth(auth_token)
        )
        assert resp.status_code == 200
        assert resp.json() == {"name": "rag_bot"}

    @pytest.mark.asyncio
    async def test_desactivada_no_cae_a_env_var(
        self, mocker, client, auth_token, monkeypatch
    ):
        """Si active_instance_name es "" (desactivado explicitamente),
        el endpoint NO debe caer a la env var. Caso contrario, desactivar
        una instancia no tendria efecto: el frontend seguiria viendo la
        activa via el fallback."""
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = ""
        monkeypatch.setenv("EVOLUTION_INSTANCE_NAME", "rag_bot")
        resp = await client.get(
            "/api/evolution/active", headers=_auth(auth_token)
        )
        assert resp.status_code == 200
        assert resp.json() == {"name": ""}

    @pytest.mark.asyncio
    async def test_falla_a_env_var_si_key_no_existe(
        self, mocker, client, auth_token, monkeypatch
    ):
        """Si active_instance_name no existe en config (nunca fue seteado),
        el endpoint usa la env var como fallback."""
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config.pop("active_instance_name", None)
        monkeypatch.setenv("EVOLUTION_INSTANCE_NAME", "rag_bot")
        resp = await client.get(
            "/api/evolution/active", headers=_auth(auth_token)
        )
        assert resp.status_code == 200
        assert resp.json() == {"name": "rag_bot"}

    @pytest.mark.asyncio
    async def test_sin_activa_devuelve_string_vacio(
        self, mocker, client, auth_token, monkeypatch
    ):
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = ""
        monkeypatch.delenv("EVOLUTION_INSTANCE_NAME", raising=False)
        resp = await client.get(
            "/api/evolution/active", headers=_auth(auth_token)
        )
        assert resp.status_code == 200
        assert resp.json() == {"name": ""}


class TestActivateInstance:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.post("/api/evolution/active", json={"name": "bot_2"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_happy_path_llama_bridge_y_devuelve_202(
        self, mocker, client, auth_token, monkeypatch
    ):
        """El endpoint re-construye admin+config por-request, llama
        instance_activation.set_active con BOT_URL/WEBHOOK_SECRET de env,
        y devuelve {status, active} en 202 Accepted (el write del config
        corre async en background, no se espera)."""
        from evolution_models import ConnectionState
        from instance_activation import set_active as real_set_active

        _patch_admin(mocker, state_return=ConnectionState.OPEN)
        monkeypatch.setenv("BOT_URL", "https://bot.example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "s3cr3t")

        # Capturamos los kwargs que el endpoint pasa al bridge.
        captured = {}
        async def fake_set_active(name, *, admin, config, webhook_url, webhook_secret):
            captured["name"] = name
            captured["admin"] = admin
            captured["config"] = config
            captured["webhook_url"] = webhook_url
            captured["webhook_secret"] = webhook_secret
        mocker.patch.object(
            importlib.import_module("instance_activation"),
            "set_active",
            new=fake_set_active,
        )

        resp = await client.post(
            "/api/evolution/active",
            json={"name": "bot_2"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 202
        assert resp.json() == {"status": "accepted", "active": "bot_2"}
        # El bridge recibio los parametros exactos del endpoint.
        assert captured["name"] == "bot_2"
        assert captured["webhook_url"] == "https://bot.example.com"
        assert captured["webhook_secret"] == "s3cr3t"
        # El admin mockeado llego al bridge (no se re-construyo).
        assert captured["admin"] is interface.evolution_admin
        # El config_manager llego al bridge.
        assert captured["config"] is interface.config_manager

    @pytest.mark.asyncio
    async def test_drift_caught_devuelve_409(self, mocker, client, auth_token, monkeypatch):
        """El bridge hace el re-verify de state; si no esta en 'open',
        raisea APIError(EVO_INSTANCE_NOT_LINKED) y el endpoint devuelve
        409 (mapeo del error_handler)."""
        from error_codes import ErrorCode
        from exceptions import APIError
        from evolution_models import ConnectionState

        _patch_admin(mocker, state_return=ConnectionState.CLOSE)
        monkeypatch.setenv("BOT_URL", "https://bot.example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "s3cr3t")

        async def fake_set_active(name, *, admin, config, webhook_url, webhook_secret):
            # Replicamos el raise del bridge real para que el endpoint
            # lo propague.
            raise APIError(
                ErrorCode.EVO_INSTANCE_NOT_LINKED,
                detail="La instancia 'bot_2' está en estado 'close' y no puede activarse",
            )
        mocker.patch.object(
            importlib.import_module("instance_activation"),
            "set_active",
            new=fake_set_active,
        )

        resp = await client.post(
            "/api/evolution/active",
            json={"name": "bot_2"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "E-COM-004"
        # El detail preserva la razon del bridge.
        assert "close" in body["error"]["detail"]

    @pytest.mark.asyncio
    async def test_nombre_invalido_regex_devuelve_400(self, mocker, client, auth_token):
        """El body del POST tambien pasa por Pydantic; un nombre con
        espacios falla la regex antes de tocar el bridge."""
        _patch_admin(mocker)
        resp = await client.post(
            "/api/evolution/active",
            json={"name": "invalid name!"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_happy_path_devuelve_202_accepted(
        self, mocker, client, auth_token, monkeypatch
    ):
        """El endpoint devuelve 202 Accepted (no 200) porque la escritura
        del config es async. El usuario recibe confirmacion inmediata de
        que la activacion se proceso, sin esperar el write a disco (que
        puede tardar 100s si WSL2 bind-mount tiene EBUSY)."""
        from evolution_models import ConnectionState
        from instance_activation import set_active as real_set_active

        _patch_admin(mocker, state_return=ConnectionState.OPEN)
        monkeypatch.setenv("BOT_URL", "https://bot.example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "s3cr3t")

        async def fake_set_active(name, *, admin, config, webhook_url, webhook_secret):
            return None
        mocker.patch.object(
            importlib.import_module("instance_activation"),
            "set_active",
            new=fake_set_active,
        )

        resp = await client.post(
            "/api/evolution/active",
            json={"name": "bot_2"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 202
        assert resp.json() == {"status": "accepted", "active": "bot_2"}


# ---------------------------------------------------------------------------
# POST /api/evolution/instances/{name}/deactivate
# ---------------------------------------------------------------------------

class TestDeactivateInstance:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.post("/api/evolution/instances/bot_1/deactivate")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_deactivate_instance_success(self, mocker, client, auth_token):
        """POST /api/evolution/instances/bot_1/deactivate devuelve 202
        con {status: accepted, deactivated: bot_1}. El write async del
        config corre en background (no se espera)."""
        fake = _patch_admin(mocker)
        fake.disable_webhook = AsyncMock(return_value=None)
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = ""
        resp = await client.post(
            "/api/evolution/instances/bot_1/deactivate",
            headers=_auth(auth_token),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body == {"status": "accepted", "deactivated": "bot_1"}
        fake.disable_webhook.assert_awaited_once_with("bot_1")

    @pytest.mark.asyncio
    async def test_deactivate_instance_not_found(self, mocker, client, auth_token):
        """Si Evolution no tiene la instancia, disable_webhook raisea
        APIError(API_NOT_FOUND) y el endpoint devuelve 404."""
        from error_codes import ErrorCode
        from exceptions import APIError

        fake = _patch_admin(mocker)
        fake.disable_webhook = AsyncMock(
            side_effect=APIError(
                ErrorCode.API_NOT_FOUND,
                detail="Instancia no encontrada",
            )
        )
        resp = await client.post(
            "/api/evolution/instances/missing/deactivate",
            headers=_auth(auth_token),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_deactivate_clears_active_instance(self, mocker, client, auth_token):
        """Si se desactiva la instancia ACTIVA, active_instance_name se
        limpia en config via set_active_instance_async (no sync) con ""."""
        fake = _patch_admin(mocker)
        fake.disable_webhook = AsyncMock(return_value=None)
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = "bot_1"
        # Mock set_active_instance_async para capturar la llamada.
        # Importante: NO setear el mock sobre set_active_instance (sync),
        # porque el bridge usa el async y el sync no se debe llamar.
        mock_async = AsyncMock()
        mock_sync = MagicMock()
        mocker.patch.object(
            interface.config_manager, "set_active_instance_async", mock_async
        )
        mocker.patch.object(
            interface.config_manager, "set_active_instance", mock_sync
        )
        resp = await client.post(
            "/api/evolution/instances/bot_1/deactivate",
            headers=_auth(auth_token),
        )
        assert resp.status_code == 202
        # Verificar que se limpio la activa via async (no sync)
        mock_async.assert_awaited_once_with("")
        mock_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_deactivate_does_not_clear_when_not_active(
        self, mocker, client, auth_token
    ):
        """Si se desactiva una instancia que NO es la activa, el config
        no se modifica (set_active_instance_async NO se llama)."""
        fake = _patch_admin(mocker)
        fake.disable_webhook = AsyncMock(return_value=None)
        mocker.patch.object(interface.config_manager, "cargar", lambda: None)
        interface.config_manager.config["active_instance_name"] = "other_bot"
        mock_async = AsyncMock()
        mock_sync = MagicMock()
        mocker.patch.object(
            interface.config_manager, "set_active_instance_async", mock_async
        )
        mocker.patch.object(
            interface.config_manager, "set_active_instance", mock_sync
        )
        resp = await client.post(
            "/api/evolution/instances/bot_1/deactivate",
            headers=_auth(auth_token),
        )
        assert resp.status_code == 202
        # Verificar que NO se toco el config
        mock_async.assert_not_called()
        mock_sync.assert_not_called()
        assert interface.config_manager.config["active_instance_name"] == "other_bot"
