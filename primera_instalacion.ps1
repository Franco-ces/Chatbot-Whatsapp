# =============================================================================
# Instalacion — Chatbot WhatsApp (PowerShell)
# Backend auto-genera WEBHOOK_SECRET, la UI maneja instancias.
# =============================================================================
$ErrorActionPreference = "Stop"

# --- Funciones auxiliares ---------------------------------------------------

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK]   $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[AVISO] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Test-Port {
    param([int]$Port)
    try {
        $conn = [System.Net.Sockets.TcpClient]::new()
        $conn.Connect("127.0.0.1", $Port)
        $conn.Close()
        return $true
    } catch {
        return $false
    }
}

function Find-FreePort {
    param([int]$Start, [int]$End)
    for ($p = $Start; $p -le $End; $p++) {
        if (-not (Test-Port $p)) { return $p }
    }
    return $null
}

# --- Inicio -----------------------------------------------------------------

# Modo verbose
if ($args -contains "--verbose") { $VerbosePreference = "Continue" }

# Guardar directorio original para restaurar al salir
$OriginalLocation = Get-Location

try {
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "  Instalacion — Chatbot WhatsApp" -ForegroundColor Cyan
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host ""

    # --- 1. Verificar Docker instalado ---------------------------------------
    Write-Info "Verificando instalacion de Docker..."
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Err "Docker no esta instalado. Instale Docker Desktop desde:"
        Write-Err "  https://docs.docker.com/desktop/install/windows-install/"
        exit 1
    }
    Write-Ok "Docker encontrado."

    # --- 2. Verificar daemon Docker ejecutandose -----------------------------
    Write-Info "Verificando que el daemon de Docker este ejecutandose..."
    try {
        $null = docker info 2>&1
    } catch {
        Write-Err "Docker no esta ejecutandose. Abra Docker Desktop y vuelva a intentar."
        exit 1
    }
    Write-Ok "Daemon de Docker activo."

    # --- 3. Detectar arquitectura ARM ----------------------------------------
    Write-Info "Detectando arquitectura del sistema..."
    $is64Bit = [System.Environment]::Is64BitOperatingSystem
    $arch = if ($is64Bit) { "x64" } else { "x86" }
    # Verificacion adicional para ARM en Windows (WMI)
    try {
        $cpuInfo = (Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop).Name
        if ($cpuInfo -match "ARM|Qualcomm|Snapdragon") {
            $arch = "ARM"
        }
    } catch {
        # Si WMI no esta disponible, mantener la deteccion por Is64Bit
    }
    if ($arch -eq "ARM") {
        Write-Warn "Se detecto una arquitectura ARM. Algunos servicios pueden tener limitaciones de compatibilidad."
    } else {
        Write-Ok "Arquitectura: $arch"
    }

    # --- 4. Detectar comando docker compose ----------------------------------
    Write-Info "Buscando comando docker compose..."
    $ComposeCmd = $null

    # Intentar docker compose (plugin)
    try {
        $null = docker compose version 2>&1
        $ComposeCmd = "docker compose"
    } catch {
        # No disponible
    }

    # Intentar docker-compose (binario independiente)
    if (-not $ComposeCmd) {
        try {
            $null = docker-compose version 2>&1
            $ComposeCmd = "docker-compose"
        } catch {
            # No disponible
        }
    }

    if (-not $ComposeCmd) {
        Write-Err "No se encontro 'docker compose' ni 'docker-compose'."
        Write-Err "Instale Docker Compose: https://docs.docker.com/compose/install/"
        exit 1
    }
    Write-Ok "Usando: $ComposeCmd"

    # --- 5. Detectar puertos disponibles --------------------------------------
    Write-Info "Verificando disponibilidad de puertos..."

    $BotPort = Find-FreePort -Start 5000 -End 5010
    if ($null -eq $BotPort) {
        Write-Err "No se encontro un puerto disponible para el bot (5000-5010)."
        exit 1
    }

    $AdminPort = Find-FreePort -Start 8000 -End 8010
    if ($null -eq $AdminPort) {
        Write-Err "No se encontro un puerto disponible para la admin UI (8000-8010)."
        exit 1
    }

    $EvoPort = Find-FreePort -Start 8080 -End 8090
    if ($null -eq $EvoPort) {
        Write-Err "No se encontro un puerto disponible para Evolution API (8080-8090)."
        exit 1
    }

    # Mostrar resultados de puertos
    $PortsOk = $true
    if ($BotPort -ne 5000) {
        Write-Warn "Puerto 5000 ocupado. Bot asignado a puerto $BotPort"
        $PortsOk = $false
    } else {
        Write-Ok "Puerto BOT: 5000"
    }

    if ($AdminPort -ne 8000) {
        Write-Warn "Puerto 8000 ocupado. Admin UI asignada a puerto $AdminPort"
        $PortsOk = $false
    } else {
        Write-Ok "Puerto ADMIN: 8000"
    }

    if ($EvoPort -ne 8080) {
        Write-Warn "Puerto 8080 ocupado. Evolution API asignada a puerto $EvoPort"
        $PortsOk = $false
    } else {
        Write-Ok "Puerto EVO: 8080"
    }

    if (-not $PortsOk) {
        Write-Warn "Algunos puertos fueron redirigidos. Se usaran las variables de entorno."
    }

    # Establecer variables de entorno para docker compose
    $env:BOT_PORT = $BotPort.ToString()
    $env:ADMIN_PORT = $AdminPort.ToString()
    $env:EVO_PORT = $EvoPort.ToString()
    $env:BOT_URL = "http://bot.local:${BotPort}/webhook"

    # --- 6. Verificar que .env existe -----------------------------------------
    Write-Info "Verificando configuracion..."
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $EnvFile = Join-Path $ScriptDir "chatbotW\.env"
    $EnvExample = Join-Path $ScriptDir "chatbotW\.env.example"

    if (-not (Test-Path $EnvFile)) {
        if (Test-Path $EnvExample) {
            Write-Warn "No se encontro el archivo .env"
            Write-Info "Copiando .env.example como .env..."
            Copy-Item -Path $EnvExample -Destination $EnvFile
            Write-Ok "Archivo .env creado desde .env.example"
            Write-Info "Puede configurar la clave API de Gemini desde la Admin UI"
            Write-Info "en http://localhost:$AdminPort despues de iniciar los servicios."
        } else {
            Write-Err "No se encontro .env ni .env.example"
            exit 1
        }
    } else {
        Write-Ok "Archivo .env encontrado"
    }

    # --- 7. Ir al directorio del proyecto ------------------------------------
    $ComposeDir = Join-Path $ScriptDir "chatbotW"
    if (-not (Test-Path (Join-Path $ComposeDir "docker-compose.yml"))) {
        Write-Err "No se encontro docker-compose.yml en: $ComposeDir"
        exit 1
    }
    Push-Location $ComposeDir
    Write-Info "Directorio de trabajo: $(Get-Location)"

    # --- 8. Construir y levantar contenedores ---------------------------------
    Write-Info "Construyendo e iniciando contenedores..."
    $composeArgs = "up -d --build"
    if ($VerbosePreference -eq "Continue") {
        $composeArgs += " --verbose"
    }
    $composeCmdLine = "$ComposeCmd $composeArgs"
    Write-Info "Ejecutando: $composeCmdLine"
    Invoke-Expression $composeCmdLine

    if ($LASTEXITCODE -ne 0) {
        Write-Err "Fallo al levantar los contenedores (codigo de salida: $LASTEXITCODE)."
        Pop-Location
        exit 1
    }
    Write-Ok "Contenedores levantados."

    # --- 9. Health check: esperar que los contenedores esten sanos -------------
    Write-Info "Esperando que los contenedores esten listos (maximo 60 segundos)..."
    $MaxWait = 60
    $Elapsed = 0
    $Interval = 3
    $AllHealthy = $false

    while ($Elapsed -lt $MaxWait) {
        Start-Sleep -Seconds $Interval
        $Elapsed += $Interval

        try {
            $psOutput = Invoke-Expression "$ComposeCmd ps --format json" 2>&1
        } catch {
            $psOutput = ""
        }

        # Verificar que al menos todos los contenedores esten "Up"
        $containers = @()
        if ($psOutput -is [array]) {
            $containers = $psOutput
        } elseif ($psOutput) {
            $containers = @($psOutput)
        }

        $upCount = 0
        foreach ($line in $containers) {
            if ($line -match '"State":"running"') {
                $upCount++
            } elseif ($line -match '"State":') {
                # Si tiene State pero no es running, aun no esta listo
            } elseif ($line -match 'Up|healthy|running') {
                $upCount++
            }
        }

        $progress = [math]::Min(([math]::Floor($Elapsed / $MaxWait * 100)), 100)
        $dots = "." * ([math]::Floor($Elapsed / $Interval) % 10 + 1)
        Write-Host -NoNewline "`r  Progreso: ${progress}%  Esperando${dots}  " -ForegroundColor Yellow

        if ($upCount -ge 3) {
            $AllHealthy = $true
            break
        }
    }

    Write-Host ""  # Salto de linea despues del progreso

    if ($AllHealthy) {
        Write-Ok "Todos los contenedores estan ejecutandose."
    } else {
        Write-Warn "Algunos contenedores pueden no estar completamente listos."
        Write-Info "Verifique el estado con: $ComposeCmd ps"
    }

    # --- 10. Resumen final -----------------------------------------------------
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor Green
    Write-Host "  Instalacion completada" -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Puertos en uso:" -ForegroundColor Cyan
    Write-Host "    - Bot (webhook):    $BotPort" -ForegroundColor White
    Write-Host "    - Admin UI:         $AdminPort" -ForegroundColor White
    Write-Host "    - Evolution API:    $EvoPort" -ForegroundColor White
    Write-Host ""
    Write-Host "  Admin UI:  http://localhost:$AdminPort" -ForegroundColor Cyan
    Write-Host "  Bot URL:   http://localhost:$BotPort" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Siguiente paso:" -ForegroundColor Yellow
    Write-Host "    1. Abra http://localhost:$AdminPort" -ForegroundColor White
    Write-Host "    2. Cargue su clave de API de Gemini desde la interfaz." -ForegroundColor White
    Write-Host "    3. Envie un mensaje de WhatsApp al bot para probar." -ForegroundColor White
    Write-Host ""

} catch {
    Write-Err "Ocurrio un error inesperado: $_"
    Write-Err "Detalles: $($_.Exception.Message)"
    exit 1
} finally {
    # Restaurar directorio original
    Pop-Location -ErrorAction SilentlyContinue
    Set-Location $OriginalLocation -ErrorAction SilentlyContinue
}

# Presionar Enter para continuar
Write-Host ""
Read-Host "Presione Enter para continuar..."
