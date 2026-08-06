param(
    [Parameter(Position = 0)]
    [ValidateSet('up','down','status')]
    [string]$Command = 'up'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$esContainer = 'hanati-es'
$qdrantContainer = 'hanati-qdrant'
$esPort = '9200'
$qdrantPort = '6333'
$fluentBitLog = Join-Path $env:TEMP 'hanati-fluentbit.log'

function Need-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'docker is not installed. Install Docker Desktop and run again.'
    }
    try {
        docker info | Out-Null
    } catch {
        throw 'docker daemon is not running. Start Docker Desktop and run again.'
    }
}

function Get-DockerContainers {
    try {
        return @(docker ps --format '{{.Names}}' 2>$null)
    } catch {
        return @()
    }
}

function Get-DockerContainersAll {
    try {
        return @(docker ps -a --format '{{.Names}}' 2>$null)
    } catch {
        return @()
    }
}

function Resolve-FluentBitPath {
    $cmd = Get-Command fluent-bit -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $cmd = Get-Command fluent-bit.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        "$env:ProgramFiles\Fluent Bit\bin\fluent-bit.exe",
        "$env:ProgramFiles(x86)\Fluent Bit\bin\fluent-bit.exe",
        "$env:LOCALAPPDATA\Programs\Fluent Bit\bin\fluent-bit.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\FluentBit.FluentBit_Microsoft.Winget.Source_8wekyb3d8bbwe\bin\fluent-bit.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Install-FluentBit {
    if (Resolve-FluentBitPath) {
        Write-Host '[fluent-bit] already installed'
        return
    }

    Write-Host '[fluent-bit] installing..'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id FluentBit.FluentBit -e --source winget
        Start-Sleep -Seconds 5
        return
    }

    if (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install fluent-bit -y
        Start-Sleep -Seconds 5
        return
    }

    Write-Warning '[fluent-bit] not installed and no package manager was found. Skipping fluent-bit startup.'
}

function Start-FluentBit {
    $running = Get-Process -Name 'fluent-bit' -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host '[fluent-bit] already running'
        return
    }

    $fluentBitPath = Resolve-FluentBitPath
    if (-not $fluentBitPath) {
        Write-Warning '[fluent-bit] executable not found after install attempt. Skipping fluent-bit startup.'
        Write-Host 'Install Fluent Bit manually from https://fluentbit.io/ or run: winget install --id FluentBit.FluentBit -e --source winget'
        return
    }

    Write-Host '[fluent-bit] starting..'
    $workingDir = Join-Path $repoRoot 'fluentbit'
    Start-Process -FilePath $fluentBitPath -ArgumentList '-c .\fluent-bit.conf' -WorkingDirectory $workingDir -WindowStyle Hidden
    Start-Sleep -Seconds 2
    Write-Host "[fluent-bit] started (log: $fluentBitLog)"
}

function Stop-FluentBit {
    Write-Host '[fluent-bit] stopping..'
    Get-Process -Name 'fluent-bit' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

function Start-Elasticsearch {
    Need-Docker
    $running = Get-DockerContainers
    if ($running -contains $esContainer) {
        Write-Host '[elasticsearch] already running'
        return
    }

    $existing = Get-DockerContainersAll
    if ($existing -contains $esContainer) {
        Write-Host '[elasticsearch] restarting existing container'
        docker start $esContainer | Out-Null
    } else {
        Write-Host '[elasticsearch] creating container (image will be downloaded if needed)'
        docker run -d --name $esContainer -p "${esPort}:9200" -e 'discovery.type=single-node' -e 'xpack.security.enabled=false' docker.elastic.co/elasticsearch/elasticsearch:8.15.0 | Out-Null
    }

    Write-Host -NoNewline '[elasticsearch] waiting for startup'
    for ($i = 0; $i -lt 60; $i++) {
        try {
            Invoke-WebRequest -Uri "http://localhost:$esPort" -UseBasicParsing -TimeoutSec 2 | Out-Null
            Write-Host ' done'
            return
        } catch {
            Write-Host -NoNewline '.'
            Start-Sleep -Seconds 2
        }
    }
    Write-Host ' timed out'
}

function Start-Qdrant {
    Need-Docker
    $running = Get-DockerContainers
    if ($running -contains $qdrantContainer) {
        Write-Host '[qdrant] already running'
        return
    }

    $existing = Get-DockerContainersAll
    if ($existing -contains $qdrantContainer) {
        Write-Host '[qdrant] restarting existing container'
        docker start $qdrantContainer | Out-Null
    } else {
        Write-Host '[qdrant] creating container (image will be downloaded if needed)'
        docker run -d --name $qdrantContainer -p "${qdrantPort}:6333" qdrant/qdrant | Out-Null
    }

    Write-Host -NoNewline '[qdrant] waiting for startup'
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-WebRequest -Uri "http://localhost:$qdrantPort/healthz" -UseBasicParsing -TimeoutSec 2 | Out-Null
            Write-Host ' done'
            return
        } catch {
            Write-Host -NoNewline '.'
            Start-Sleep -Seconds 1
        }
    }
    Write-Host ' timed out'
}

function Stop-Containers {
    Write-Host '[elasticsearch] stopping container..'
    docker stop $esContainer 2>$null | Out-Null
    Write-Host '[qdrant] stopping container..'
    docker stop $qdrantContainer 2>$null | Out-Null
}

function Print-EnvHint {
    @"

Set these environment variables to use the local infrastructure:

  `$env:QDRANT_URL = 'http://localhost:$qdrantPort'
  `$env:ELASTICSEARCH_URL = 'http://localhost:$esPort'
  `$env:ELASTICSEARCH_VERIFY_CERTS = 'false'
  `$env:CASE_SEARCHER_BACKEND = 'hybrid'   # qdrant or elastic

Initial data seeding:
  python -m qdrant.seed
  python -m elastic.seed_cases

Use TESTING.md for the fluentbit -> backend pipeline check.
"@
}

function Get-Status {
    if (Get-Process -Name 'fluent-bit' -ErrorAction SilentlyContinue) {
        Write-Host 'fluent-bit: running'
    } else {
        Write-Host 'fluent-bit: stopped'
    }

    if (Get-Command docker -ErrorAction SilentlyContinue) {
        $running = Get-DockerContainers
        if ($running -contains $esContainer) { Write-Host 'elasticsearch: running' } else { Write-Host 'elasticsearch: stopped' }
        if ($running -contains $qdrantContainer) { Write-Host 'qdrant: running' } else { Write-Host 'qdrant: stopped' }
    } else {
        Write-Host 'elasticsearch: docker not available'
        Write-Host 'qdrant: docker not available'
    }
}

switch ($Command) {
    'up' {
        try {
            Install-FluentBit
            Start-Elasticsearch
            Start-Qdrant
            Start-FluentBit
            Print-EnvHint
        } catch {
            Write-Error $_
            exit 1
        }
    }
    'down' {
        Stop-FluentBit
        Stop-Containers
    }
    'status' {
        Get-Status
    }
}
