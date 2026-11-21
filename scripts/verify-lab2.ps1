[CmdletBinding()]
param(
    [string]$DockerExe = 'docker'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$backends = @('auth', 'collector', 'articles', 'community', 'moderation', 'notifications')
$components = $backends + @('gateway', 'postgres', 'rabbitmq')
$marker = 'smoke_' + [Guid]::NewGuid().ToString('N')

function Assert-Check([bool]$Condition, [string]$Description) {
    if (-not $Condition) { throw $Description }
}

function Read-Compose {
    $ErrorActionPreference = 'Continue'
    & $DockerExe compose @args 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose check failed ($($args[0])). Check Docker Desktop and local configuration." }
}

function Read-Http([string]$Path, [int]$Status = 200, [string]$Media = 'application/json') {
    try {
        $response = Invoke-WebRequest -Uri "$origin$Path" -UseBasicParsing -TimeoutSec 12 -MaximumRedirection 0
    } catch {
        $httpResponse = $_.Exception.Response
        if ($httpResponse -and $Status -ne 200 -and [int]$httpResponse.StatusCode -eq $Status) { return }
        throw "GET $Path failed (expected HTTP $Status)."
    }
    Assert-Check ([int]$response.StatusCode -eq $Status) "GET $Path returned an unexpected status."
    Assert-Check (([string]$response.Headers['Content-Type']).StartsWith($Media)) "GET $Path returned unexpected content."
    return $response
}

function Read-Database([string]$Phase) {
    $ErrorActionPreference = 'Continue'
    $source = [IO.File]::ReadAllText((Join-Path $root 'tests/postgres-smoke.sh'))
    $source | & $DockerExe compose exec -T postgres bash -c 'tr -d \\015 | bash -s -- $1 $2' audit $Phase $marker 2>$null
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL read-only check failed ($Phase)." }
}

function Find-RequestLog([string]$Service, [string]$RequestId) {
    $logs = Read-Compose logs --no-color --no-log-prefix --tail 160 $Service
    $record = $logs | Where-Object { $_ -like "*$RequestId*" } | ForEach-Object {
        $_ | ConvertFrom-Json -ErrorAction SilentlyContinue
    } | Where-Object { $_.request_id -eq $RequestId -and $_.status -eq 200 } | Select-Object -First 1
    Assert-Check ($record.timestamp -and $record.service -eq $Service -and $record.level -and $record.message) "Missing correlated JSON log for $Service."
}

Push-Location $root
try {
    Assert-Check ([bool](Get-Command $DockerExe -ErrorAction SilentlyContinue)) 'Docker was not found.'
    foreach ($path in @('compose.yaml', '.env.example', 'gateway/default.conf.template', 'gateway/frontend-headers.conf',
            'frontend/index.html', 'frontend/admin/index.html', 'infrastructure/postgres/10-initialize.sh',
            'infrastructure/rabbitmq/rabbitmq.conf')) {
        Assert-Check (Test-Path -LiteralPath $path -PathType Leaf) "Missing file $path."
    }
    foreach ($service in $backends) {
        foreach ($path in @('Dockerfile', 'requirements.txt', 'alembic.ini', 'app/config.py', 'app/main.py')) {
            Assert-Check (Test-Path -LiteralPath "services/$service/$path" -PathType Leaf) "Missing file services/$service/$path."
        }
        Assert-Check ([bool](Get-ChildItem -LiteralPath "services/$service/alembic/versions" -Filter '*.py' -File)) "No migrations for $service."
    }
    Read-Compose version --short | Out-Null
    Read-Compose config --quiet
    $running = @(Read-Compose ps --format '{{.Service}}|{{.State}}|{{.Health}}')
    Assert-Check ($running.Count -eq $components.Count) 'Expected nine Compose containers.'
    foreach ($component in $components) {
        Assert-Check ($running -contains "$component|running|healthy") "$component is missing or unhealthy."
        Write-Host "PASS: $component running and healthy"
    }
    $portMap = @{ gateway = 8080; postgres = 5432; rabbitmq = 15672 }
    $ports = @{}
    foreach ($component in $components) {
        $container = (Read-Compose ps -q $component | Out-String).Trim()
        $bindings = & $DockerExe inspect --format '{{json .HostConfig.PortBindings}}' $container 2>$null
        Assert-Check ($LASTEXITCODE -eq 0) "Could not inspect ports for $component."
        $published = $bindings | ConvertFrom-Json
        if ($portMap.ContainsKey($component)) {
            Assert-Check (@($published.PSObject.Properties).Count -eq 1) "Unexpected ports for $component."
            $key = "$($portMap[$component])/tcp"
            $bind = @($published.$key)
            Assert-Check ($bind.Count -eq 1 -and $bind[0].HostIp -eq '127.0.0.1') "$component must bind to IPv4 loopback."
            $address = (Read-Compose port $component $portMap[$component] | Out-String).Trim()
            Assert-Check ($address -match '^127\.0\.0\.1:\d+$') "Unexpected active address for $component."
            $ports[$component] = $address
        } else {
            Assert-Check (-not $published -or @($published.PSObject.Properties).Count -eq 0) "$component exposes an external port."
        }
    }
    Assert-Check (@($ports.Values | Sort-Object -Unique).Count -eq 3) 'Published ports are not distinct.'
    $origin = "http://$($ports.gateway)"
    $health = (Read-Http '/health').Content | ConvertFrom-Json
    Assert-Check ($health.service -eq 'gateway' -and $health.status -eq 'ok') 'Invalid Gateway health payload.'
    Read-Compose exec -T gateway nginx -t
    foreach ($page in @('/', '/admin/')) {
        $response = Read-Http $page 200 'text/html'
        Assert-Check ($response.Content -match '/js/app\.js' -and $response.Headers['Content-Security-Policy'] -and
            [string]$response.Headers['X-Content-Type-Options'] -eq 'nosniff') "Frontend security headers or assets missing at $page."
    }
    $operations = @{
        auth = '/register'; collector = '/sources'; articles = '/categories'
        community = '/bookmarks'; moderation = '/reports'; notifications = '/subscriptions'
    }
    $privatePaths = @{
        auth = '/me'; collector = '/status'; articles = '/admin/articles'
        community = '/bookmarks'; moderation = '/reports'; notifications = '/unread-count'
    }
    foreach ($service in $backends) {
        $prefix = "/api/v1/$service"
        $live = (Read-Http "$prefix/health").Content | ConvertFrom-Json
        $ready = (Read-Http "$prefix/ready").Content | ConvertFrom-Json
        Assert-Check ($live.service -eq $service -and $live.status -eq 'ok') "$service returned invalid health."
        Assert-Check ($ready.service -eq $service -and $ready.status -eq 'ready' -and $ready.database -eq 'ok') "$service is not ready."
        $docs = Read-Http "$prefix/docs" 200 'text/html'
        $schema = (Read-Http "$prefix/openapi.json").Content | ConvertFrom-Json
        $paths = $schema.paths.PSObject.Properties.Name
        Assert-Check ($docs.Content -match '\./openapi\.json' -and $schema.openapi -and
            $schema.servers[0].url -eq $prefix -and $paths -contains $operations[$service] -and
            -not @($paths | Where-Object { $_ -match '^/internal(?:/|$)' }).Count) "$service OpenAPI contract or Swagger route is invalid."
        Read-Http ($prefix + $privatePaths[$service]) 401
        Read-Http "$prefix/internal/v1/health" 404

        $requestId = "$marker-$service"
        $reply = Invoke-WebRequest -Uri "$origin$prefix/health" -UseBasicParsing -TimeoutSec 12 -Headers @{ 'X-Request-ID' = $requestId }
        Assert-Check ([string]$reply.Headers['X-Request-ID'] -ceq $requestId) "$service did not preserve X-Request-ID."
        Find-RequestLog $service $requestId
        Find-RequestLog gateway $requestId
        $uid = (Read-Compose exec -T $service id -u | Out-String).Trim()
        Assert-Check ($uid -match '^[1-9]\d*$') "$service must run as non-root."
        $revision = (Read-Compose exec -T $service alembic current --check-heads | Out-String).Trim()
        Assert-Check ([bool]$revision) "Missing revision for $service."
        Write-Host "PASS: $service health, readiness, Swagger, OpenAPI, permissions, JSON logs and Alembic ($revision)"
    }
    Read-Http '/internal/v1/health' 404
    Read-Http '/api/v1/unknown/health' 404
    $catalog = (Read-Http '/api/v1/articles/?limit=1').Content | ConvertFrom-Json
    $categories = @(((Read-Http '/api/v1/articles/categories').Content | ConvertFrom-Json) | Where-Object { $_.id })
    Assert-Check ($catalog.total -gt 0 -and $catalog.items[0].id -and $categories.Count -gt 0) 'Public catalog or categories are empty.'
    Write-Host "PASS: frontend, Gateway, $($catalog.total) published articles and $($categories.Count) categories"

    Read-Compose exec -T rabbitmq rabbitmq-diagnostics -q check_running | Out-Null
    Read-Compose exec -T rabbitmq rabbitmq-diagnostics -q check_port_connectivity | Out-Null
    Write-Host 'PASS: RabbitMQ node and listeners'
    Read-Database isolation
    Read-Database snapshot
    Write-Host 'PASS: Lab 2 read-only verification completed.'
} catch {
    Write-Error "FAIL: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
} finally {
    Pop-Location
}
