"""Unit tests for the CLI entrypoint (`python -m src <subcommand>`).

Strategy: mockeamos `EvolutionAdmin` (el import dentro de `src.__main__`)
para que cada test controle exactamente lo que devuelve. Capturamos
stdout/stderr con `capfd` y asserteamos exit code + JSON shape +
separacion stderr.
"""

import importlib
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

# Cargamos el modulo via importlib para que su nombre estable sea
# `src.__main__` (asi `mocker.patch` lo encuentra estable).
main_mod = importlib.import_module("src.__main__")


def _patch_admin(mocker, *, list_return=None, create_return=None,
                 qr_return=None, state_return=None, set_webhook_side=None):
    """Reemplaza `src.__main__.EvolutionAdmin` por un mock controlable.

    Devuelve el mock para que el test inspeccion el call_args si quiere.
    """
    fake = MagicMock()
    fake.list_instances = AsyncMock(return_value=list_return if list_return is not None else [])
    fake.create_instance = AsyncMock(return_value=create_return)
    fake.get_qr = AsyncMock(return_value=qr_return)
    fake.get_state = AsyncMock(return_value=state_return)
    fake.set_webhook = AsyncMock(side_effect=set_webhook_side)
    mocker.patch.object(main_mod, "EvolutionAdmin", return_value=fake)
    return fake


def _make_instance(name, state):
    """Helper rapido: contruye un InstanceInfo minimo sin HTTP."""
    from evolution_models import ConnectionState, InstanceInfo
    return InstanceInfo.model_validate({"name": name, "connectionState": state})


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    """Todos los subcomandos (excepto set-active) leen EVOLUTION_API_KEY."""
    monkeypatch.setenv("EVOLUTION_API_KEY", "test-key")
    monkeypatch.setenv("EVOLUTION_API_URL", "https://evo.test")


class TestList:
    def test_list_emits_json_to_stdout_and_exits_0(self, mocker, capfd):
        _patch_admin(mocker, list_return=[
            _make_instance("a", "open"),
            _make_instance("b", "close"),
        ])
        code = main_mod.main(["list"])
        out, err = capfd.readouterr()
        assert code == 0
        assert err == ""  # nada a stderr en el happy path
        data = json.loads(out.strip())
        assert len(data) == 2
        assert data[0]["name"] == "a"
        assert data[0]["connectionState"] == "open"
        assert data[1]["connectionState"] == "close"


class TestCreate:
    def test_create_emits_name_and_state(self, mocker, capfd):
        _patch_admin(mocker, create_return=_make_instance("bot_1", "close"))
        code = main_mod.main(["create", "--name", "bot_1"])
        out, err = capfd.readouterr()
        assert code == 0
        assert err == ""
        data = json.loads(out.strip())
        assert data["name"] == "bot_1"
        assert data["connectionState"] == "close"


class TestQr:
    def test_qr_emits_base64_and_state(self, mocker, capfd):
        from evolution_models import ConnectionState, QRPayload
        _patch_admin(mocker, qr_return=QRPayload(
            base64="AAAA", instance="bot_1", state=ConnectionState.CLOSE
        ))
        code = main_mod.main(["qr", "--name", "bot_1"])
        out, err = capfd.readouterr()
        assert code == 0
        data = json.loads(out.strip())
        assert data == {"base64": "AAAA", "state": "close"}


class TestState:
    def test_state_emits_state_field(self, mocker, capfd):
        from evolution_models import ConnectionState
        _patch_admin(mocker, state_return=ConnectionState.OPEN)
        code = main_mod.main(["state", "--name", "bot_1"])
        out, err = capfd.readouterr()
        assert code == 0
        data = json.loads(out.strip())
        assert data == {"state": "open"}


