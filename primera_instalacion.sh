#!/bin/bash

# Nos aseguramos de entrar a la carpeta del proyecto donde está el docker-compose.yml
cd "$(dirname "$0")/chatbotW"

# Definimos algunos colores para que la consola se lea mejor
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # Sin color

echo -e "${CYAN}1. Levantando y construyendo contenedores desde cero...${NC}"
# Usamos el comando moderno con espacio que sí funciona con tu Python 3.12:
docker compose up -d --build

echo -e "${YELLOW}2. Esperando 15 segundos para que Postgres y Evolution API se inicien correctamente...${NC}"
sleep 15

echo -e "${CYAN}3. Creando la instancia 'rag_bot' en la base de datos...${NC}"
if curl -s -f -X POST "http://localhost:8080/instance/create" \
     -H "apikey: franquitoGoat" \
     -H "Content-Type: application/json" \
     -d '{"instanceName": "rag_bot", "qrcode": true, "integration": "WHATSAPP-BAILEYS"}' > /dev/null; then
    echo -e "${GREEN}Instancia creada con exito.${NC}"
else
    echo -e "${RED}Error al crear la instancia. Revisa que Evolution API haya levantado bien.${NC}"
    exit 1
fi

echo ""
echo "================================================================="
echo "PAUSA REQUERIDA: Vinculación de WhatsApp"
echo "Abri tu archivo conectar.html y escanea el QR con el celular."
echo "================================================================="
echo ""
read -p "Presiona ENTER únicamente cuando WhatsApp ya figure como conectado"

echo -e "${CYAN}4. Configurando el Webhook para recibir los mensajes...${NC}"
if curl -s -f -X POST "http://localhost:8080/webhook/set/rag_bot" \
     -H "apikey: franquitoGoat" \
     -H "Content-Type: application/json" \
     -d '{"webhook": {"enabled": true, "url": "http://bot.local:5000/webhook", "byEvents": false, "base64": false, "events": ["MESSAGES_UPSERT"]}}' > /dev/null; then
    echo -e "${GREEN}Webhook configurado con éxito.${NC}"
else
    echo -e "${RED}Error al configurar el webhook.${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Todo listo. El bot ya está operativo en esta máquina.${NC}"

read -p "Presioná ENTER para salir..."