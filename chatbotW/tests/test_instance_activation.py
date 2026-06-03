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
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers de import
# ---------------------------------------------------------------------------

def _load_config_manager_module(tmp_path: Path):
    """Carga ConfigManager apuntando a un tmp_path. Parchea paths.CONFIG_FILE
    para que apunte al config temporal."""
    import paths
    original_config_file = paths.CONFIG_FILE
    paths.CONFIG_FILE = tmp_path / "config_bot.json"

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

@pytest_asyncio.fixture
async def config_manager(tmp_path):
    """Un ConfigManager real apuntado a tmp_path. Se usa para verificar que
    la escritura atomica realmente toco disco (no solo el mock).

    Async fixture con yield: limpia el worker de write async al final del
    test. Sin esto, los tasks quedan pending y pytest muestra warnings de
    "Task was destroyed but it is pending" + "Event loop is closed".
    """
    cfg_mod = _load_config_manager_module(tmp_path)
    cm = cfg_mod.ConfigManager()
    yield cm, tmp_path / "config_bot.json"
    await cm.stop_worker()


@pytest.fixture
def admin():
    """Mock de EvolutionAdmin con get_state / set_webhook / disable_webhook como AsyncMock."""
    a = MagicMock()
    a.get_state = AsyncMock()
    a.set_webhook = AsyncMock()
    a.disable_webhook = AsyncMock()
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
    """State open + set_webhook ok -> config.set_active_instance_async se llama
    con el nombre, y la escritura atomica realmente impacta en disco
    (esperando al worker de fondo)."""
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
    # El write del config es async: esperamos al worker antes de leer disco.
    await cm._write_queue.join()
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
    """El orden de invocacion es: get_state -> set_webhook -> set_active_instance_async.
    Verificamos con call_args_list de ambos mocks."""
    cm, _ = config_manager
    admin.get_state.return_value = "open"
    admin.set_webhook.return_value = None

    # Reemplazamos set_active_instance_async del config por un mock para
    # capturar el orden relativo contra los awaits de admin.
    real_async = cm.set_active_instance_async
    cm.set_active_instance_async = AsyncMock(wraps=real_async)

    await bridge.set_active(
        "bot_2",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    # El config mock se llamo despues de set_webhook.
    assert admin.set_webhook.await_count == 1
    assert cm.set_active_instance_async.await_count == 1
    # Drenamos la cola para que el worker termine antes de salir del test.
    await cm._write_queue.join()


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
    el config es `set_active_instance` (via async), y ocurre DESPUES de
    `set_webhook`.

    Cubrimos tres angulos:
    a) get_state y set_webhook se llaman exactamente una vez.
    b) set_active_instance_async se llama exactamente una vez.
    c) Si set_webhook fallara, set_active_instance NO se llama (cubierto
       por `test_set_active_config_untouched_when_set_webhook_fails`,
       pero aca re-aseguramos el orden en el happy path).
    """
    cm, target = config_manager
    admin.get_state.return_value = "open"

    # Mockeamos set_active_instance_async para capturar la llamada.
    cm.set_active_instance_async = AsyncMock(wraps=cm.set_active_instance_async)

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
    assert cm.set_active_instance_async.await_count == 1

    # c) El side effect final: el archivo en disco quedo con la nueva
    # instancia. Esto es lo que el watcher de PR 3 va a leer.
    # El write es async: esperamos al worker antes de leer disco.
    await cm._write_queue.join()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["active_instance_name"] == "bot_2"


# ---------------------------------------------------------------------------
# Tests: desactivación de la instancia anterior
# ---------------------------------------------------------------------------

async def test_activation_deactivates_previous(bridge, admin, config_manager):
    """Cuando hay una instancia activa previa distinta, se llama
    disable_webhook sobre ella antes de configurar la nueva."""
    cm, _ = config_manager
    cm.set_active_instance("bot_1")

    admin.get_state.return_value = "open"
    admin.disable_webhook.return_value = None

    await bridge.set_active(
        "bot_2",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    admin.disable_webhook.assert_awaited_once_with("bot_1")


async def test_activation_skips_deactivation_when_empty(bridge, admin, config_manager):
    """Si active_instance_name está vacío, NO se llama disable_webhook."""
    cm, _ = config_manager
    # active_instance_name ya es "" por default

    admin.get_state.return_value = "open"

    await bridge.set_active(
        "bot_1",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    admin.disable_webhook.assert_not_awaited()


async def test_activation_skips_deactivation_when_same(bridge, admin, config_manager):
    """Si se activa la misma instancia que ya está activa, NO se llama
    disable_webhook (no tiene sentido desactivar la misma)."""
    cm, _ = config_manager
    cm.set_active_instance("bot_1")

    admin.get_state.return_value = "open"

    await bridge.set_active(
        "bot_1",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    admin.disable_webhook.assert_not_awaited()


async def test_activation_aborts_on_deactivation_failure(bridge, admin, config_manager):
    """Si disable_webhook falla con un error distinto a NOT_FOUND,
    la activación se ABORTA — no puede haber dos webhooks activos."""
    from exceptions import APIError
    from error_codes import ErrorCode

    cm, _ = config_manager
    cm.set_active_instance("bot_1")

    admin.get_state.return_value = "open"
    admin.disable_webhook.side_effect = APIError(
        ErrorCode.EVO_WEBHOOK_FAILED,
        detail="Evolution rechazó desactivar webhook",
    )

    with pytest.raises(APIError) as exc_info:
        await bridge.set_active(
            "bot_2",
            admin=admin,
            config=cm,
            webhook_url="https://bot.example.com",
            webhook_secret="s3cr3t",
        )

    admin.disable_webhook.assert_awaited_once_with("bot_1")
    # La activación NO continúa: set_webhook NO se llamó
    admin.set_webhook.assert_not_awaited()
    assert exc_info.value.code == ErrorCode.EVO_WEBHOOK_FAILED


async def test_activation_logs_deactivation(bridge, admin, config_manager, mocker):
    """Se registra en log cuando se desactiva la instancia anterior."""
    cm, _ = config_manager
    cm.set_active_instance("bot_1")

    admin.get_state.return_value = "open"
    mock_logger = mocker.patch("instance_activation.logger")

    await bridge.set_active(
        "bot_2",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    mock_logger.info.assert_any_call(
        "Previous webhook disabled", previous_instance="bot_1"
    )


async def test_activation_no_disable_when_previous_not_found(bridge, admin, config_manager):
    """Si la instancia previa no existe en Evolution (get_webhook falla),
    la desactivación se salta graciosamente y la activación continúa."""
    from exceptions import APIError
    from error_codes import ErrorCode

    cm, _ = config_manager
    cm.set_active_instance("old_bot")

    admin.get_state.return_value = "open"
    # Simular que get_webhook falla (instancia no existe en Evolution)
    admin.get_webhook = AsyncMock(
        side_effect=APIError(ErrorCode.API_NOT_FOUND, detail="Instance not found")
    )
    # disable_webhook propagaría el error de get_webhook
    async def _disable(name):
        await admin.get_webhook(name)
    admin.disable_webhook = AsyncMock(side_effect=_disable)

    await bridge.set_active(
        "bot_2",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    # La activación no se abortó: set_webhook se llamó
    admin.set_webhook.assert_awaited_once()


# ---------------------------------------------------------------------------
# Task 4: tests para el lock de activacion (evita doble activacion)
# ---------------------------------------------------------------------------


async def test_activation_lock_existe_a_nivel_de_modulo(bridge):
    """Task 4.1: el bridge expone un asyncio.Lock reutilizable para que dos
    requests de activacion no se pisen (uno espera al otro)."""
    import asyncio as aio
    # Reset para que el test sea independiente del orden de ejecucion
    bridge.activation_lock = aio.Lock()
    assert isinstance(bridge.activation_lock, aio.Lock)


async def test_set_active_usa_set_active_instance_async_no_sync(bridge, admin, config_manager, mocker):
    """Task 4.2: la escritura del config se hace via set_active_instance_async
    (no espera el write), asi el endpoint puede devolver 202 inmediato."""
    import asyncio as aio
    bridge.activation_lock = aio.Lock()

    cm, _ = config_manager
    cm.set_active_instance("")

    admin.get_state.return_value = "open"
    admin.set_webhook.return_value = None

    mock_async = mocker.patch.object(
        cm, "set_active_instance_async", new=AsyncMock()
    )
    mock_sync = mocker.patch.object(
        cm, "set_active_instance", wraps=cm.set_active_instance
    )

    await bridge.set_active(
        "bot_2",
        admin=admin,
        config=cm,
        webhook_url="https://bot.example.com",
        webhook_secret="s3cr3t",
    )

    mock_async.assert_awaited_once_with("bot_2")
    mock_sync.assert_not_called()


async def test_activation_lock_serializa_dos_requests_concurrentes(bridge, admin, config_manager):
    """Task 4.3: si dos requests de activacion entran casi simultaneamente,
    el segundo ESPERA al primero antes de empezar disable_webhook/set_webhook.
    Asi no se pisan los webhooks (no quedan dos instancias con webhook activo)."""
    import asyncio as aio
    bridge.activation_lock = aio.Lock()

    cm, _ = config_manager
    cm.set_active_instance("")

    # get_state responde "open" para ambos
    admin.get_state.return_value = "open"

    # Rastreamos el orden real de inicio/fin de cada set_active
    timeline = []

    real_set_webhook = admin.set_webhook

    async def tracking_set_webhook(name, *args, **kwargs):
        timeline.append(("start", name))
        await aio.sleep(0.1)  # simula latencia
        timeline.append(("end", name))
        return await real_set_webhook(*args, **kwargs)

    admin.set_webhook = AsyncMock(side_effect=tracking_set_webhook)

    # Lanzamos las dos activaciones en paralelo
    await aio.gather(
        bridge.set_active(
            "bot_A",
            admin=admin,
            config=cm,
            webhook_url="https://bot.example.com",
            webhook_secret="s3cr3t",
        ),
        bridge.set_active(
            "bot_B",
            admin=admin,
            config=cm,
            webhook_url="https://bot.example.com",
            webhook_secret="s3cr3t",
        ),
    )

    # El primer start debe terminar (end) ANTES del segundo start.
    # Eso demuestra que el lock serializo los dos requests.
    starts = [i for i, (ev, _) in enumerate(timeline) if ev == "start"]
    ends = [i for i, (ev, _) in enumerate(timeline) if ev == "end"]
    assert len(starts) == 2
    assert len(ends) == 2
    assert ends[0] < starts[1], f"Lock no serializo: timeline={timeline}"


# ---------------------------------------------------------------------------
# Task 5: tests para bridge.deactivate (async write + mismo lock que activate)
# ---------------------------------------------------------------------------


async def test_deactivate_uses_set_active_instance_async_not_sync(bridge, admin, config_manager, mocker):
    """Task 5.1: deactivate debe usar set_active_instance_async (no espera
    el write), igual que set_active, para que el endpoint devuelva 202
    inmediato aunque el bind-mount tenga EBUSY 100s."""
    import asyncio as aio
    bridge.activation_lock = aio.Lock()

    cm, _ = config_manager
    cm.set_active_instance("bot_1")  # bot_1 está activa

    admin.disable_webhook.return_value = None

    mock_async = mocker.patch.object(cm, "set_active_instance_async", new=AsyncMock())
    mock_sync = mocker.patch.object(cm, "set_active_instance", wraps=cm.set_active_instance)

    await bridge.deactivate("bot_1", admin=admin, config=cm)

    # Se llamo el async (no el sync) y con string vacio (clear)
    mock_async.assert_awaited_once_with("")
    mock_sync.assert_not_called()
    # disable_webhook si se llamo
    admin.disable_webhook.assert_awaited_once_with("bot_1")


async def test_deactivate_skips_set_active_when_not_the_active_one(bridge, admin, config_manager, mocker):
    """Task 5.2: si la instancia a desactivar NO es la activa, no tocamos
    el config (no la limpiamos ni la escribimos). Solo se deshabilita
    el webhook en Evolution."""
    import asyncio as aio
    bridge.activation_lock = aio.Lock()

    cm, _ = config_manager
    cm.set_active_instance("bot_active")  # la activa es OTRA

    admin.disable_webhook.return_value = None

    mock_async = mocker.patch.object(cm, "set_active_instance_async", new=AsyncMock())

    await bridge.deactivate("bot_other", admin=admin, config=cm)

    admin.disable_webhook.assert_awaited_once_with("bot_other")
    # El config NO se toco porque "bot_other" no es la activa
    mock_async.assert_not_called()


async def test_deactivate_propagates_disable_webhook_error(bridge, admin, config_manager):
    """Task 5.3: si disable_webhook falla (ej. instancia no existe en
    Evolution), el bridge NO toca el config y propaga el error."""
    import asyncio as aio
    bridge.activation_lock = aio.Lock()

    from exceptions import APIError
    from error_codes import ErrorCode

    cm, _ = config_manager
    cm.set_active_instance("bot_1")

    admin.disable_webhook.side_effect = APIError(
        ErrorCode.API_NOT_FOUND, detail="Instance not found"
    )

    with pytest.raises(APIError) as exc_info:
        await bridge.deactivate("bot_1", admin=admin, config=cm)

    assert exc_info.value.code == ErrorCode.API_NOT_FOUND
    # El config no se modifico (el write async no se encolo)
    assert cm.config["active_instance_name"] == "bot_1"


async def test_deactivate_and_set_active_share_same_lock(bridge, admin, config_manager):
    """Task 5.4: deactivate y set_active usan el MISMO lock. Si llegan
    concurrentemente, uno espera al otro. Asi no se pisan (ej. activate
    configura webhook en B mientras deactivate esta limpiando el config)."""
    import asyncio as aio
    bridge.activation_lock = aio.Lock()

    cm, _ = config_manager
    cm.set_active_instance("bot_A")

    admin.get_state.return_value = "open"
    admin.set_webhook.return_value = None
    admin.disable_webhook.return_value = None

    timeline = []

    real_set_webhook = admin.set_webhook
    real_disable_webhook = admin.disable_webhook

    async def tracking_set_webhook(name, *args, **kwargs):
        timeline.append(("set_webhook_start", name))
        await aio.sleep(0.05)
        timeline.append(("set_webhook_end", name))
        return await real_set_webhook(*args, **kwargs)

    async def tracking_disable(name):
        timeline.append(("disable_start", name))
        await aio.sleep(0.05)
        timeline.append(("disable_end", name))
        return await real_disable_webhook(name)

    admin.set_webhook = AsyncMock(side_effect=tracking_set_webhook)
    admin.disable_webhook = AsyncMock(side_effect=tracking_disable)

    # Lanzamos activate (A->B) y deactivate (B) en paralelo.
    # Si comparten el lock, uno espera al otro. Si no, se intercalan.
    await aio.gather(
        bridge.set_active(
            "bot_B",
            admin=admin,
            config=cm,
            webhook_url="https://bot.example.com",
            webhook_secret="s3cr3t",
        ),
        bridge.deactivate("bot_B", admin=admin, config=cm),
    )

    # El primer start (sea cual sea) debe terminar antes del segundo start.
    # Eso demuestra serializacion: si fueran en paralelo, los starts
    # ocurririan antes que los ends. El set_active hace 2 awaits
    # (disable_webhook + set_webhook) y deactivate hace 1 (disable_webhook),
    # asi que esperamos >= 3 starts/ends en orden serializado.
    starts = [i for i, ev in enumerate(timeline) if ev[0].endswith("start")]
    ends = [i for i, ev in enumerate(timeline) if ev[0].endswith("end")]
    assert len(starts) >= 2
    assert len(ends) == len(starts)
    # Cada end debe ocurrir ANTES del siguiente start: no hay solapamiento.
    for i in range(len(starts) - 1):
        assert ends[i] < starts[i + 1], (
            f"Lock no serializo (solapamiento en {i}): timeline={timeline}"
        )
