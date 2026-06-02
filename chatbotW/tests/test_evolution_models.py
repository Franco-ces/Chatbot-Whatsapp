"""Unit tests for `evolution_models` (pure Pydantic)."""

import pytest

from evolution_models import (
    ConnectionState,
    InstanceInfo,
    QRPayload,
    WebhookConfig,
)


class TestConnectionState:
    def test_has_all_four_states(self):
        """Los 4 estados del enum deben existir y tener los valores que
        Evolution devuelve literalmente en su API."""
        assert ConnectionState.OPEN.value == "open"
        assert ConnectionState.CLOSE.value == "close"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.UNKNOWN.value == "unknown"
        # Y nada mas: el enum es cerrado a estos 4.
        assert set(ConnectionState) == {
            ConnectionState.OPEN,
            ConnectionState.CLOSE,
            ConnectionState.CONNECTING,
            ConnectionState.UNKNOWN,
        }

    def test_values_are_strings(self):
        """`str, Enum` -> los miembros son str comparables."""
        for state in ConnectionState:
            assert isinstance(state, str)
            # Sirve para usar el valor directo como string en logs, JSON, etc.
            assert state == state.value


class TestInstanceInfo:
    def test_parses_with_camel_case_aliases(self):
        """Evolution devuelve camelCase; el modelo debe aceptarlo sin tocar."""
        raw = {
            "name": "bot_1",
            "ownerJid": "54911@s.whatsapp.net",
            "connectionState": "open",
            "serverUrl": "https://srv.example",
            "apiKey": "abc",
            "integration": "WHATSAPP-BAILEYS",
            "profilePicUrl": "https://pic",
        }
        info = InstanceInfo.model_validate(raw)
        assert info.name == "bot_1"
        assert info.owner_jid == "54911@s.whatsapp.net"
        assert info.connection_state == ConnectionState.OPEN
        assert info.server_url == "https://srv.example"
        assert info.api_key == "abc"
        assert info.integration == "WHATSAPP-BAILEYS"
        assert info.profile_pic_url == "https://pic"

    def test_optional_fields_default_to_none(self):
        """Sin ownerJid, serverUrl, etc. -> todos en None (excepto los requeridos)."""
        info = InstanceInfo.model_validate(
            {"name": "bot_2", "connectionState": "close"}
        )
        assert info.owner_jid is None
        assert info.server_url is None
        assert info.api_key is None
        assert info.integration is None
        assert info.profile_pic_url is None

    def test_also_accepts_snake_case_input(self):
        """`populate_by_name=True` permite construir con nombres Python
        (util para tests, fixtures, CLI)."""
        info = InstanceInfo.model_validate(
            {"name": "bot_3", "connection_state": "connecting", "owner_jid": "x"}
        )
        assert info.connection_state == ConnectionState.CONNECTING
        assert info.owner_jid == "x"


class TestWebhookConfig:
    def test_default_events_is_messsages_upsert(self):
        """Sin `events` -> ['MESSAGES_UPSERT'], el unico evento que el bot procesa."""
        cfg = WebhookConfig(url="https://bot.example.com")
        assert cfg.events == ["MESSAGES_UPSERT"]

    def test_default_headers_is_empty_dict(self):
        """Sin `headers` -> {} (no se manda X-Webhook-Secret hasta que el operador lo configure)."""
        cfg = WebhookConfig(url="https://bot.example.com")
        assert cfg.headers == {}

    def test_default_factory_not_shared_between_instances(self):
        """El default_factory debe crear un dict/list NUEVO por instancia;
        si compartiera referencia, mutar uno mutaria todos."""
        a = WebhookConfig(url="https://a")
        b = WebhookConfig(url="https://b")
        a.headers["X-Test"] = "leak"
        a.events.append("EXTRA")
        assert b.headers == {}
        assert b.events == ["MESSAGES_UPSERT"]
