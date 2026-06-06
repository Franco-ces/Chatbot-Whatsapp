#!/bin/bash
# =============================================================================
# Instalacion — Chatbot WhatsApp (Gemini + RAG + Evolution API)
# =============================================================================
# Este script levanta todos los servicios via Docker Compose:
#   - Bot webhook (FastAPI, puerto 5000)
#   - Admin UI (FastAPI, puerto 8000)
#   - Evolution API (puerto 8080)
#   - PostgreSQL
#   - Redis
#
# Uso: ./primera_instalacion.sh [--verbose]
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colores ANSI
# ---------------------------------------------------------------------------
readonly C_RED='\033[0;31m'
readonly C_GREEN='\033[0;32m'
readonly C_YELLOW='\033[0;33m'
readonly C_CYAN='\033[0;36m'
readonly C_BOLD='\033[1m'
readonly C_RESET='\033[0m'

# ---------------------------------------------------------------------------
# Utilidades de impresion
# ---------------------------------------------------------------------------
info()    { echo -e "${C_CYAN}[INFO]${C_RESET}  $*"; }
ok()      { echo -e "${C_GREEN}[OK]${C_RESET}    $*"; }
warn()    { echo -e "${C_YELLOW}[WARN]${C_RESET}  $*"; }
fail()    { echo -e "${C_RED}[ERROR]${C_RESET} $*"; }
header()  { echo -e "\n${C_BOLD}${C_CYAN}=== $* ===${C_RESET}"; }

# ---------------------------------------------------------------------------
# Error trap — muestra la linea donde fallo
# ---------------------------------------------------------------------------
on_error() {
    local exit_code=$?
    fail "El script fallo en la linea ${BASH_LINENO[0]} (codigo: $exit_code)"
    exit "$exit_code"
}
trap on_error ERR

# ---------------------------------------------------------------------------
# Verificar que docker esta instalado
# ---------------------------------------------------------------------------
check_docker() {
    header "Verificando Docker"
    if ! command -v docker &>/dev/null; then
        fail "Docker no esta instalado."
        echo "  Instalelo con: sudo apt install docker.io"
        echo "  O descargue Docker Desktop: https://docs.docker.com/get-docker/"
        exit 1
    fi
    ok "Docker instalado: $(docker --version 2>/dev/null || echo '(version desconocida)')"

    # Verificar que el daemon esta corriendo
    if ! docker info &>/dev/null; then
        fail "Docker no esta ejecutandose."
        echo "  Abra Docker Desktop o ejecute 'sudo systemctl start docker'"
        echo "  y vuelva a intentar."
        exit 1
    fi
    ok "Daemon Docker activo."
}

# ---------------------------------------------------------------------------
# Detectar docker compose (v2) o docker-compose (v1)
# ---------------------------------------------------------------------------
detect_compose() {
    header "Detectando Docker Compose"

    # Primero: docker compose (plugin v2)
    if docker compose version &>/dev/null; then
        DC="docker compose"
        ok "Usando: docker compose (plugin v2)"
        return 0
    fi

    # Segundo: docker-compose standalone (v1)
    if command -v docker-compose &>/dev/null && docker-compose version &>/dev/null; then
        DC="docker-compose"
        ok "Usando: docker-compose (standalone v1)"
        return 0
    fi

    fail "No se encontro Docker Compose."
    echo "  Instale Docker Compose v2: https://docs.docker.com/compose/install/"
    exit 1
}

# ---------------------------------------------------------------------------
# Verificar arquitectura ARM
# ---------------------------------------------------------------------------
check_architecture() {
    header "Verificando arquitectura"
    local arch
    arch="$(uname -m)"
    info "Arquitectura detectada: $arch"

    case "$arch" in
        *arm*|*aarch64*)
            warn "Se detecto una arquitectura ARM."
            warn "Algunos servicios pueden tener limitaciones de compatibilidad."
            echo ""
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Verificar puertos disponibles (5000, 8000, 8080)
# ---------------------------------------------------------------------------
detect_ports() {
    header "Detectando puertos disponibles"

    # Puertos objetivo
    local bot_target=5000
    local admin_target=8000
    local evo_target=8080

    # Rango de busqueda: desde el puerto objetivo hasta +10
    local range_end=5010

    # Buscar puerto para el bot
    BOT_PORT=$(_find_free_port "$bot_target" $((bot_target + 10)))
    BOT_PORT="${BOT_PORT:-$bot_target}"
    export BOT_PORT

    # Buscar puerto para admin UI
    ADMIN_PORT=$(_find_free_port "$admin_target" $((admin_target + 10)))
    ADMIN_PORT="${ADMIN_PORT:-$admin_target}"
    export ADMIN_PORT

    # Buscar puerto para Evolution API
    EVO_PORT=$(_find_free_port "$evo_target" $((evo_target + 10)))
    EVO_PORT="${EVO_PORT:-$evo_target}"
    export EVO_PORT

    # Construir URL del webhook del bot
    export BOT_URL="http://bot.local:${BOT_PORT}/webhook"

    info "Puertos asignados:"
    echo "  Bot webhook:    $BOT_PORT"
    echo "  Admin UI:       $ADMIN_PORT"
    echo "  Evolution API:  $EVO_PORT"
}

