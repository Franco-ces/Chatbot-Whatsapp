"""Tests para la plomería de faq_threshold en ConfigManager (Task 1).

Cubre los escenarios del spec:
- Default 0.88 cuando no está presente
- Valor custom preservado
- Defaults previos (email, telefono, bot_phone) siguen aplicando
- El archivo config_bot.json tiene la clave
"""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def fresh_config(tmp_path, monkeypatch):
    """Recarga ConfigManager apuntando a un archivo temporal."""
    target = tmp_path / "config_bot.json"
    # Sacar cualquier módulo previamente importado para forzar reimport
    for mod in list(sys.modules):
        if mod == "ConfigManager":
            del sys.modules[mod]
    # Reimportar apuntando al tmp_path
    spec = __import__("importlib.util").util.spec_from_file_location(
        "ConfigManager", Path(__file__).resolve().parent.parent / "src" / "ConfigManager.py"
    )
    cfg_mod = __import__("importlib.util").util.module_from_spec(spec)

    # Parchear __file__ ANTES de ejecutar el módulo para que ROOT_DIR caiga en tmp_path
    fake_src = tmp_path / "src" / "ConfigManager.py"
    fake_src.parent.mkdir(parents=True, exist_ok=True)
    # Leer el original y escribirlo con __file__ apuntando al fake
    original = (Path(__file__).resolve().parent.parent / "src" / "ConfigManager.py").read_text(encoding="utf-8")
    fake_src.write_text(original, encoding="utf-8")

    spec = __import__("importlib.util").util.spec_from_file_location(
        "ConfigManager", str(fake_src)
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
