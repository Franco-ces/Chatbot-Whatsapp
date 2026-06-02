#!/bin/bash
# =============================================================================
# Primera Instalacion - Neuradocs
# Bootstrap de un clone limpio: orquesta containers, instancia de WhatsApp,
# QR y webhook. Toda interaccion con Evolution API esta delegada a la CLI
# Python (`python -m src`), que es la unica autorizada a hablar con el
# endpoint externo. Bash solo maneja: prereqs, .env, containers, y polling
# de readiness (porque el bot container no esta vivo al inicio del script).
# =============================================================================
set -Eeuo pipefail

# --- Config (overrideable via env) -----------------------------------------
INSTANCE_NAME="${EVOLUTION_INSTANCE_NAME:-rag_bot}"
EVO_URL="${EVOLUTION_API_URL:-http://localhost:8080}"
EVO_API_KEY="${EVOLUTION_API_KEY:-franquitoGoat}"
BOT_URL="${BOT_URL:-http://bot.local:5000/webhook}"

# --- Colores + log helpers ------------------------------------------------
C='\033[0;36m'; G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'
log() { echo -e "${C}$1${N}"; }
ok()  { echo -e "${G}[OK] $1${N}"; }
wrn() { echo -e "${Y}[!] $1${N}"; }
err() { echo -e "${R}[X] $1${N}" >&2; exit 1; }
trap 'wrn "Error en linea $1. Estado parcial - revisa los logs."' ERR

# --- Prereqs --------------------------------------------------------------
log "Verificando prerequisitos..."
for c in docker curl openssl; do
    command -v "$c" &>/dev/null || err "Falta: $c. Instalalo con: sudo apt install $c"
done
ok "Prereqs OK"

# --- WEBHOOK_SECRET en .env (idempotente) ---------------------------------
S=$(openssl rand -hex 32) || err "openssl fallo al generar secret"
if [[ -f .env ]]; then
    if grep -q "^WEBHOOK_SECRET=" .env; then
        sed -i "s|^WEBHOOK_SECRET=.*|WEBHOOK_SECRET=$S|" .env
    else
        echo "WEBHOOK_SECRET=$S" >> .env
    fi
fi

# --- 1. Containers --------------------------------------------------------
log "1/4 Levantando contenedores..."
docker compose up -d --build

# --- 2. Esperar Evolution API (curl directo, no delega: bot aun no esta vivo)
log "2/4 Esperando Evolution API..."
for i in {1..30}; do
    curl -s -f "$EVO_URL/instance/fetchInstances" -H "apikey: $EVO_API_KEY" &>/dev/null && break
    [[ $i -eq 30 ]] && err "Evolution API no respondio en 60s. Revisa: docker logs evolution_api"
    sleep 2
done
ok "Evolution API lista"

# --- 3. Crear instancia (delegado al CLI: muestra QR + abre browser) ------
log "3/4 Creando instancia '$INSTANCE_NAME'..."
docker compose exec -T whatsapp-bot python -m src create --name "$INSTANCE_NAME" \
    || err "No se pudo crear la instancia."

# --- 4. Esperar estado=open (delegado al CLI, bash parsea JSON) ----------
log "4/4 Esperando que escanees el QR..."
for i in {1..30}; do
    STATE=$(docker compose exec -T whatsapp-bot python -m src state --name "$INSTANCE_NAME" 2>/dev/null) || STATE=""
    [[ "$STATE" == *'"state": "open"'* ]] && break
    [[ $i -eq 30 ]] && err "Timeout - WhatsApp no se conecto. Escaneá el QR y volvé a correr."
    sleep 2
done
ok "WhatsApp conectado"

# --- 5. Webhook (delegado al CLI) ----------------------------------------
log "Configurando webhook..."
docker compose exec -T whatsapp-bot python -m src set-webhook \
    --name "$INSTANCE_NAME" --url "$BOT_URL" --secret "$S" \
    || err "No se pudo configurar el webhook."
ok "Webhook configurado"

echo ""
echo -e "${G}[OK] Bot operativo. Mandale un mensaje al numero de WhatsApp para probar.${N}"
