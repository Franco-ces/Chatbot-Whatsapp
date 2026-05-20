# primera_instalacion.ps1

cd chatbotW

Write-Host "1. Levantando y construyendo contenedores desde cero..." -ForegroundColor Cyan
docker-compose up -d --build

Write-Host "2. Esperando 15 segundos para que Postgres y Evolution API se inicien correctamente..." -ForegroundColor Yellow
Start-Sleep -Seconds 15

Write-Host "3. Creando la instancia 'rag_bot' en la base de datos..." -ForegroundColor Cyan
try {
    Invoke-RestMethod -Uri "http://localhost:8080/instance/create" -Method Post -Headers @{"apikey"="franquitoGoat"; "Content-Type"="application/json"} -Body '{"instanceName": "rag_bot", "qrcode": true, "integration": "WHATSAPP-BAILEYS"}'
    Write-Host "Instancia creada con exito." -ForegroundColor Green
} catch {
    Write-Host "Error al crear la instancia. Es posible que Evolution API tarde mas en levantar. Revisa los logs." -ForegroundColor Red
    exit
}

Write-Host ""
Write-Host "================================================================="
Write-Host "PAUSA REQUERIDA: Vinculacion de WhatsApp"
Write-Host "Abri tu archivo conectar.html y escanea el QR con el celular."
Write-Host "================================================================="
Write-Host ""
Read-Host "Presiona ENTER unicamente cuando WhatsApp ya figure como conectado"

Write-Host "4. Configurando el Webhook para recibir los mensajes..." -ForegroundColor Cyan
try {
    Invoke-RestMethod -Uri "http://localhost:8080/webhook/set/rag_bot" -Method Post -Headers @{"apikey"="franquitoGoat"; "Content-Type"="application/json"} -Body '{"webhook": {"enabled": true, "url": "http://bot.local:5000/webhook", "byEvents": false, "base64": false, "events": ["MESSAGES_UPSERT"]}}'
    Write-Host "Webhook configurado con exito." -ForegroundColor Green
} catch {
    Write-Host "Error al configurar el webhook." -ForegroundColor Red
    exit
}

Write-Host ""
Write-Host "Todo listo. El bot ya esta operativo en esta maquina." -ForegroundColor Green

Read-Host "Presioná ENTER para salir..."