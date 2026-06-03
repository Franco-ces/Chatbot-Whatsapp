"""Tests para la plomería de faq_threshold en ConfigManager (Task 1).

Cubre los escenarios del spec:
- Default 0.88 cuando no está presente
- Valor custom preservado
- Defaults previos (email, telefono, bot_phone) siguen aplicando
- El archivo config_bot.json tiene la clave
"""
import errno
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def fresh_config(tmp_path, monkeypatch):
    """Recarga ConfigManager apuntando a un archivo temporal."""
    target = tmp_path / "config_bot.json"
    # Parchear paths.CONFIG_FILE para que apunte al tmp_path
    import paths
    monkeypatch.setattr(paths, "CONFIG_FILE", target)

    # Sacar módulos previamente importados para forzar reimport
    for mod in list(sys.modules):
        if mod == "ConfigManager":
            del sys.modules[mod]

    # Reimportar ConfigManager (ahora usa paths.CONFIG_FILE parcheado)
    spec = __import__("importlib.util").util.spec_from_file_location(
        "ConfigManager", Path(__file__).resolve().parent.parent / "src" / "ConfigManager.py"
    )
    cfg_mod = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(cfg_mod)
    return cfg_mod, target


def test_default_es_0_88_cuando_archivo_no_existe(fresh_config):
    cfg_mod, target = fresh_config
    # No existe el archivo → ConfigManager lo crea con defaults
    cm = cfg_mod.ConfigManager()
    assert cm.config.get("faq_threshold") == 0.88


def test_default_es_0_88_cuando_archivo_existe_sin_clave(fresh_config):
    cfg_mod, target = fresh_config
    target.write_text(json.dumps({"email": "x@y.com", "telefono": "123", "bot_phone": ""}), encoding="utf-8")
    cm = cfg_mod.ConfigManager()
    assert cm.config.get("faq_threshold") == 0.88


def test_valor_custom_se_preserva(fresh_config):
    cfg_mod, target = fresh_config
    target.write_text(json.dumps({
        "email": "x@y.com",
        "telefono": "123",
        "bot_phone": "",
        "faq_threshold": 0.75,
    }), encoding="utf-8")
    cm = cfg_mod.ConfigManager()
    assert cm.config.get("faq_threshold") == 0.75


def test_defaults_previos_siguen_aplicando(fresh_config):
    """Los defaults email/telefono/bot_phone no se rompen al añadir faq_threshold."""
    cfg_mod, target = fresh_config
    # Archivo sin ninguna clave → el __init__ crea con defaults
    cm = cfg_mod.ConfigManager()
    assert "email" in cm.config
    assert "telefono" in cm.config
    assert "bot_phone" in cm.config
    # Y el nuevo default también
    assert "faq_threshold" in cm.config
    assert cm.config["faq_threshold"] == 0.88


def test_cargar_re_aplica_default_si_falta(fresh_config):
    """Llamadas subsecuentes a cargar() también re-aplican setdefault."""
    cfg_mod, target = fresh_config
    target.write_text(json.dumps({"email": "x@y.com"}), encoding="utf-8")
    cm = cfg_mod.ConfigManager()
    # Forzar recarga tras modificar disco
    target.write_text(json.dumps({"email": "x@y.com"}), encoding="utf-8")
    cm.cargar()
    assert cm.config.get("faq_threshold") == 0.88


# ---------------------------------------------------------------------------
# Task 2.3 (PR 2): tests para `set_active_instance`
# ---------------------------------------------------------------------------
# Cobertura:
# 1) happy write: el campo se persiste y se re-lee correctamente
# 2) tmp cleanup on OSError: el .tmp desaparece y la excepcion es ConfigError
# 3) atomicidad via mtime: cada escritura avanza mtime, contenido final
#    es siempre JSON valido (no hay estado intermedio visible)
# 4) preserva otras claves: email, telefono, etc. quedan intactos
# 5) default backfill: un config viejo sin `active_instance_name` lo recibe
# ---------------------------------------------------------------------------


