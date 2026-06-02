"""CLI entrypoint: `python -m src <subcommand> [...]`.

Salida JSON a stdout, mensajes humanos a stderr, exit codes
documentados (0/1/2/3) para que el script de setup (`primera_instalacion.sh`,
PR 5) pueda diferenciar errores sin parsear texto.

Subcomandos:
- list
- create --name NAME
- qr --name NAME
- state --name NAME
- set-webhook --name NAME --url URL [--secret SECRET]
- set-active --name NAME [--config PATH]   (requiere `instance_activation`, PR 2)

Por que un `__main__.py` y no un `if __name__ == "__main__"` en
`evolution_admin.py`? Porque Docker compose ya fija `working_dir: /app/src`,
y `python -m src` desde ese directorio es la invocacion canonica: localiza
el paquete `src` en sys.path (gracias al `__init__.py` vacio) y ejecuta
su `__main__`. Asi `primera_instalacion.sh` puede correr
`docker compose exec bot python -m src create "$EVOLUTION_INSTANCE_NAME"`
sin asumir layout de archivos.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Optional

# Cuando se invoca como `python -m src` desde un directorio arbitrario, el
# paquete `src` se carga pero su contenido NO se agrega a sys.path. Como
# el resto del proyecto usa bare imports (`from evolution_admin import ...`),
# ponemos el directorio del paquete en sys.path explicitamente. Asi el CLI
# funciona tanto en local (desde `chatbotW/`) como en Docker
# (`docker compose exec bot python -m src ...` con working_dir=/app/src).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from error_codes import ErrorCode  # noqa: E402
from exceptions import AppError, ConfigError  # noqa: E402
from evo_client import build_evolution_admin  # noqa: E402
from evolution_models import WebhookConfig  # noqa: E402

if TYPE_CHECKING:
    # Solo para type hints; el AST del boundary test NO incluye imports
    # dentro de `if TYPE_CHECKING:`. Asi `__main__.py` no cuenta como
    # cross-importer de evolution_admin, y instance_activation sigue
    # siendo el unico.
    from evolution_admin import EvolutionAdmin

# ---------------------------------------------------------------------------
# Exit codes (documentados en design.md §Interfaces / Contracts §CLI)
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_HTTP_ERROR = 1
EXIT_STATE_PRECONDITION = 2
EXIT_CONFIG_ERROR = 3


def _build_admin_from_env() -> EvolutionAdmin:
    """Construye un `EvolutionAdmin` con URL/key de las env vars.

    Falla con exit 1 si falta la key. La URL tiene un default razonable
    para que el comando `list` funcione en un dev local sin .env.
    """
    api_key = os.environ.get("EVOLUTION_API_KEY", "")
    if not api_key:
        print("ERROR: EVOLUTION_API_KEY no está definida.", file=sys.stderr)
        sys.exit(EXIT_HTTP_ERROR)
    return build_evolution_admin()


def _emit_json(payload: Any) -> None:
    """Escribe `payload` como JSON en una sola linea a stdout."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str))
    sys.stdout.write("\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Subcomandos (cada uno retorna exit code; ya escribio a stdout/stderr)
# ---------------------------------------------------------------------------
async def _cmd_list(admin: EvolutionAdmin) -> int:
    instances = await admin.list_instances()
    _emit_json([i.model_dump(by_alias=True, exclude_none=True) for i in instances])
    return EXIT_OK


async def _cmd_create(admin: EvolutionAdmin, *, name: str) -> int:
    info = await admin.create_instance(name)
    _emit_json(info.model_dump(by_alias=True, exclude_none=True))
    return EXIT_OK


async def _cmd_qr(admin: EvolutionAdmin, *, name: str) -> int:
    payload = await admin.get_qr(name)
    _emit_json({"base64": payload.base64, "state": payload.state.value})
    return EXIT_OK


async def _cmd_state(admin: EvolutionAdmin, *, name: str) -> int:
    state = await admin.get_state(name)
    _emit_json({"state": state.value})
    return EXIT_OK


async def _cmd_set_webhook(
    admin: EvolutionAdmin, *, name: str, url: str, secret: Optional[str]
) -> int:
    headers = {"X-Webhook-Secret": secret} if secret else {}
    config = WebhookConfig(url=url, headers=headers)
    await admin.set_webhook(name, config)
    _emit_json({"status": "ok"})
    return EXIT_OK


async def _cmd_set_active(*, name: str, config_path: Optional[str]) -> int:
    """Activa una instancia: re-verifica estado, configura webhook, escribe
    `config_bot.json.active_instance_name` de forma atomica.

    Delega en `instance_activation.set_active` (PR 2). Si ese modulo
    todavia no existe, devuelve EXIT_CONFIG_ERROR con un mensaje claro;
    asi el CLI ya es funcional y se completa cuando PR 2 mergee.

    NOTA: pasamos `config_path` (no un `ConfigManager` pre-construido).
    El bridge construye el ConfigManager internamente. Asi el CLI NO
    importa `ConfigManager` directamente, manteniendo limpia la frontera
    de dominios (instance_activation sigue siendo el unico cross-importer).
    """
    try:
        from instance_activation import set_active  # type: ignore
    except ImportError as e:
        print(
            f"ERROR: 'set-active' requiere 'instance_activation' (PR 2). Detalle: {e}",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    admin = _build_admin_from_env()
    webhook_url = os.environ.get("BOT_URL", "")
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")

    await set_active(
        name,
        admin=admin,
        config_path=config_path,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
    )
    _emit_json({"status": "ok", "active": name})
    return EXIT_OK


# ---------------------------------------------------------------------------
# argparse + dispatch
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src",
        description="CLI administrativo para Evolution API (WhatsApp instances).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Listar todas las instancias registradas.")

    p = sub.add_parser("create", help="Crear una nueva instancia.")
    p.add_argument("--name", required=True, help="Nombre único de la instancia.")

    p = sub.add_parser("qr", help="Obtener el QR actual de una instancia.")
    p.add_argument("--name", required=True)

    p = sub.add_parser("state", help="Consultar el estado de una instancia (open/close/connecting/unknown).")
    p.add_argument("--name", required=True)

    p = sub.add_parser("set-webhook", help="Registrar el webhook que Evolution llamará al recibir mensajes.")
    p.add_argument("--name", required=True)
    p.add_argument("--url", required=True, help="URL pública del bot (ej. https://bot.example.com).")
    p.add_argument(
        "--secret",
        default=None,
        help="Valor del header X-Webhook-Secret (opcional, recomendado).",
    )

    p = sub.add_parser(
        "set-active",
        help="Activar una instancia: re-verifica estado, configura webhook y escribe config_bot.json.",
    )
    p.add_argument("--name", required=True)
    p.add_argument(
        "--config",
        default=None,
        help="Ruta al config_bot.json (default: el de la raíz del proyecto).",
    )
    return parser


def _map_app_error_to_exit(e: AppError) -> int:
    """Convierte un AppError en un exit code segun su codigo."""
    if e.code == ErrorCode.EVO_INSTANCE_NOT_LINKED:
        print(f"Precondición fallida: {e.detail}", file=sys.stderr)
        return EXIT_STATE_PRECONDITION
    if isinstance(e, ConfigError) or e.code in (
        ErrorCode.CFG_READ_FAILED,
        ErrorCode.CFG_WRITE_FAILED,
    ):
        print(f"Error de configuración: {e.detail}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    print(f"Error HTTP: {e.detail}", file=sys.stderr)
    return EXIT_HTTP_ERROR


def main(argv: Optional[List[str]] = None) -> int:
    """Punto de entrada. Retorna el exit code (no llama a sys.exit)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # `set-active` construye su propio admin dentro de la funcion (necesita
    # ademas ConfigManager y las env vars de webhook); los otros subcomandos
    # comparten un admin built-once.
    if args.command != "set-active":
        admin = _build_admin_from_env()
    else:
        admin = None  # type: ignore[assignment]

    try:
        if args.command == "list":
            return asyncio.run(_cmd_list(admin))
        if args.command == "create":
            return asyncio.run(_cmd_create(admin, name=args.name))
        if args.command == "qr":
            return asyncio.run(_cmd_qr(admin, name=args.name))
        if args.command == "state":
            return asyncio.run(_cmd_state(admin, name=args.name))
        if args.command == "set-webhook":
            return asyncio.run(
                _cmd_set_webhook(admin, name=args.name, url=args.url, secret=args.secret)
            )
        if args.command == "set-active":
            return asyncio.run(
                _cmd_set_active(name=args.name, config_path=args.config)
            )
    except AppError as e:
        return _map_app_error_to_exit(e)

    # argparse con `required=True` en subparsers garantiza que command exista;
    # este punto es inalcanzable.
    return EXIT_HTTP_ERROR


if __name__ == "__main__":
    sys.exit(main())
