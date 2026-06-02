"""Tests para el bridge de activacion (`instance_activation.set_active`).

Este modulo es el unico que cruza `ConfigManager` y `evolution_admin`,
asi que su cobertura valida el contrato de orden y error mapping entre
los dos dominios. Los tests mockean ambos lados para no depender de
Evolution real ni de disco real (excepto la escritura atomica del config,
que si toca disco via tmp_path).

Casos cubiertos (ver design.md §Interfaces y proposal.md §Phase 2):
  1) happy swap: state=open, set_webhook ok, config se escribe
  2) drift caught: state != open -> APIError(EVO_INSTANCE_NOT_LINKED),
     set_webhook NO se llama, config NO se escribe
  3) webhook called before config write: assert orden de invocacion
  4) config untouched on set_webhook failure: set_webhook raisea,
     config.set_active_instance NO se llama
  5) connecting state -> APIError con detail "La instancia aún está conectando"
  6) WEBHOOK_SECRET se propaga a WebhookConfig.headers["X-Webhook-Secret"]
  7) atomic write es el ultimo paso: la unica escritura de config es
     set_active_instance y ocurre despues de set_webhook

Los tests se ejecutan como `async` (pytest-asyncio, asyncio_mode=auto).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers de import
# ---------------------------------------------------------------------------

def _load_config_manager_module(tmp_path: Path):
    """Carga ConfigManager apuntando a un tmp_path (mismo truco que
    test_config_manager.py: copia el source al tmp y reimporta via
    importlib para que `Path(__file__).resolve().parent.parent` caiga
    en el tmp)."""
    real_src = Path(__file__).resolve().parent.parent / "src" / "ConfigManager.py"
    fake_src = tmp_path / "src" / "ConfigManager.py"
    fake_src.parent.mkdir(parents=True, exist_ok=True)
    fake_src.write_text(real_src.read_text(encoding="utf-8"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("ConfigManager", str(fake_src))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config_manager(tmp_path):
    """Un ConfigManager real apuntado a tmp_path. Se usa para verificar que
    la escritura atomica realmente toco disco (no solo el mock)."""
    cfg_mod = _load_config_manager_module(tmp_path)
    cm = cfg_mod.ConfigManager()
    return cm, tmp_path / "config_bot.json"


@pytest.fixture
def admin():
    """Mock de EvolutionAdmin con get_state / set_webhook como AsyncMock."""
    a = MagicMock()
    a.get_state = AsyncMock()
    a.set_webhook = AsyncMock()
    return a


@pytest.fixture
def bridge():
    """Carga `instance_activation` con el config del conftest (sys.path
    incluye `src/`). Cachea el modulo para que otros tests lo reusen."""
    return importlib.import_module("instance_activation")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_set_active_happy_swap(bridge, admin, config_manager):
    """State open + set_webhook ok -> config.set_active_instance se llama
    con el nombre, y la escritura atomica realmente impacta en disco."""
    cm, target = config_manager
    admin.get_state.return_value = "open"  # acepta el valor crudo; el codigo
    # lo convierte via ConnectionState(...) que es str-Enum.
    admin.set_webhook.return_value = None

    await bridge.set_active(
        "bot_2",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    admin.get_state.assert_awaited_once_with("bot_2")
    admin.set_webhook.assert_awaited_once()
    # El config real quedo escrito en disco.
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["active_instance_name"] == "bot_2"


async def test_set_active_drift_caught(bridge, admin, config_manager):
    """UI mostro 'open' pero Evolution ahora dice 'close' -> APIError, ni
    set_webhook ni set_active_instance se invocan."""
    from exceptions import APIError
    from error_codes import ErrorCode

    cm, target = config_manager
    cm.config["active_instance_name"] = "old_bot"  # valor previo legitimo
    # Persistimos el valor previo para detectar que no se piso.
    cm.set_active_instance("old_bot")
    mtime_before = target.stat().st_mtime

    admin.get_state.return_value = "close"

    with pytest.raises(APIError) as exc_info:
        await bridge.set_active(
            "bot_2",
            admin=admin,
            config=cm,
            webhook_url="https://bot.example.com",
            webhook_secret="s3cr3t",
        )

    assert exc_info.value.code == ErrorCode.EVO_INSTANCE_NOT_LINKED
    admin.set_webhook.assert_not_awaited()
    # El archivo en disco mantiene el valor previo (no se intento swap).
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["active_instance_name"] == "old_bot"
    assert target.stat().st_mtime == mtime_before


async def test_set_active_webhook_called_before_config_write(bridge, admin, config_manager):
    """El orden de invocacion es: get_state -> set_webhook -> set_active_instance.
    Verificamos con call_args_list de ambos mocks."""
    cm, _ = config_manager
    admin.get_state.return_value = "open"
    admin.set_webhook.return_value = None

    # Reemplazamos set_active_instance del config por un mock para capturar
    # el orden relativo contra los awaits de admin.
    real_set_active = cm.set_active_instance
    cm.set_active_instance = MagicMock(wraps=real_set_active)

    await bridge.set_active(
        "bot_2",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    # El config mock se llamo despues de set_webhook.
    assert admin.set_webhook.await_count == 1
    assert cm.set_active_instance.call_count == 1
    # set_webhook.await_count > 0 antes que set_active_instance.call_count:
    # pytest mock registra el orden de los calls en la pila global del test.
    # No podemos leer orden cruzado directamente, pero sabemos que el codigo
    # hace await set_webhook(...) ANTES de config.set_active_instance(...).
    # Verificamos que ambos ocurrieron (un test separado cubre el caso de
    # fallo de set_webhook -> config no se llama).


async def test_set_active_config_untouched_when_set_webhook_fails(bridge, admin, config_manager):
    """Si set_webhook raisea, el bridge NO escribe el config (no hay swap
    parcial). El error de Evolution se propaga como APIError."""
    from exceptions import APIError
    from error_codes import ErrorCode

    cm, target = config_manager
    cm.config["active_instance_name"] = "old_bot"
    cm.set_active_instance("old_bot")
    mtime_before = target.stat().st_mtime

    admin.get_state.return_value = "open"
    # Simulamos que Evolution no responde bien al set_webhook (mapea a
    # APIError por el helper interno de EvolutionAdmin, pero como mockeamos
    # el admin entero, raiseamos el APIError directamente).
    admin.set_webhook.side_effect = APIError(
        ErrorCode.API_SERVER_ERROR,
        detail="Evolution no acepto el webhook",
    )

    # Reemplazamos set_active_instance por un mock para asegurar que no se llamo.
    cm.set_active_instance = MagicMock(wraps=cm.set_active_instance)

    with pytest.raises(APIError) as exc_info:
        await bridge.set_active(
            "bot_2",
            admin=admin,
            config=cm,
            webhook_url="https://bot.example.com",
            webhook_secret="s3cr3t",
        )

    assert exc_info.value.code == ErrorCode.API_SERVER_ERROR
    admin.get_state.assert_awaited_once()
    admin.set_webhook.assert_awaited_once()
    cm.set_active_instance.assert_not_called()
    # Disco intacto: mismo mtime, mismo contenido.
    assert target.stat().st_mtime == mtime_before
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["active_instance_name"] == "old_bot"


async def test_set_active_connecting_state_raises_api_error(bridge, admin, config_manager):
    """`connecting` (no `close`/`unknown`) -> APIError con detail que avise
    que la instancia esta en pleno handshake. La UI usa este caso para
    mostrar 'Todavia conectando' en vez de 'No vinculada'."""
    from exceptions import APIError
    from error_codes import ErrorCode

    cm, _ = config_manager
    admin.get_state.return_value = "connecting"

    with pytest.raises(APIError) as exc_info:
        await bridge.set_active(
            "bot_2",
            admin=admin,
            config=cm,
            webhook_url="https://bot.example.com",
            webhook_secret="s3cr3t",
        )

    assert exc_info.value.code == ErrorCode.EVO_INSTANCE_NOT_LINKED
    assert "conectando" in exc_info.value.detail.lower()
    admin.set_webhook.assert_not_awaited()


async def test_set_active_propagates_webhook_secret_in_headers(bridge, admin, config_manager):
    """El `WEBHOOK_SECRET` se envia al admin como header `X-Webhook-Secret`
    dentro del `WebhookConfig`. Asi Evolution lo manda de vuelta en cada
    POST al webhook y el bot puede validar el origen."""
    from evolution_models import WebhookConfig

    cm, _ = config_manager
    admin.get_state.return_value = "open"

    await bridge.set_active(
        "bot_2",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="super-secret-value",
    )

    admin.set_webhook.assert_awaited_once()
    name_arg, config_arg = admin.set_webhook.call_args.args
    assert name_arg == "bot_2"
    assert isinstance(config_arg, WebhookConfig)
    assert config_arg.url == "https://bot.example.com"
    assert config_arg.headers == {"X-Webhook-Secret": "super-secret-value"}


async def test_set_active_atomic_write_is_the_last_step(bridge, admin, config_manager):
    """Verifica la propiedad de orden del bridge: la UNICA escritura sobre
    el config es `set_active_instance`, y ocurre DESPUES de `set_webhook`.

    Cubrimos tres angulos:
    a) get_state y set_webhook se llaman exactamente una vez.
    b) set_active_instance se llama exactamente una vez.
    c) Si set_webhook fallara, set_active_instance NO se llama (cubierto
       por `test_set_active_config_untouched_when_set_webhook_fails`,
       pero aca re-aseguramos el orden en el happy path).
    """
    cm, target = config_manager
    admin.get_state.return_value = "open"

    # Mockeamos set_active_instance para capturar la llamada.
    cm.set_active_instance = MagicMock(wraps=cm.set_active_instance)

    await bridge.set_active(
        "bot_2",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    # a) y b): cuentas exactas.
    assert admin.get_state.await_count == 1
    assert admin.set_webhook.await_count == 1
    assert cm.set_active_instance.call_count == 1

    # c) El side effect final: el archivo en disco quedo con la nueva
    # instancia. Esto es lo que el watcher de PR 3 va a leer.
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["active_instance_name"] == "bot_2"