# Helper: encuentra el primer puerto libre desde start hasta end
_find_free_port() {
    local start=$1
    local end=$2
    local port=$start

    while [ "$port" -le "$end" ]; do
        if ! ss -tlnH "sport = :$port" 2>/dev/null | grep -q ":${port}"; then
            # Tambien probar con lsof como fallback
            if ! command -v lsof &>/dev/null || ! lsof -i ":$port" &>/dev/null; then
                echo "$port"
                return 0
            fi
        fi
        port=$((port + 1))
    done

    # No se encontro puerto libre en el rango
    warn "No se encontro un puerto libre en el rango $start-$end para el puerto base $start"
    echo "$start"
}

# ---------------------------------------------------------------------------
# Verificar que .env existe
# ---------------------------------------------------------------------------
check_env() {
    header "Verificando configuracion"

    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            warn "No se encontro el archivo .env"
            info "Copiando .env.example como .env..."
            cp .env.example .env
            ok "Archivo .env creado desde .env.example"
            echo ""
            info "Puede configurar la clave API de Gemini desde la Admin UI"
            info "en http://localhost:${ADMIN_PORT} despues de iniciar los servicios."
        else
            fail "No se encontro .env ni .env.example"
            exit 1
        fi
    else
        ok "Archivo .env encontrado"
    fi
}
start_services() {
    header "Levantando contenedores"
    info "Ejecutando: $DC up -d --build"
    echo ""

    $DC up -d --build

    ok "Contenedores enviados a ejecutarse."
}

# ---------------------------------------------------------------------------
# Health check — esperar a que los contenedores esten listos
# ---------------------------------------------------------------------------
wait_for_healthy() {
    header "Esperando que los servicios esten listos"

    local max_wait=60
    local elapsed=0
    local interval=3
    local all_healthy=false

    while [ "$elapsed" -lt "$max_wait" ]; do
        # Obtener estado de los contenedores
        local ps_output
        ps_output="$($DC ps 2>/dev/null || true)"

        # Contar contenedores que estan "Up" o "healthy"
        local total
        local running
        total=$(echo "$ps_output" | grep -c "Up\|healthy" || true)

        # Mostrar progreso
        local dots=""
        local i=0
        while [ "$i" -lt "$((elapsed / interval))" ]; do
            dots="${dots}."
            i=$((i + 1))
        done

        if [ "$total" -ge 3 ]; then
            echo ""
            ok "Todos los contenedores estan activos (${elapsed}s)."
            all_healthy=true
            break
        fi

        echo -ne "\r  ${C_CYAN}Esperando${C_RESET} ${dots} (${elapsed}s / ${max_wait}s) "
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    echo ""

    if [ "$all_healthy" = false ]; then
        warn "Algunos contenedores pueden tardar mas en iniciar."
        warn "Revise los logs con: $DC logs -f"
    fi
}

# ---------------------------------------------------------------------------
# Resumen final
# ---------------------------------------------------------------------------
print_summary() {
    echo ""
    header "Instalacion completada"
    echo ""
    echo "  ${C_BOLD}Puertos:${C_RESET}"
    echo "    Bot webhook:    ${C_GREEN}${BOT_PORT}${C_RESET}"
    echo "    Admin UI:       ${C_GREEN}${ADMIN_PORT}${C_RESET}"
    echo "    Evolution API:  ${C_GREEN}${EVO_PORT}${C_RESET}"
    echo ""
    echo "  ${C_BOLD}URLs:${C_RESET}"
    echo "    Admin UI:  ${C_CYAN}http://localhost:${ADMIN_PORT}${C_RESET}"
    echo "    Bot API:   ${C_CYAN}${BOT_URL}${C_RESET}"
    echo ""
    echo "  ${C_BOLD}Siguiente paso:${C_RESET}"
    echo "    1. Abra la Admin UI en el navegador"
    echo "    2. Configure la clave API de Gemini desde la interfaz"
    echo "    3. Suba los PDFs que el bot debe consultar"
    echo ""
    echo "  ${C_BOLD}Comandos utiles:${C_RESET}"
    echo "    Ver logs:        $DC logs -f"
    echo "    Detener todo:    $DC down"
    echo "    Reiniciar:       $DC restart"
    echo ""
    echo -en "${C_YELLOW}Presione Enter para continuar...${C_RESET}"
    read -r
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    # Verificar si se pidio modo verbose
    [[ "${1:-}" == "--verbose" ]] && set -x

    echo -e "\n${C_BOLD}${C_CYAN}============================================${C_RESET}"
    echo -e "${C_BOLD}${C_CYAN}  Instalacion — Chatbot WhatsApp${C_RESET}"
    echo -e "${C_BOLD}${C_CYAN}============================================${C_RESET}\n"

    # Ir al directorio del script
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cd "$SCRIPT_DIR/chatbotW"

    # Ejecutar pasos
    check_docker
    detect_compose
    check_architecture
    detect_ports
    check_env
    start_services
    wait_for_healthy
    print_summary
}

main "$@"