def test_set_active_instance_happy_write_persists_value(fresh_config):
    """Tras `set_active_instance("bot_2")` el archivo contiene el campo nuevo
    y un reload lo levanta tal cual."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()
    assert "active_instance_name" not in cm.config  # todavia no se persistio

    cm.set_active_instance("bot_2")

    # En memoria y en disco estan sincronizados.
    assert cm.config["active_instance_name"] == "bot_2"
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["active_instance_name"] == "bot_2"

    # Un reload lo ve.
    cm2 = cfg_mod.ConfigManager()
    assert cm2.config["active_instance_name"] == "bot_2"


def test_set_active_instance_cleans_tmp_on_oserror(fresh_config):
    """Si `os.fsync` revienta, el .tmp se borra y se relanza ConfigError."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()
    tmp_path = target.parent
    tmp_file = tmp_path / "config_bot.json.tmp"

    from exceptions import ConfigError

    with patch("os.fsync", side_effect=OSError("disk full simulated")):
        with pytest.raises(ConfigError) as exc_info:
            cm.set_active_instance("bot_2")

    # El tmp fue limpiado.
    assert not tmp_file.exists(), "el .tmp no deberia quedar en disco tras OSError"
    # El codigo es el de write failed (E-CFG-002) y conserva la causa original.
    assert exc_info.value.code.value == "E-CFG-002"
    assert "disk full simulated" in str(exc_info.value.detail)
    assert isinstance(exc_info.value.__cause__, OSError)
    # El config real no fue tocado.
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert "active_instance_name" not in on_disk


def test_set_active_instance_advances_mtime_and_writes_full_content(fresh_config):
    """Cada escritura atomica avanza mtime y el archivo final es JSON valido.

    Esto cubre la promesa de `os.replace` (atomica en POSIX): el watcher
    jamas ve un JSON a medio escribir. Si la promesa se rompiera y el
    archivo quedara corrupto entre writes, este test fallaria al parsearlo.
    """
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()
    mtime_before = target.stat().st_mtime

    # La resolucion de mtime en algunos FS es 1s; dormimos lo necesario
    # para que el segundo `set_active_instance` registre un mtime claramente
    # distinto del primero.
    time.sleep(1.1)
    cm.set_active_instance("bot_2")
    mtime_after_first = target.stat().st_mtime
    assert mtime_after_first > mtime_before

    time.sleep(1.1)
    cm.set_active_instance("bot_3")
    mtime_after_second = target.stat().st_mtime
    assert mtime_after_second > mtime_after_first

    # El contenido final es siempre un JSON valido y completo, no un estado
    # intermedio: esta es la garantia de "no in-between state visible"
    # que ofrece `os.replace`.
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["active_instance_name"] == "bot_3"


