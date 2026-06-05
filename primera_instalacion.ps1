# =============================================================================
# Primera Instalación — Chatbot WhatsApp (PowerShell)
# Simplificado: el backend auto-genera WEBHOOK_SECRET, la UI maneja instancias.
# =============================================================================
$ErrorActionPreference = "Stop"

# Ir al directorio del docker-compose.yml
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$ScriptDir\chatbotW"

# Verificar que docker está instalado
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Falta docker. Instalalo desde: https://docs.docker.com/desktop/install/windows-install/" -ForegroundColor Red
    exit 1
}

# Modo verbose
if ($args -contains "--verbose") { $VerbosePreference = "Continue" }

# Levantar contenedores
docker compose up -d --build

Write-Host ""
Write-Host "[OK] Contenedores levantados. Abrí http://localhost:8000 para configurar." -ForegroundColor Green
