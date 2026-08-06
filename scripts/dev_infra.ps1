param(
    [Parameter(Position = 0)]
    [ValidateSet('up','down','status')]
    [string]$Command = 'up'
)

$ErrorActionPreference = 'Stop'
# 저장소 루트를 기준으로 fluentbit 설정 파일 위치를 찾는다.
$repoRoot = Split-Path -Parent $PSScriptRoot
# Docker 컨테이너 이름과 포트 설정
$esContainer = 'hanati-es'
$qdrantContainer = 'hanati-qdrant'
$esPort = '9200'
$qdrantPort = '6333'
$esVolume = 'hanati-es-data'
$qdrantVolume = 'hanati-qdrant-data'
# Fluent Bit 로그 파일 경로
$fluentBitLog = Join-Path $env:TEMP 'hanati-fluentbit.log'

# Docker가 설치되어 있고 실행 중인지 확인한다.
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

# 현재 실행 중인 Docker 컨테이너 이름 목록을 조회한다.
function Get-DockerContainers {
    try {
        return @(docker ps --format '{{.Names}}' 2>$null)
    } catch {
        return @()
    }
}

# 정지된 컨테이너까지 포함한 Docker 컨테이너 이름 목록을 조회한다.
function Get-DockerContainersAll {
    try {
        return @(docker ps -a --format '{{.Names}}' 2>$null)
    } catch {
        return @()
    }
}

# 지정한 Docker 이미지가 로컬에 이미 있는지 확인한다.
function Test-DockerImage {
    param([string]$ImageName)

    try {
        $images = @(docker image ls --format '{{.Repository}}:{{.Tag}}' 2>$null)
        return $images -contains $ImageName
    } catch {
        return $false
    }
}

# Fluent Bit 실행 파일이 어디에 설치되어 있는지 탐색한다.
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

# Fluent Bit이 없으면 설치하고, 이미 있으면 재설치를 막는다.
function Install-FluentBit {
    $resolvedPath = Resolve-FluentBitPath
    if ($resolvedPath) {
        Write-Host "[fluent-bit] already installed at $resolvedPath"
        return
    }

    Write-Host '[fluent-bit] installing..'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id FluentBit.FluentBit -e --source winget
        Start-Sleep -Seconds 5
        $resolvedPath = Resolve-FluentBitPath
        if ($resolvedPath) {
            Write-Host "[fluent-bit] installed successfully at $resolvedPath"
        } else {
            Write-Warning '[fluent-bit] install command completed, but executable was not found yet.'
        }
        return
    }

    if (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install fluent-bit -y
        Start-Sleep -Seconds 5
        $resolvedPath = Resolve-FluentBitPath
        if ($resolvedPath) {
            Write-Host "[fluent-bit] installed successfully at $resolvedPath"
        } else {
            Write-Warning '[fluent-bit] install command completed, but executable was not found yet.'
        }
        return
    }

    Write-Warning '[fluent-bit] not installed and no package manager was found. Skipping fluent-bit startup.'
}

# Fluent Bit 프로세스를 실행한다.
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

# 실행 중인 Fluent Bit 프로세스를 종료한다.
function Stop-FluentBit {
    Write-Host '[fluent-bit] stopping..'
    Get-Process -Name 'fluent-bit' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

# Elasticsearch 컨테이너를 준비하고 기동한다.
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
        $image = 'docker.elastic.co/elasticsearch/elasticsearch:8.15.0'
        if (-not (Test-DockerImage -ImageName $image)) {
            Write-Host "[elasticsearch] pulling image $image"
            docker pull $image | Out-Null
        }

        Write-Host '[elasticsearch] creating container (first run only)'
        # 이름 있는 볼륨에 데이터 마운트 - 컨테이너를 지우고 새로 만들어도
        # 시딩한 사례가 안 날아가게 한다.
        docker volume create $esVolume | Out-Null
        docker run -d --name $esContainer -p "${esPort}:9200" -e 'discovery.type=single-node' -e 'xpack.security.enabled=false' -v "${esVolume}:/usr/share/elasticsearch/data" $image | Out-Null
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

# Qdrant 컨테이너를 준비하고 기동한다.
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
        $image = 'qdrant/qdrant'
        if (-not (Test-DockerImage -ImageName $image)) {
            Write-Host "[qdrant] pulling image $image"
            docker pull $image | Out-Null
        }

        Write-Host '[qdrant] creating container (first run only)'
        # 이름 있는 볼륨에 데이터 마운트 - 컨테이너를 지우고 새로 만들어도
        # 시딩한 사례가 안 날아가게 한다.
        docker volume create $qdrantVolume | Out-Null
        docker run -d --name $qdrantContainer -p "${qdrantPort}:6333" -v "${qdrantVolume}:/qdrant/storage" $image | Out-Null
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

# Elasticsearch와 Qdrant 컨테이너를 모두 정지한다.
function Seed-Knowledge {
    $venvPython = Join-Path $repoRoot 'venv\Scripts\python.exe'
    $pythonBin = if (Test-Path $venvPython) { $venvPython } else { 'python' }

    Write-Host '[seed] seeding incident case data (Qdrant + Elasticsearch)..'
    Push-Location $repoRoot
    try {
        & $pythonBin -m qdrant.seed
        if ($LASTEXITCODE -ne 0) { throw "qdrant.seed exited $LASTEXITCODE" }
        & $pythonBin -m elastic.seed_cases
        if ($LASTEXITCODE -ne 0) { throw "elastic.seed_cases exited $LASTEXITCODE" }
        & $pythonBin scripts\seed_incident_knowledge.py
        if ($LASTEXITCODE -ne 0) { throw "seed_incident_knowledge.py exited $LASTEXITCODE" }
    } catch {
        Write-Warning "[seed] failed - run manually after checking venv/deps: python -m qdrant.seed && python -m elastic.seed_cases && python scripts/seed_incident_knowledge.py"
    } finally {
        Pop-Location
    }
}

function Stop-Containers {
    Write-Host '[elasticsearch] stopping container..'
    docker stop $esContainer 2>$null | Out-Null
    Write-Host '[qdrant] stopping container..'
    docker stop $qdrantContainer 2>$null | Out-Null
}

# 앱 실행 시 필요한 환경변수 안내를 출력한다.
function Print-EnvHint {
    @"

Set these environment variables to use the local infrastructure:

  `$env:QDRANT_URL = 'http://localhost:$qdrantPort'
  `$env:ELASTICSEARCH_URL = 'http://localhost:$esPort'
  `$env:ELASTICSEARCH_VERIFY_CERTS = 'false'
  `$env:CASE_SEARCHER_BACKEND = 'hybrid'   # qdrant or elastic

Incident case data was auto-seeded above (check the [seed] log line if it failed).
To re-seed:
  python -m qdrant.seed
  python -m elastic.seed_cases
  python scripts/seed_incident_knowledge.py

Use TESTING.md for the fluentbit -> backend pipeline check.
"@
}

# 현재 상태를 요약해서 출력한다.
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

# 실행 명령에 따라 전체 흐름을 제어한다.
switch ($Command) {
    # up: 인프라를 설치/기동하고 환경변수 안내까지 출력한다.
    'up' {
        try {
            Install-FluentBit
            Start-Elasticsearch
            Start-Qdrant
            Start-FluentBit
            Seed-Knowledge
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
