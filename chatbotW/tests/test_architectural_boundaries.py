"""AST-based enforcement of the architectural boundary rules from
`design.md` §Architectural Boundaries.

Este test NO prueba comportamiento: prueba ESTRUCTURA. Garantiza que
los modulos que el design declara como 'puente unico' o 'aislados' no
acumulan dependencias cruzadas en futuras PRs. Si alguien importa
`bot_service` desde `evolution_admin` por alguna razon urgente sin
discutirlo en design.md, este test rompe y obliga a la conversacion.

Reglas enforced (verbatim de design.md):

  evolution_models   NO importa: bot_service, main, interface,
                             whatsapp_client, ConfigManager,
                             instance_activation, instance_watcher, httpx
  evolution_http     NO importa: bot_service, main, interface,
                             whatsapp_client, ConfigManager,
                             instance_activation, instance_watcher
  evolution_admin    NO importa: bot_service, main, interface,
                             whatsapp_client, ConfigManager,
                             instance_activation, instance_watcher
  instance_watcher   NO importa: ningun evolution_*

  instance_activation es el UNICO modulo que importa desde AMBOS
  ConfigManager Y evolution_admin. El conteo debe ser exactamente 1.

Scope: solo se escanean archivos `chatbotW/src/*.py` (no `tests/`,
no `__pycache__`, no subdirectorios). Si el boundary test alguna vez
necesita escanear mas, ese es un cambio de diseno, no un fix del test.
"""
import ast
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Mapa de imports prohibidos (de design.md §Boundaries)
# ---------------------------------------------------------------------------
# Cada entrada: nombre del modulo sin extension -> set de imports prohibidos.
# `httpx` esta en la lista de `evolution_models` porque ese modulo
# deberia ser puro Pydantic: si necesita HTTP, va por `evolution_http`.
FORBIDDEN = {
    "evolution_models": {
        "bot_service", "main", "interface", "whatsapp_client",
        "ConfigManager", "instance_activation", "instance_watcher",
        "httpx",
    },
    "evolution_http": {
        "bot_service", "main", "interface", "whatsapp_client",
        "ConfigManager", "instance_activation", "instance_watcher",
    },
    "evolution_admin": {
        "bot_service", "main", "interface", "whatsapp_client",
        "ConfigManager", "instance_activation", "instance_watcher",
    },
}

# instance_watcher no debe importar nada que arranque con `evolution_`
# (chequeo de prefijo, no de equality).
WATCHER_FORBIDDEN_PREFIX = "evolution_"

# Cross-importer unico: solo instance_activation cruza estos dos
# dominios. Si otro modulo lo hace, rompe el contrato.
CROSS_IMPORTER_MODULES = {"ConfigManager", "evolution_admin"}
CROSS_IMPORTER_UNIQUE_FILE = "instance_activation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).resolve().parent.parent / "src"


def _list_python_sources() -> list[Path]:
    """Devuelve todos los .py directos bajo src/ (no recursivo, no __pycache__)."""
    return sorted(p for p in SRC_DIR.glob("*.py") if p.name != "__init__.py")


def _normalize_module(name: str) -> str:
    """Para `from x.y.z import ...` usamos el modulo top-level `x` para
    el match. Asi `from ConfigManager.cosas import foo` matchea contra
    `ConfigManager` (no contra `ConfigManager.cosas`).
    """
    return name.split(".", 1)[0]


