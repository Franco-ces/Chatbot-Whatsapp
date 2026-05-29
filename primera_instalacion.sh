#!/bin/bash
set -euo pipefail

# =============================================================================
# Primera Instalacion - Neuradocs
# Configura containers, instancia de WhatsApp, QR y webhook automaticamente.
# =============================================================================

# --- Configuracion (overrideable via env) --------------------------------
INSTANCE_NAME="${INSTANCE_NAME:-rag_bot}"
EVO_URL="${EVO_URL:-http://localhost:8080}"
BOT_URL="${BOT_URL:-http://bot.local:5000/webhook}"
EVO_API_KEY="${EVO_API_KEY:-franquitoGoat}"

# --- Colores -------------------------------------------------------------
CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${CYAN}$1${NC}"; }
ok()   { echo -e "${GREEN}[OK] $1${NC}"; }
warn() { echo -e "${YELLOW}[!] $1${NC}"; }
err()  { echo -e "${RED}[X] $1${NC}"; exit 1; }

# --- Cleanup en error ----------------------------------------------------
cleanup() {
    local line=$1
    if [[ -n "$line" && "$line" -gt 0 ]]; then
        warn "Error en linea $line. Estado parcial - revisa los logs."
    fi
}
trap cleanup ERR

# --- Verificar prerequisitos ---------------------------------------------
log "Verificando prerequisitos..."
for cmd in docker curl openssl jq; do
    if ! command -v "$cmd" &>/dev/null; then
        err "Falta: $cmd\n  Instalalo con: sudo apt install $cmd"
    fi
done
ok "Prerequisitos OK"

# --- 1. Levantar containers ----------------------------------------------
log "1/5 Levantando contenedores..."
docker compose up -d --build

# --- 2. Esperar Evolution API (poll, no sleep) ---------------------------
log "2/5 Esperando Evolution API..."
for i in {1..30}; do
    if curl -s -f "$EVO_URL/instance/fetchInstances" \
         -H "apikey: $EVO_API_KEY" &>/dev/null; then
        break
    fi
    if [[ $i -eq 30 ]]; then
        err "Evolution API no respondio en 60 segundos.\n  Revisa: docker logs evolution_api"
    fi
    sleep 2
done
ok "Evolution API lista"

# --- 3. Crear instancia de WhatsApp --------------------------------------
log "3/5 Creando instancia '$INSTANCE_NAME'..."
curl -s -f -X POST "$EVO_URL/instance/create" \
     -H "apikey: $EVO_API_KEY" \
     -H "Content-Type: application/json" \
     -d "{\"instanceName\": \"$INSTANCE_NAME\", \"qrcode\": true, \"integration\": \"WHATSAPP-BAILEYS\"}" \
     > /dev/null || err "No se pudo crear la instancia.\n  Revisa: docker logs evolution_api"
ok "Instancia creada"

# --- 4. Obtener QR y abrir en browser ------------------------------------
log "4/5 Generando codigo QR..."

QR_BASE64=""
for i in {1..20}; do
    QR_RESPONSE=$(curl -s "$EVO_URL/instance/connect/$INSTANCE_NAME" \
        -H "apikey: $EVO_API_KEY")

    # Intentar extraer base64 del QR (varia segun version de Evolution API)
    QR_BASE64=$(echo "$QR_RESPONSE" | jq -r '.base64 // .qrcode.base64 // empty' 2>/dev/null | cut -d',' -f2)

    if [[ -n "$QR_BASE64" && "$QR_BASE64" != "null" && ${#QR_BASE64} -gt 100 ]]; then
        break
    fi
    sleep 2
done

if [[ -z "$QR_BASE64" || "$QR_BASE64" == "null" ]]; then
    err "No se pudo obtener el codigo QR.\n  Revisa: docker logs evolution_api"
fi

# Generar HTML temporal con el QR
QR_HTML="/tmp/qr_whatsapp_$$.html"
cat > "$QR_HTML" << HTMLEOF
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Vincular WhatsApp</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; background: #f4f4f9; }
        img { max-width: 350px; border: 2px solid #ccc; border-radius: 10px; padding: 15px; background: white; }
        p { color: #666; font-size: 15px; }
    </style>
</head>
<body>
    <h2>Vincular Bot de WhatsApp</h2>
    <img src="data:image/png;base64,$QR_BASE64" alt="Codigo QR">
    <p>Abrilo en <strong>WhatsApp - Dispositivos vinculados - Vincular dispositivo</strong></p>
</body>
</html>
HTMLEOF

# Abrir en browser (funciona en Linux, macOS, Windows)
if xdg-open "$QR_HTML" 2>/dev/null || open "$QR_HTML" 2>/dev/null || start "$QR_HTML" 2>/dev/null; then
    ok "QR abierto en el browser"
else
    warn "No se pudo abrir el browser automaticamente.\n  Abri manualmente: $QR_HTML"
fi

# --- 5. Esperar conexion de WhatsApp -------------------------------------
log "5/5 Esperando que escanees el QR..."

CONNECTED=false
for i in {1..30}; do
    STATUS=$(curl -s "$EVO_URL/instance/connectionState/$INSTANCE_NAME" \
        -H "apikey: $EVO_API_KEY" | jq -r '.state // empty' 2>/dev/null)

    if [[ "$STATUS" == "open" ]]; then
        CONNECTED=true
        break
    fi
    sleep 2
done

if [[ "$CONNECTED" != "true" ]]; then
    err "Timeout - WhatsApp no se conecto en 60 segundos.\n  Escanea el QR y volve a ejecutar el script."
fi
ok "WhatsApp conectado"

# --- 6. Configurar webhook -----------------------------------------------
log "Configurando webhook..."

# Generar secret (idempotente - no duplica si ya existe)
WEBHOOK_SECRET=$(openssl rand -hex 32) || err "openssl fallo al generar secret"

ENV_FILE="../.env"
if grep -q "^WEBHOOK_SECRET=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s/^WEBHOOK_SECRET=.*/WEBHOOK_SECRET=${WEBHOOK_SECRET}/" "$ENV_FILE"
else
    echo "WEBHOOK_SECRET=${WEBHOOK_SECRET}" >> "$ENV_FILE"
fi

# Verificar que se escribio
if ! grep -q "WEBHOOK_SECRET=${WEBHOOK_SECRET}" "$ENV_FILE" 2>/dev/null; then
    err "No se pudo guardar el secret en .env"
fi

# Configurar webhook en Evolution API
curl -s -f -X POST "$EVO_URL/webhook/set/$INSTANCE_NAME" \
     -H "apikey: $EVO_API_KEY" \
     -H "Content-Type: application/json" \
     -d "{\"webhook\": {\"enabled\": true, \"url\": \"$BOT_URL\", \"byEvents\": false, \"base64\": false, \"headers\": {\"X-Webhook-Secret\": \"${WEBHOOK_SECRET}\"}, \"events\": [\"MESSAGES_UPSERT\"]}}" \
     > /dev/null || err "No se pudo configurar el webhook"

ok "Webhook configurado"

# --- Limpieza ------------------------------------------------------------
rm -f "$QR_HTML"

# --- Listo ---------------------------------------------------------------
echo ""
echo -e "${GREEN}========================================================${NC}"
echo -e "${GREEN}  [OK] Bot operativo                                    ${NC}"
echo -e "${GREEN}  WhatsApp conectado y webhook configurado.              ${NC}"
echo -e "${GREEN}  Mandale un mensaje al numero de WhatsApp para probar. ${NC}"
echo -e "${GREEN}========================================================${NC}"
