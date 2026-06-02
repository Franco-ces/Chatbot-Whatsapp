"""Tests para InstanceWatcher (PR 3 — bot decoupling).

Cubre:
1. Picks up existing name on reload
2. mtime change picked up within budget (spec: <=2s)
3. Atomic swap on overwrite
4. Unchanged mtime is a no-op
5. Tmp file (atomic write target) is ignored
6. Jitter keeps sleep within range
7. Lifecycle: start/stop idempotent
8. Thread-safe reload_now under concurrent access
"""
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from instance_watcher import InstanceWatcher


@pytest.fixture
def config_path(tmp_path):
    """Config file sin `active_instance_name` (caso pre-activacion)."""
    p = tmp_path / "config_bot.json"
    p.write_text(json.dumps({"email": "test@example.com"}))
    return p


@pytest.fixture
def fast_watcher(config_path):
    """Watcher con poll/jitter agresivos para tests de timing."""
    return InstanceWatcher(config_path, poll_seconds=0.05, jitter_seconds=0.01)


class TestReloadNow:
    """Lectura inicial + swap atomic sin polling."""

    def test_picks_up_existing_name_on_reload(self, config_path):
        """Si el config tiene `active_instance_name`, reload_now lo levanta.

        Caso pre-PR-2 vs post-PR-2: el campo es opcional (default ''),
        pero si esta presente el watcher lo respeta.
        """
        config_path.write_text(json.dumps({"active_instance_name": "bot_1"}))
        watcher = InstanceWatcher(config_path)
        assert watcher.get_active_name() == ""
        watcher.reload_now()
        assert watcher.get_active_name() == "bot_1"

    def test_atomic_swap_on_overwrite(self, config_path):
        """Sobrescribir el config con un nombre nuevo: reload lo refleja.

        Reproduce el flujo del spec scenario 'Hot-Swap picks up change':
        el admin activa bot_2, el bot (en su proximo tick) ve el swap.
        """
        config_path.write_text(json.dumps({"active_instance_name": "bot_1"}))
        watcher = InstanceWatcher(config_path)
        watcher.reload_now()
        assert watcher.get_active_name() == "bot_1"
        # Simulamos la escritura atomica de PR 2: tmp + os.replace.
        # El mtime avanza (FS resuelve >=10ms en la mayoria), el
        # siguiente reload lo detecta.
        time.sleep(0.01)  # ensure mtime advances
        tmp = config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"active_instance_name": "bot_2"}))
        tmp.replace(config_path)
        watcher.reload_now()
        assert watcher.get_active_name() == "bot_2"

    def test_unchanged_mtime_is_noop(self, config_path, fast_watcher):
        """Dos reloads consecutivos sobre el mismo archivo: estado estable.

        El segundo reload detecta mtime igual y sale sin re-leer
        el JSON. Lo verificamos indirectamente: el nombre activo no
        cambia, no se loggea, no hay excepcion.
        """
        config_path.write_text(json.dumps({"active_instance_name": "bot_1"}))
        fast_watcher.reload_now()
        assert fast_watcher.get_active_name() == "bot_1"
        fast_watcher.reload_now()
        assert fast_watcher.get_active_name() == "bot_1"

    def test_ignores_tmp_file(self, config_path):
        """Escribir SOLO al .tmp (durante el atomic-write de PR 2) no triggea reload.

        El watcher hace `os.stat(config_path).st_mtime` — el archivo
        principal, no el .tmp. Mientras el `os.replace` no haya
        ocurrido, el mtime del principal no avanzo y el watcher no
        re-lee. Esto es critico: si leyera el .tmp podria ver un
        JSON a medio escribir y corromper `_active_name`.
        """
        config_path.write_text(json.dumps({"active_instance_name": "bot_1"}))
        watcher = InstanceWatcher(config_path)
        watcher.reload_now()
        assert watcher.get_active_name() == "bot_1"
        # Escribimos al tmp SIN hacer replace. Esto simula el estado
        # intermedio de `set_active_instance` entre el open(tmp, "w")
        # y el `os.replace(tmp, path)`.
        tmp = config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"active_instance_name": "sneaky_attacker"}))
        try:
            watcher.reload_now()
            # CRITICO: el watcher NO debe haber leido el tmp.
            assert watcher.get_active_name() == "bot_1", (
                "BUG: watcher leyo el .tmp, no el config principal"
            )
        finally:
            tmp.unlink(missing_ok=True)


