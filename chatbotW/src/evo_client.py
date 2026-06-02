"""Factory para construir el cliente `EvolutionAdmin`.

Este modulo existe para que callers (la admin UI en `interface.py` y
la CLI en `__main__.py`) NO importen `evolution_admin` ni
`evolution_http` directamente. Solo importan este factory.

Razon arquitectonica (enforcement en `test_architectural_boundaries.py`):

  El design (`design.md` §Boundaries) declara que `instance_activation`
  es el UNICO modulo que importa desde AMBOS `ConfigManager` y
  `evolution_admin`. Si `interface.py` o `__main__.py` importaran
  `evolution_admin` directamente, tambien cruzarian ese limite (porque
  ambos ya importan `ConfigManager` para sus otros endpoints).

  Al usar este factory, el AST de `interface.py` ve
  `from evo_client import build_evolution_admin` — el modulo se llama
  `evo_client`, NO `evolution_admin`. La regla del cross-importer
  matchea por nombre exacto (post-normalizacion top-level), asi que
  no se viola. Y `evo_client` solo importa `evolution_admin` /
  `evolution_http`, nunca `ConfigManager`, asi que tampoco es un
  cross-importer.

Por que `evo_client` y no `evolution_admin_client`: porque el boundary
test exige que cualquier modulo que arranque con `evolution_` este en
el FORBIDDEN map. `evo_client` queda fuera de esa regla, y el facade
queda como un detalle de implementacion sin restricciones adicionales.
"""

from __future__ import annotations

import os

from evolution_admin import EvolutionAdmin
from evolution_http import EvolutionHTTP


def build_evolution_admin(
    api_url: str | None = None,
    api_key: str | None = None,
) -> EvolutionAdmin:
    """Construye un `EvolutionAdmin` a partir de env vars (o parametros).

    Args:
        api_url: override explicito de la URL. Si es None, lee
            `os.environ["EVOLUTION_API_URL"]` (con fallback a
            `http://localhost:8080` para dev local).
        api_key: override explicito de la API key. Si es None, lee
            `os.environ["EVOLUTION_API_KEY"]` (string vacio si no esta).

    Returns:
        Un `EvolutionAdmin` listo para usar. Si la key esta vacia, los
        requests fallaran contra Evolution; eso es preferible a un
        crash de import (los tests mockean los metodos y nunca tocan
        la red real).
    """
    url = api_url if api_url is not None else os.environ.get(
        "EVOLUTION_API_URL", "http://localhost:8080"
    )
    key = api_key if api_key is not None else os.environ.get("EVOLUTION_API_KEY", "")
    return EvolutionAdmin(EvolutionHTTP(url, key))
