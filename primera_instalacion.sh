#!/bin/bash
# =============================================================================
# Primera Instalación — Chatbot WhatsApp
# Simplificado: el backend auto-genera WEBHOOK_SECRET, la UI maneja instancias.
# =============================================================================
set -euo pipefail

# Ir al directorio del docker-compose.yml
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/chatbotW"

# Verificar que docker está instalado
command -v docker &>/dev/null || { echo "Falta docker. Instalalo: sudo apt install docker.io" >&2; exit 1; }

# Levantar contenedores
docker compose up -d --build

echo ""
echo -e "\033[0;32m[OK] Contenedores levantados. Abrí http://localhost:8000 para configurar.\033[0m"
