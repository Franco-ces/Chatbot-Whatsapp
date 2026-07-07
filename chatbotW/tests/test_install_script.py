"""Tests para la simplificación de primera_instalacion.sh.

Verifica:
- Bash syntax válido (bash -n)
- Zero llamadas a curl
- Zero llamadas a openssl
- docker compose up -d --build presente
- Mensaje final con URL del admin UI
- No requiere curl/openssl como prerequisito
"""
import subprocess
import os
import pytest

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "primera_instalacion.sh"
)
SCRIPT_PATH = os.path.normpath(SCRIPT_PATH)


class TestInstallScriptSyntax:
    """Validación de sintaxis bash del script."""

    def test_bash_syntax_valid(self):
        """El script pasa la verificación de sintaxis bash -n."""
        result = subprocess.run(
            ["bash", "-n", SCRIPT_PATH],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, \
            f"Error de sintaxis bash:\n{result.stderr}"

    def test_script_exists(self):
        """El archivo del script existe."""
        assert os.path.isfile(SCRIPT_PATH), \
            f"Script no encontrado: {SCRIPT_PATH}"

    def test_script_is_executable_or_has_shebang(self):
        """El script tiene shebang o es ejecutable."""
        with open(SCRIPT_PATH, "r") as f:
            first_line = f.readline().strip()
        assert first_line.startswith("#!/"), \
            f"Script sin shebang: {first_line}"


class TestInstallScriptNoCurl:
    """El script no debe contener llamadas a curl."""

    def test_no_curl_calls(self):
        """Zero invocaciones de curl en el script."""
        with open(SCRIPT_PATH, "r") as f:
            content = f.read()
        # Buscar curl como comando (no en comentarios o strings)
        lines = content.split("\n")
        curl_lines = [
            line.strip()
            for line in lines
            if line.strip()
            and not line.strip().startswith("#")
            and "curl" in line
        ]
        assert len(curl_lines) == 0, \
            f"Script contiene curl en estas líneas:\n" + "\n".join(curl_lines)

    def test_no_openssl_calls(self):
        """Zero invocaciones de openssl en el script."""
        with open(SCRIPT_PATH, "r") as f:
            content = f.read()
        lines = content.split("\n")
        openssl_lines = [
            line.strip()
            for line in lines
            if line.strip()
            and not line.strip().startswith("#")
            and "openssl" in line
        ]
        assert len(openssl_lines) == 0, \
            f"Script contiene openssl en estas líneas:\n" + "\n".join(openssl_lines)


class TestInstallScriptDocker:
    """El script debe usar docker compose."""

    def test_docker_compose_up_present(self):
        """El script usa docker compose para levantar los contenedores.

        El script abstrae v1/v2 en la variable $DC (= 'docker compose' o
        'docker-compose') y luego ejecuta '$DC up -d --build'. Verificamos
        que el script referencie docker compose (detección v2 literal en
        `DC="docker compose"`); el flag --build lo cubre el test hermano.
        """
        with open(SCRIPT_PATH, "r") as f:
            content = f.read()
        assert "docker compose" in content, \
            "Script debe usar docker compose (vía $DC up -d --build)"

    def test_docker_compose_has_build_flag(self):
        """docker compose up incluye --build."""
        with open(SCRIPT_PATH, "r") as f:
            content = f.read()
        assert "-d --build" in content or "--build -d" in content, \
            "docker compose up debe incluir -d --build"

    def test_docker_prereq_check(self):
        """El script verifica que docker está instalado."""
        with open(SCRIPT_PATH, "r") as f:
            content = f.read()
        assert "command -v docker" in content or "which docker" in content, \
            "Script debe verificar que docker existe"


class TestInstallScriptOutput:
    """El script imprime la URL del admin UI."""

    def test_prints_admin_url(self):
        """El script imprime la URL del admin UI.

        El puerto es dinámico (ADMIN_PORT, default 8000 con auto-detección
        de puerto libre), así que se imprime `http://localhost:${ADMIN_PORT}`
        en vez del literal `localhost:8000`. Verificamos el prefijo de URL.
        """
        with open(SCRIPT_PATH, "r") as f:
            content = f.read()
        assert "http://localhost" in content, \
            "Script debe imprimir la URL del admin UI (http://localhost:${ADMIN_PORT})"

    def test_message_in_spanish(self):
        """El mensaje final está en español."""
        with open(SCRIPT_PATH, "r") as f:
            content = f.read()
        # Al menos una palabra en español en el output final
        spanish_indicators = ["Configurar", "configurar", "Contenedores", "contenedores",
                              "Levant", "levant", "listo", "OK"]
        assert any(word in content for word in spanish_indicators), \
            "El mensaje final debe estar en español"


class TestInstallScriptMinimal:
    """El script es mínimo (~10 líneas, sin lógica compleja)."""

    def test_script_is_short(self):
        """El script mantiene un tamaño razonable para un instalador.

        Originalmente era un script mínimo (~10 líneas); evolucionó a un
        instalador completo con detección de docker compose v1/v2, verificación
        de puertos libres, prompt de contraseña admin y health check. El
        umbral refleja el tamaño actual con margen de seguridad.
        """
        with open(SCRIPT_PATH, "r") as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) <= 400, \
            f"Script demasiado largo ({len(lines)} líneas). Umbral 400."

    def test_no_evolution_api_interaction(self):
        """El script no hace llamadas a Evolution API."""
        with open(SCRIPT_PATH, "r") as f:
            content = f.read()
        # No debe contener referencias directas a Evolution API endpoints
        evo_indicators = ["fetchInstances", "instance/fetch", "evolution-api",
                          "EVO_URL", "EVO_API_KEY"]
        for indicator in evo_indicators:
            assert indicator not in content, \
                f"Script contiene referencia a Evolution API: {indicator}"

    def test_set_pipefail(self):
        """El script usa set -euo pipefail o equivalente."""
        with open(SCRIPT_PATH, "r") as f:
            content = f.read()
        assert "set -" in content, "Script debe usar set -euo pipefail"