def test_set_active_instance_preserves_other_keys(fresh_config):
    """Escribir `active_instance_name` no pisa las otras claves del config."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()
    # Simulamos un admin que ya configuro email y telefono antes del swap.
    cm.config["email"] = "soporte@example.com"
    cm.config["telefono"] = "+54 11 5555-0000"
    cm.config["bot_phone"] = "5491155550000"
    cm.config["faq_threshold"] = 0.91  # custom, no debe ser pisado por el default

    cm.set_active_instance("bot_2")

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["active_instance_name"] == "bot_2"
    assert on_disk["email"] == "soporte@example.com"
    assert on_disk["telefono"] == "+54 11 5555-0000"
    assert on_disk["bot_phone"] == "5491155550000"
    assert on_disk["faq_threshold"] == 0.91

    # Y al recargar el ConfigManager, todo sigue ahi.
    cm2 = cfg_mod.ConfigManager()
    assert cm2.config["email"] == "soporte@example.com"
    assert cm2.config["active_instance_name"] == "bot_2"


def test_cargar_backfills_default_active_instance_name(fresh_config):
    """Un config viejo (sin `active_instance_name`) lo recibe como `` tras
    `cargar()`. Asi el bot puede hacer fallback a
    `os.environ["EVOLUTION_INSTANCE_NAME"]` sin tocar el archivo en disco."""
    cfg_mod, target = fresh_config
    # Escribimos un config SIN la clave, simulando un deploy pre-PR-2.
    target.write_text(json.dumps({
        "email": "x@y.com",
        "telefono": "123",
        "bot_phone": "",
        "faq_threshold": 0.88,
    }), encoding="utf-8")

    cm = cfg_mod.ConfigManager()
    assert cm.config["active_instance_name"] == ""
    # Y el archivo en disco sigue sin la clave: setdefault no persiste.
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert "active_instance_name" not in on_disk


# ---------------------------------------------------------------------------
# Task 2.1–2.2: tests para retry en EBUSY/ETXTBSY en set_active_instance
# ---------------------------------------------------------------------------


def test_set_active_instance_retries_on_ebusy(fresh_config):
    """Task 2.1: si os.replace falla con ETXTBSY dos veces y luego tiene exito,
    set_active_instance completa sin error."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()

    call_count = 0
    original_replace = os.replace

    def flaky_replace(src, dst):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise OSError(errno.ETXTBSY, "Text file busy")
        return original_replace(src, dst)

    with patch("os.replace", side_effect=flaky_replace):
        # Mockeamos sleep: con jitter+MAX_RETRIES=20 un sleep real tardaria
        # segundos y el test seria lento. Solo validamos la logica de retry.
        with patch.object(cfg_mod.time, "sleep"):
            # No debe lanzar excepcion
            cm.set_active_instance("bot_2")

    assert cm.config["active_instance_name"] == "bot_2"
    assert call_count == 3


def test_set_active_instance_fails_after_max_ebusy_retries(fresh_config):
    """Task 2.2: si os.replace siempre falla con ETXTBSY,
    set_active_instance lanza ConfigError despues de MAX_RETRIES intentos."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()

    call_count = 0

    def always_ebusy(src, dst):
        nonlocal call_count
        call_count += 1
        raise OSError(errno.ETXTBSY, "Text file busy")

    from exceptions import ConfigError

    with patch("os.replace", side_effect=always_ebusy):
        # Mockeamos sleep para que el test no tarde ~90s con MAX_RETRIES=20.
        # Solo nos importa que `os.replace` sea llamado MAX_RETRIES veces.
        with patch.object(cfg_mod.time, "sleep"):
            with pytest.raises(ConfigError) as exc_info:
                cm.set_active_instance("bot_2")

    assert exc_info.value.code.value == "E-CFG-002"
    assert call_count == cfg_mod.MAX_RETRIES


def test_max_retries_es_20_para_aguantar_wsl2_bind_mount(fresh_config):
    """Task 2.4: MAX_RETRIES debe ser 20 para tolerar locks prolongados de
    Docker Desktop WSL2 bind-mount (los 10 intentos previos daban ~50s y no
    alcanzaban; el lock puede durar mas de un minuto)."""
    cfg_mod, target = fresh_config
    assert cfg_mod.MAX_RETRIES == 20


def test_set_active_instance_delay_tiene_jitter(fresh_config):
    """Task 2.5: el delay entre reintentos incluye jitter aleatorio para
    evitar thundering-herd si varios procesos pelean por el mismo lock
    (ej. WSL2 bind-mount). Mockeamos random.uniform para verificar que
    se suma al base delay exponencial."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()

    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    with patch("os.replace", side_effect=OSError(errno.ETXTBSY, "busy")):
        with patch.object(cfg_mod.time, "sleep", side_effect=fake_sleep):
            with patch.object(cfg_mod.random, "uniform", return_value=0.5) as mock_uniform:
                from exceptions import ConfigError
                with pytest.raises(ConfigError):
                    cm.set_active_instance("bot_2")

    # random.uniform fue llamado (al menos una vez por retry)
    assert mock_uniform.call_count >= cfg_mod.MAX_RETRIES - 1

    # Cada sleep debe ser >= base exponencial (sin jitter restado)
    # base para attempt=0 es 0.2, attempt=1 es 0.4, ..., capped a 5.0
    # Con jitter=0.5, el delay final = base + 0.5
    expected_base_delays = []
    base = 0.2
    for i in range(cfg_mod.MAX_RETRIES - 1):
        expected_base_delays.append(min(base * (2 ** i), 5.0) + 0.5)

    assert sleeps == pytest.approx(expected_base_delays, abs=1e-9)


