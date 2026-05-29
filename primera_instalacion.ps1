# primera_instalacion.ps1
# =============================================================================
# Primera Instalacion - Neuradocs (Windows)
# Configura containers, instancia de WhatsApp, QR y webhook automaticamente.
# =============================================================================

$ErrorActionPreference = "Stop"

# --- Configuracion (overrideable via env) --------------------------------
$INSTANCE_NAME = if ($env:INSTANCE_NAME) { $env:INSTANCE_NAME } else { "rag_bot" }
$EVO_URL = if ($env:EVO_URL) { $env:EVO_URL } else { "http://localhost:8080" }
$BOT_URL = if ($env:BOT_URL) { $env:BOT_URL } else { "http://bot.local:5000/webhook" }
$EVO_API_KEY = if ($env:EVO_API_KEY) { $env:EVO_API_KEY } else { "franquitoGoat" }

# --- Utils ---------------------------------------------------------------
function Log($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "[X] $msg" -ForegroundColor Red; exit 1 }

# --- Verificar prerequisitos ---------------------------------------------
Log "Verificando prerequisitos..."
$missing = @()
foreach ($cmd in @("docker", "curl", "openssl")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        $missing += $cmd
    }
}
if ($missing.Count -gt 0) {
    Err "Faltan: $($missing -join ', ')"
}
Ok "Prerequisitos OK"

# --- 1. Levantar containers ----------------------------------------------
Log "1/5 Levantando contenedores..."
Push-Location chatbotW
try {
    docker compose up -d --build
} finally {
    Pop-Location
}

# --- 2. Esperar Evolution API (poll, no sleep) ---------------------------
Log "2/5 Esperando Evolution API..."
$ready = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $null = Invoke-RestMethod -Uri "$EVO_URL/instance/fetchInstances" -Headers @{"apikey"=$EVO_API_KEY}
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) {
    Err "Evolution API no respondio en 60 segundos. Revisa: docker logs evolution_api"
}
Ok "Evolution API lista"

# --- 3. Crear instancia de WhatsApp --------------------------------------
Log "3/5 Creando instancia '$INSTANCE_NAME'..."
try {
    $body = @{
        instanceName = $INSTANCE_NAME
        qrcode = $true
        integration = "WHATSAPP-BAILEYS"
    } | ConvertTo-Json
    Invoke-RestMethod -Uri "$EVO_URL/instance/create" -Method Post `
        -Headers @{"apikey"=$EVO_API_KEY; "Content-Type"="application/json"} `
        -Body $body
    Ok "Instancia creada"
} catch {
    Err "No se pudo crear la instancia. Revisa: docker logs evolution_api"
}

# --- 4. Obtener QR y abrir en browser ------------------------------------
Log "4/5 Generando codigo QR..."

$qrBase64 = ""
for ($i = 1; $i -le 20; $i++) {
    try {
        $response = Invoke-RestMethod -Uri "$EVO_URL/instance/connect/$INSTANCE_NAME" `
            -Headers @{"apikey"=$EVO_API_KEY}

        # Intentar extraer base64 del QR (varia segun version)
        if ($response.base64 -and $response.base64.Length -gt 100) {
            $qrBase64 = ($response.base64 -split ",", 2)[1]
        } elseif ($response.qrcode.base64 -and $response.qrcode.base64.Length -gt 100) {
            $qrBase64 = ($response.qrcode.base64 -split ",", 2)[1]
        }

        if ($qrBase64) { break }
    } catch {}
    Start-Sleep -Seconds 2
}

if (-not $qrBase64) {
    Err "No se pudo obtener el codigo QR. Revisa: docker logs evolution_api"
}

# Generar HTML temporal con el QR
$qrHtml = "$env:TEMP\qr_whatsapp_$([System.IO.Path]::GetRandomFileName()).html"
@"
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
    <img src="data:image/png;base64,$qrBase64" alt="Codigo QR">
    <p>Abrilo en <strong>WhatsApp - Dispositivos vinculados - Vincular dispositivo</strong></p>
</body>
</html>
"@ | Out-File -FilePath $qrHtml -Encoding UTF8

Start-Process $qrHtml
Ok "QR abierto en el browser"

# --- 5. Esperar conexion de WhatsApp -------------------------------------
Log "5/5 Esperando que escanees el QR..."

$connected = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $state = Invoke-RestMethod -Uri "$EVO_URL/instance/connectionState/$INSTANCE_NAME" `
            -Headers @{"apikey"=$EVO_API_KEY}
        if ($state.state -eq "open") {
            $connected = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
}

if (-not $connected) {
    Err "Timeout - WhatsApp no se conecto en 60 segundos. Escanea el QR y volve a ejecutar."
}
Ok "WhatsApp conectado"

# --- 6. Configurar webhook -----------------------------------------------
Log "Configurando webhook..."

# Generar secret
$webhookSecret = (openssl rand -hex 32 2>$null).Trim()
if (-not $webhookSecret) {
    Err "openssl fallo al generar secret"
}

# Escribir a .env (idempotente)
$envFile = "..\.env"
if (Test-Path $envFile) {
    $content = Get-Content $envFile -Raw
    if ($content -match "WEBHOOK_SECRET=") {
        $content = $content -replace "WEBHOOK_SECRET=.*", "WEBHOOK_SECRET=$webhookSecret"
        Set-Content -Path $envFile -Value $content -NoNewline
    } else {
        Add-Content -Path $envFile -Value "`nWEBHOOK_SECRET=$webhookSecret"
    }
} else {
    "WEBHOOK_SECRET=$webhookSecret" | Out-File -FilePath $envFile -Encoding UTF8
}

# Verificar que se escribio
$envContent = Get-Content $envFile -Raw
if (-not $envContent.Contains("WEBHOOK_SECRET=$webhookSecret")) {
    Err "No se pudo guardar el secret en .env"
}

# Configurar webhook en Evolution API
try {
    $webhookBody = @{
        webhook = @{
            enabled = $true
            url = $BOT_URL
            byEvents = $false
            base64 = $false
            headers = @{ "X-Webhook-Secret" = $webhookSecret }
            events = @("MESSAGES_UPSERT")
        }
    } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Uri "$EVO_URL/webhook/set/$INSTANCE_NAME" -Method Post `
        -Headers @{"apikey"=$EVO_API_KEY; "Content-Type"="application/json"} `
        -Body $webhookBody
    Ok "Webhook configurado"
} catch {
    Err "No se pudo configurar el webhook"
}

# --- Limpieza ------------------------------------------------------------
Remove-Item -Path $qrHtml -ErrorAction SilentlyContinue

# --- Listo ---------------------------------------------------------------
Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  [OK] Bot operativo                                    " -ForegroundColor Green
Write-Host "  WhatsApp conectado y webhook configurado.              " -ForegroundColor Green
Write-Host "  Mandale un mensaje al numero de WhatsApp para probar. " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
