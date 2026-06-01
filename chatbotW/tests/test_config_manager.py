"""Tests para la plomería de faq_threshold en ConfigManager (Task 1).

Cubre los escenarios del spec:
- Default 0.88 cuando no está presente
- Valor custom preservado
- Defaults previos (email, telefono, bot_phone) siguen aplicando
- El archivo config_bot.json tiene la clave
"""
import json
import sys
from pathlib import Path

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