class TestSetWebhook:
    def test_set_webhook_emits_ok_and_passes_secret_header(self, mocker, capfd):
        fake = _patch_admin(mocker)
        code = main_mod.main([
            "set-webhook", "--name", "bot_1",
            "--url", "https://bot.example.com",
            "--secret", "s3cr3t",
        ])
        out, err = capfd.readouterr()
        assert code == 0
        data = json.loads(out.strip())
        assert data == {"status": "ok"}
        # Inspecciona que set_webhook recibio el WebhookConfig con el secret.
        fake.set_webhook.assert_awaited_once()
        name_arg, config_arg = fake.set_webhook.call_args.args
        assert name_arg == "bot_1"
        assert config_arg.url == "https://bot.example.com"
        assert config_arg.headers == {"X-Webhook-Secret": "s3cr3t"}


class TestSetActive:
    def test_set_active_succeeds_with_mocked_instance_activation(
        self, mocker, monkeypatch, capfd
    ):
        """PR 2: instance_activation ya esta implementado. El CLI lo invoca
        con (name, admin, config, webhook_url, webhook_secret) leyendo
        BOT_URL y WEBHOOK_SECRET del entorno, y emite `{status, active}`."""
        from unittest.mock import AsyncMock
        import instance_activation

        captured = {}

        async def fake_set_active(name, *, admin, config, webhook_url, webhook_secret):
            captured["name"] = name
            captured["admin"] = admin
            captured["config"] = config
            captured["webhook_url"] = webhook_url
            captured["webhook_secret"] = webhook_secret

        mocker.patch.object(instance_activation, "set_active", new=fake_set_active)

        # BOT_URL y WEBHOOK_SECRET son las dos env vars que el CLI pasa
        # al bridge. Si el admin no las setea en `.env` antes de invocar
        # `set-active`, el bot no recibe webhooks firmados.
        monkeypatch.setenv("BOT_URL", "https://bot.example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "topsecret")

        code = main_mod.main(["set-active", "--name", "bot_2"])
        out, err = capfd.readouterr()
        assert code == 0
        assert err == ""  # happy path: nada a stderr
        data = json.loads(out.strip())
        assert data == {"status": "ok", "active": "bot_2"}

        # El bridge recibio los parametros exactos del CLI.
        assert captured["name"] == "bot_2"
        assert captured["webhook_url"] == "https://bot.example.com"
        assert captured["webhook_secret"] == "topsecret"
        # El admin se construyo desde EVOLUTION_API_URL/_KEY (ver fixture).
        assert captured["admin"] is not None

    def test_set_active_exits_3_when_instance_activation_raises_config_error(
        self, mocker, monkeypatch, capfd
    ):
        """Si el bridge propaga ConfigError (ej. escritura atomica del
        config falla), el CLI traduce a exit 3 sin filtrar el detalle
        crudo al stdout."""
        from error_codes import ErrorCode
        from exceptions import ConfigError
        import instance_activation

        async def fake_set_active(name, *, admin, config, webhook_url, webhook_secret):
            raise ConfigError(ErrorCode.CFG_WRITE_FAILED, detail="disk full simulated")

        mocker.patch.object(instance_activation, "set_active", new=fake_set_active)
        monkeypatch.setenv("BOT_URL", "https://bot.example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "topsecret")

        code = main_mod.main(["set-active", "--name", "bot_2"])
        out, err = capfd.readouterr()
        assert code == 3
        assert out == ""  # stdout limpio, todo a stderr
        assert "disk full simulated" in err

    def test_set_active_exits_2_when_instance_state_is_not_open(
        self, mocker, monkeypatch, capfd
    ):
        """Si el bridge propaga APIError(EVO_INSTANCE_NOT_LINKED) (drift
        detectado al activar), el CLI traduce a exit 2 (precondicion)."""
        from error_codes import ErrorCode
        from exceptions import APIError
        import instance_activation

        async def fake_set_active(name, *, admin, config, webhook_url, webhook_secret):
            raise APIError(
                ErrorCode.EVO_INSTANCE_NOT_LINKED,
                detail="La instancia 'bot_2' está en estado 'connecting' y no puede activarse",
            )

        mocker.patch.object(instance_activation, "set_active", new=fake_set_active)
        monkeypatch.setenv("BOT_URL", "https://bot.example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "topsecret")

        code = main_mod.main(["set-active", "--name", "bot_2"])
        out, err = capfd.readouterr()
        assert code == 2
        assert out == ""
        assert "connecting" in err