class TestTiming:
    """Verifica que el watcher cumple el budget de <=2s del spec."""

    @pytest.mark.asyncio
    async def test_mtime_within_2s(self, config_path):
        """Spec: 'mtime polling <=2s'. Verificamos que un cambio se
        refleja en menos de 2s. Usamos poll=0.1s para que el test sea
        rapido; el principio es el mismo (un tick <= 2s).
        """
        watcher = InstanceWatcher(
            config_path, poll_seconds=0.1, jitter_seconds=0.02,
        )
        await watcher.start()
        try:
            # Un primer tick para que el watcher vea el estado vacio.
            await asyncio.sleep(0.15)
            assert watcher.get_active_name() == ""
            # Escribimos el nuevo nombre y esperamos el proximo tick.
            start = time.perf_counter()
            config_path.write_text(json.dumps({"active_instance_name": "bot_1"}))
            # Deadline: 2s. En la practica con poll=0.1s lo vemos en ~100ms.
            while watcher.get_active_name() != "bot_1":
                if time.perf_counter() - start > 2.0:
                    pytest.fail(
                        f"Watcher no levanto el cambio en 2s "
                        f"(actual: {watcher.get_active_name()!r})"
                    )
                await asyncio.sleep(0.05)
            elapsed = time.perf_counter() - start
            assert elapsed < 2.0
        finally:
            await watcher.stop()


class TestJitter:
    """El jitter evita que multiples instancias del watcher sincronicen
    sus ticks (thundering herd). Verificamos que el sleep_for es la
    suma de poll_seconds + uniform(-jitter, +jitter)."""

    def test_compute_sleep_for_formula(self, config_path):
        """sleep_for = poll_seconds + uniform(-jitter, +jitter), clampeado a 0.

        Mockeamos random.uniform para verificar la formula
        deterministicamente. Esto es mas robusto que patchear
        asyncio.sleep (que parchea el modulo global y rompe el
        asyncio.sleep del test mismo).
        """
        watcher = InstanceWatcher(
            config_path, poll_seconds=1.0, jitter_seconds=0.15,
        )
        # uniform=+0.1 -> sleep_for = 1.1
        with patch("instance_watcher.random.uniform", return_value=0.1):
            assert abs(watcher._compute_sleep_for() - 1.1) < 0.001
        # uniform=-0.15 -> sleep_for = 0.85 (positivo, no se clampa)
        with patch("instance_watcher.random.uniform", return_value=-0.15):
            assert abs(watcher._compute_sleep_for() - 0.85) < 0.001
        # uniform=-2.0 -> sleep_for = -1.0 -> clampeado a 0
        with patch("instance_watcher.random.uniform", return_value=-2.0):
            assert watcher._compute_sleep_for() == 0.0


class TestLifecycle:
    """Start/stop deben ser idempotentes y limpiar bien la task."""

    @pytest.mark.asyncio
    async def test_start_stop_idempotent(self, config_path, fast_watcher):
        """start() crea la task; stop() la cancela y la limpia.
        Doble start() no spawna una segunda task. stop() sin start()
        previo es un no-op.
        """
        # start() inicial
        await fast_watcher.start()
        assert fast_watcher._task is not None
        assert not fast_watcher._task.done()
        first_task = fast_watcher._task
        # Doble start() no debe spawnar otra task
        await fast_watcher.start()
        assert fast_watcher._task is first_task
        # stop() limpia
        await fast_watcher.stop()
        assert fast_watcher._task is None
        # stop() sin task es no-op
        await fast_watcher.stop()
        assert fast_watcher._task is None


class TestThreadSafety:
    """El poll loop (async) y reload_now (sync, llamado por tests o
    por admin tooling futuro) pueden coincidir. El lock garantiza que
    el swap de `_active_name` y `_known_mtime` sea consistente."""

    def test_reload_now_concurrent(self, config_path):
        """20 threads * 50 reloads cada uno: no crashea, estado final consistente.

        El lock serializa el read+swap. Sin el lock, dos threads
        podrian leer el mismo mtime, ambos creer que es la primera
        vez, y pisarse el _active_name. Con el lock, el segundo
        espera al primero y ve mtime == _known_mtime (skip).
        """
        config_path.write_text(json.dumps({"active_instance_name": "bot_1"}))
        watcher = InstanceWatcher(config_path, poll_seconds=1.0, jitter_seconds=0.0)
        watcher.reload_now()
        assert watcher.get_active_name() == "bot_1"

        def hammer(_):
            for _ in range(50):
                watcher.reload_now()

        with ThreadPoolExecutor(max_workers=20) as ex:
            list(ex.map(hammer, range(20)))
        # Despues de toda la paliza, el estado sigue consistente.
        assert watcher.get_active_name() == "bot_1"

        # Y un cambio real despues de la paliza se ve (no se "perdio"
        # un swap por un read race).
        time.sleep(0.01)
        config_path.write_text(json.dumps({"active_instance_name": "bot_2"}))
        watcher.reload_now()
        assert watcher.get_active_name() == "bot_2"