# ---------------------------------------------------------------------------
# Task 3: tests para set_active_instance_async (write no-bloqueante + FIFO)
# ---------------------------------------------------------------------------


async def test_set_active_instance_async_encola_y_retorna_inmediato(fresh_config):
    """Task 3.1: set_active_instance_async debe encolar el write y retornar
    inmediato aunque el write subyacente tarde 100s en EBUSY. Asi el endpoint
    de activacion puede devolver 202 sin colgar al usuario."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()

    # Mockeamos set_active_instance sincrono para que demore "mucho".
    import time as time_mod

    def slow_write(name):
        time_mod.sleep(2.0)  # simula 2s de retry
        cm.config["active_instance_name"] = name
        return None

    try:
        with patch.object(cm, "set_active_instance", side_effect=slow_write):
            start = time_mod.monotonic()
            await cm.set_active_instance_async("bot_2")
            elapsed = time_mod.monotonic() - start

        # El enqueue debe haber retornado casi inmediato (<200ms), NO 2s.
        assert elapsed < 0.2, f"set_active_instance_async bloqueó {elapsed:.2f}s"
    finally:
        await cm.stop_worker()


async def test_set_active_instance_async_procesa_en_orden_fifo(fresh_config):
    """Task 3.2: si encolamos A, B, C en ese orden, el worker debe procesarlos
    en ese orden. El archivo final tiene el ultimo valor, pero los writes
    intermedios se aplican en secuencia (no se intercalan)."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()

    # Capturamos el orden real en que se invoca set_active_instance sincrono.
    write_order = []
    real_set_active = cm.set_active_instance

    def tracking_set_active(name):
        write_order.append(name)
        return real_set_active(name)

    try:
        with patch.object(cm, "set_active_instance", side_effect=tracking_set_active):
            await cm.set_active_instance_async("bot_A")
            await cm.set_active_instance_async("bot_B")
            await cm.set_active_instance_async("bot_C")
            # Esperamos a que el worker drene la cola
            await cm._write_queue.join()

        assert write_order == ["bot_A", "bot_B", "bot_C"]
        # El archivo final tiene el ultimo valor
        cm2 = cfg_mod.ConfigManager()
        assert cm2.config["active_instance_name"] == "bot_C"
    finally:
        await cm.stop_worker()


async def test_set_active_instance_async_worker_arranca_al_primer_enqueue(fresh_config):
    """Task 3.3: el worker se crea lazy en el primer set_active_instance_async.
    Antes de eso, _worker_task debe ser None. Despues, debe estar vivo."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()

    try:
        assert cm._worker_task is None

        await cm.set_active_instance_async("bot_x")
        assert cm._worker_task is not None
    finally:
        await cm.stop_worker()


async def test_set_active_instance_async_maneja_error_sin_morir(fresh_config):
    """Task 3.4: si un write del worker falla (ej. EBUSY que agota MAX_RETRIES),
    el worker sigue vivo y procesa los siguientes writes."""
    cfg_mod, target = fresh_config
    cm = cfg_mod.ConfigManager()

    fail_count = {"n": 0}
    real_set_active = cm.set_active_instance

    def maybe_fail(name):
        fail_count["n"] += 1
        if fail_count["n"] == 1:
            from exceptions import ConfigError
            from error_codes import ErrorCode
            raise ConfigError(ErrorCode.CFG_WRITE_FAILED, detail="boom")
        return real_set_active(name)

    try:
        with patch.object(cm, "set_active_instance", side_effect=maybe_fail):
            await cm.set_active_instance_async("bot_first")
            await cm.set_active_instance_async("bot_second")
            await cm._write_queue.join()

        # El primer write falló, el segundo tuvo éxito.
        cm2 = cfg_mod.ConfigManager()
        assert cm2.config["active_instance_name"] == "bot_second"
    finally:
        await cm.stop_worker()