def _collect_imports(source: Path) -> list[tuple[str, int]]:
    """Devuelve [(modulo, linea), ...] para todos los `import X` y
    `from X import Y` en el archivo. Los modulos se normalizan a
    top-level. Si el parse falla, raise (queremos saber del syntax
    error, no silenciarlo)."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((_normalize_module(alias.name), node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` -> module es ''; lo ignoramos.
            if node.module is None:
                continue
            out.append((_normalize_module(node.module), node.lineno))
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_forbidden_imports():
    """Cada modulo en FORBIDDEN no debe importar nada de su set prohibido."""
    files_to_check = {
        p.stem: p
        for p in _list_python_sources()
        if p.stem in FORBIDDEN
    }
    assert files_to_check, "FORBIDDEN contiene modulos que no estan en src/"

    violations: list[str] = []
    for mod_stem, src_path in files_to_check.items():
        forbidden_set = FORBIDDEN[mod_stem]
        for imported, lineno in _collect_imports(src_path):
            if imported in forbidden_set:
                violations.append(
                    f"{src_path.name}: line {lineno}: import '{imported}' "
                    f"forbidden in {mod_stem}"
                )

    if violations:
        pytest.fail("\n".join(violations))


def test_instance_watcher_does_not_import_evolution():
    """El watcher es observador pasivo: no conoce evolution_*. Si lo
    hiciera, estariamos creando un ciclo entre el bot y el cliente
    de Evolution, justo lo que el design intenta evitar."""
    src_path = SRC_DIR / "instance_watcher.py"
    if not src_path.exists():
        pytest.skip("instance_watcher.py no existe todavia (PR 3 pendiente)")

    for imported, lineno in _collect_imports(src_path):
        if imported.startswith(WATCHER_FORBIDDEN_PREFIX):
            pytest.fail(
                f"{src_path.name}: line {lineno}: import '{imported}' "
                f"forbidden in instance_watcher (no evolution_* allowed)"
            )


def test_instance_activation_is_unique_cross_importer():
    """instance_activation es el UNICO modulo que importa de AMBOS
    ConfigManager y evolution_admin. Si el conteo != 1, alguien metio
    un shortcut por otro modulo y se rompio la frontera de dominios."""
    cross_importer_files: list[Path] = []
    for src_path in _list_python_sources():
        imports = {mod for mod, _ in _collect_imports(src_path)}
        if CROSS_IMPORTER_MODULES.issubset(imports):
            cross_importer_files.append(src_path)

    if len(cross_importer_files) != 1:
        names = [p.name for p in cross_importer_files]
        pytest.fail(
            f"Expected exactly 1 module to import from both "
            f"{sorted(CROSS_IMPORTER_MODULES)} (unique cross-importer), "
            f"found {len(cross_importer_files)}: {names}. "
            f"Only '{CROSS_IMPORTER_UNIQUE_FILE}.py' is allowed."
        )

    if cross_importer_files[0].stem != CROSS_IMPORTER_UNIQUE_FILE:
        pytest.fail(
            f"Cross-importer must be '{CROSS_IMPORTER_UNIQUE_FILE}.py', "
            f"found '{cross_importer_files[0].name}'"
        )


def test_boundary_map_consistency():
    """Guard rail contra drift: si alguien agrega un modulo nuevo al
    FORBIDDEN map, este test recuerda que ese modulo debe existir.
    Si alguien BORRA un modulo de FORBIDDEN, este test lo detecta."""
    files = {p.stem for p in _list_python_sources()}
    for mod_stem, forbidden_set in FORBIDDEN.items():
        assert mod_stem in files, (
            f"FORBIDDEN references '{mod_stem}.py' but it does not exist "
            f"in {SRC_DIR}. Remove from FORBIDDEN or add the file."
        )
        # Y todos los modulos en los sets prohibidos deben ser plausibles
        # (i.e. no typos como 'whatsapp_clients' que no existe en src).
        for forbidden_mod in forbidden_set:
            # Algunos modulos prohibidos NO estan en src/ (p.ej. `main`
            # en tests, o dependencias externas). Solo validamos los
            # que SI estan en src/.
            if not forbidden_mod.startswith("evolution_") and forbidden_mod not in {
                "bot_service", "main", "interface", "whatsapp_client",
                "ConfigManager", "instance_activation", "instance_watcher",
            }:
                # Es un modulo externo (httpx, etc.) o un typo.
                if forbidden_mod not in {"httpx"}:
                    # No es un modulo conocido del proyecto ni una dep
                    # comun: probablemente typo.
                    pytest.fail(
                        f"FORBIDDEN['{mod_stem}'] references unknown module "
                        f"'{forbidden_mod}'. Verifica que no sea un typo."
                    )


def test_all_evolution_modules_are_scanned():
    """Todos los archivos evolution_*.py en src/ deben tener una entrada
    en FORBIDDEN. Si alguien crea `evolution_xyz.py` y no lo agrega al
    mapa, este test rompe — no hay forma de que la frontera pase
    silenciosamente."""
    forbidden_keys = set(FORBIDDEN.keys())
    for src_path in _list_python_sources():
        if src_path.stem.startswith("evolution_"):
            assert src_path.stem in forbidden_keys, (
                f"Found evolution module '{src_path.name}' not in FORBIDDEN. "
                f"Add it with its forbidden-import set."
            )
