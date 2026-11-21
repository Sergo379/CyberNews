[CmdletBinding()]
param(
    [string]$DockerExe = 'docker'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$services = @('auth', 'collector', 'articles', 'community', 'moderation', 'notifications')
$marker = 'smoke_' + [Guid]::NewGuid().ToString('N')

function Invoke-Compose {
    & $DockerExe compose @args
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose command failed ($($args[0]), exit $LASTEXITCODE)."
    }
}

function Test-Assert([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-HttpCheck {
    param([string]$Url, [string]$RequestId, [int]$Status = 200)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10 `
            -Headers @{ 'X-Request-ID' = $RequestId }
    } catch {
        if ($Status -ne 200 -and $_.Exception.Response -and
            [int]$_.Exception.Response.StatusCode -eq $Status) { return }
        throw
    }
    Test-Assert ([int]$response.StatusCode -eq $Status) "Unexpected HTTP status at $Url."
    return $response
}

function Wait-Ready([scriptblock]$Check, [string]$Description) {
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    do {
        try {
            & $Check
            return
        } catch {
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "Timed out waiting for $Description. $($_.Exception.Message)"
            }
            Start-Sleep -Seconds 2
        }
    } while ($true)
}

function Invoke-PostgresCheck([string]$Phase) {
    $source = [IO.File]::ReadAllText((Join-Path $root 'tests/postgres-smoke.sh'))
    $source | & $DockerExe compose exec -T postgres bash -c 'tr -d \\015 | bash -s -- $1 $2' smoke $Phase $marker
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL check failed ($Phase, exit $LASTEXITCODE)."
    }
}

function Test-Backends {
    foreach ($service in $services) {
        $prefix = "$gateway/api/v1/$service"
        foreach ($endpoint in @('health', 'ready')) {
            $reply = Invoke-HttpCheck "$prefix/$endpoint" $marker
            $payload = $reply.Content | ConvertFrom-Json
            Test-Assert ($payload.service -ceq $service) "Gateway routed $service/$endpoint to the wrong backend."
            Test-Assert ([string]$reply.Headers['X-Request-ID'] -ceq $marker) "Missing request ID at $service/$endpoint."
            if ($endpoint -eq 'ready') {
                Test-Assert ($payload.status -eq 'ready' -and $payload.database -eq 'ok') "$service database is not ready."
            } else {
                Test-Assert ($payload.status -eq 'ok') "$service health check failed."
            }
        }
    }
}

function Test-GitSecrets($ComposeConfig) {
    $gitEnvFiles = @(& git ls-files --cached -- '.env' '.env.*' ':(glob)**/.env' ':(glob)**/.env.*')
    Test-Assert ($LASTEXITCODE -eq 0) 'Could not list staged environment files.'
    Test-Assert (@($gitEnvFiles | Where-Object { $_ -ne '.env.example' }).Count -eq 0) 'An environment file is tracked.'
    & git check-ignore -q -- .env
    Test-Assert ($LASTEXITCODE -eq 0) '.env must be ignored.'

    $secretValues = @(
        $ComposeConfig.services.postgres.environment.PSObject.Properties |
            Where-Object { $_.Name -like '*_PASSWORD' } | ForEach-Object { $_.Value }
    )
    $secretValues += $ComposeConfig.services.rabbitmq.environment.RABBITMQ_DEFAULT_PASS
    $secretValues += $ComposeConfig.services.auth.environment.JWT_SECRET
    $secretValues += $ComposeConfig.services.auth.environment.INTERNAL_AUTH_SECRET
    Test-Assert ($secretValues.Count -eq 10) 'Unexpected number of infrastructure and application secrets.'
    foreach ($value in $secretValues) {
        Test-Assert ($value.Length -ge 16) 'An infrastructure password is too short for this stack.'
    }
    Test-Assert (@($secretValues | Sort-Object -Unique).Count -eq 10) 'Secrets must be distinct.'
    $trackedSecrets = @($secretValues | & git grep --cached -l -F -f -)
    $grepStatus = $LASTEXITCODE
    Test-Assert ($grepStatus -eq 1 -and $trackedSecrets.Count -eq 0) 'Git index secret scan failed.'

    $candidates = @(& git -c core.quotePath=false ls-files --cached --others --exclude-standard)
    Test-Assert ($LASTEXITCODE -eq 0) 'Could not list repository files.'
    $secretPattern = '(?m)^-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----$|\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b'
    foreach ($path in $candidates) {
        $absolute = Join-Path $root $path
        if (Test-Path -LiteralPath $absolute -PathType Leaf) {
            $withLocalSecret = Select-String -LiteralPath $absolute -Pattern $secretValues -SimpleMatch -Quiet
            $withKeyOrToken = Select-String -LiteralPath $absolute -Pattern $secretPattern -Quiet
            Test-Assert (-not ($withLocalSecret -or $withKeyOrToken)) "Potential secret in $path."
        }
    }
    Write-Host 'PASS: Git index and candidate files contain no infrastructure passwords or private key/token signatures.'
}

Push-Location $root
try {
    $config = (Invoke-Compose config --format json | Out-String) | ConvertFrom-Json
    Test-GitSecrets $config

    $expectedPorts = @{ gateway = 8080; postgres = 5432; rabbitmq = 15672 }
    $published = @{}
    foreach ($component in $config.services.PSObject.Properties) {
        $ports = @($component.Value.ports | Where-Object { $_ })
        if ($expectedPorts.ContainsKey($component.Name)) {
            Test-Assert ($ports.Count -eq 1) "Expected one published port for $($component.Name)."
            $target = $expectedPorts[$component.Name]
            $port = $ports[0]
            Test-Assert ($port.host_ip -eq '127.0.0.1' -and $port.target -eq $target -and
                $port.protocol -eq 'tcp') "Unexpected bind for $($component.Name)."
            $published[$component.Name] = [int]$port.published
            $boundAddress = (Invoke-Compose port $component.Name $target | Out-String).Trim()
            Test-Assert ($boundAddress -eq "127.0.0.1:$($port.published)") "Docker returned an unexpected address for $($component.Name)."
        } else {
            Test-Assert ($ports.Count -eq 0) "Unexpected published ports for $($component.Name)."
        }
    }
    Test-Assert (@($published.Values | Sort-Object -Unique).Count -eq 3) 'Published TCP ports conflict.'
    Write-Host 'PASS: gateway, PostgreSQL and RabbitMQ Management use distinct loopback ports.'

    $gateway = "http://127.0.0.1:$($published.gateway)"
    $rabbit = "http://127.0.0.1:$($published.rabbitmq)"
    $gatewayReply = (Invoke-HttpCheck "$gateway/health" $marker).Content | ConvertFrom-Json
    Test-Assert ($gatewayReply.service -eq 'gateway' -and $gatewayReply.status -eq 'ok') 'Gateway health check failed.'
    Invoke-HttpCheck "$gateway/api/v1/unknown/health" $marker 404
    Invoke-HttpCheck "$gateway/api/v1/auth/unknown" $marker 404
    Wait-Ready { Test-Backends } 'six backends and their databases'
    $schema = (Invoke-HttpCheck "$gateway/api/v1/auth/openapi.json?smoke=true" $marker).Content | ConvertFrom-Json
    Test-Assert ($schema.servers[0].url -eq '/api/v1/auth' -and $schema.paths.'/ready') 'OpenAPI is not routed through the gateway.'
    $swagger = (Invoke-HttpCheck "$gateway/api/v1/auth/docs" $marker).Content
    Test-Assert ($swagger -match '\./openapi\.json') 'Swagger UI does not use the routed schema.'
    foreach ($service in $services) {
        $uid = (Invoke-Compose exec -T $service id -u | Out-String).Trim()
        Test-Assert ($uid -match '^[1-9][0-9]*$') "$service does not run as a non-root user."
    }
    $requestLogs = Invoke-Compose logs --no-color --no-log-prefix --tail 100 auth
    $entry = $requestLogs | ForEach-Object { $_ | ConvertFrom-Json -ErrorAction SilentlyContinue } |
        Where-Object { $_.request_id -eq $marker -and $_.status -eq 200 } | Select-Object -First 1
    Test-Assert ($entry.timestamp -and $entry.service -eq 'auth' -and $entry.level -and $entry.message) 'Missing correlated JSON request log.'
    Write-Host 'PASS: gateway routing, six FastAPI health/readiness responses, non-root users and JSON request logging.'

    Invoke-PostgresCheck isolation
    Write-Host 'PASS: PostgreSQL service credentials, UTF-8 and cross-database access restrictions.'

    try {
        Invoke-PostgresCheck write
        try {
            Invoke-Compose stop postgres
            foreach ($service in $services) {
                $base = "$gateway/api/v1/$service"
                $null = Invoke-HttpCheck "$base/health" $marker
                Invoke-HttpCheck "$base/ready" $marker 503
            }
        } finally {
            Invoke-Compose start postgres
            Wait-Ready { Test-Backends } 'PostgreSQL restart and backend readiness'
        }
        Invoke-PostgresCheck read
    } finally {
        Invoke-PostgresCheck cleanup
    }
    Write-Host 'PASS: /ready returns 503 during the PostgreSQL stop, /health stays live and test data survives restart.'

    $rabbitEnv = $config.services.rabbitmq.environment
    $credentials = $rabbitEnv.RABBITMQ_DEFAULT_USER + ':' + $rabbitEnv.RABBITMQ_DEFAULT_PASS
    $auth = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($credentials))
    $headers = @{ Authorization = "Basic $auth" }
    $vhost = [Uri]::EscapeDataString($rabbitEnv.RABBITMQ_DEFAULT_VHOST)
    $queue = "$rabbit/api/queues/$vhost/$marker"

    Wait-Ready {
        Invoke-Compose exec -T rabbitmq rabbitmq-diagnostics -q check_port_connectivity | Out-Null
        Invoke-WebRequest -Uri $rabbit -UseBasicParsing -TimeoutSec 10 | Out-Null
        Invoke-RestMethod -Uri "$rabbit/api/overview" -Headers $headers -TimeoutSec 10 | Out-Null
    } 'RabbitMQ listeners and authenticated Management API'
    Invoke-RestMethod -Method Put -Uri $queue -Headers $headers -TimeoutSec 10 `
        -ContentType 'application/json' -Body '{"durable":true,"auto_delete":false,"arguments":{}}' | Out-Null
    try {
        Invoke-Compose restart rabbitmq
        Wait-Ready {
            $result = Invoke-RestMethod -Uri $queue -Headers $headers -TimeoutSec 10
            Test-Assert ($result.name -eq $marker -and $result.durable) 'Durable RabbitMQ test queue did not survive restart.'
        } 'RabbitMQ restart and durable queue'
    } finally {
        Invoke-RestMethod -Method Delete -Uri $queue -Headers $headers -TimeoutSec 10 | Out-Null
    }
    Write-Host 'PASS: RabbitMQ listeners, authenticated Management API and durable queue across restart.'

    $containerIds = @(Invoke-Compose ps -q)
    Test-Assert ($containerIds.Count -eq ($services.Count + 3)) 'Unexpected number of running containers.'
    Wait-Ready {
        $statuses = @(& $DockerExe inspect --format '{{.State.Health.Status}}' @containerIds)
        Test-Assert ($LASTEXITCODE -eq 0 -and $statuses.Count -eq $containerIds.Count -and
            @($statuses | Where-Object { $_ -ne 'healthy' }).Count -eq 0) 'Some Docker health checks are pending.'
    } 'healthy status for all nine containers'
    Invoke-Compose ps
    Write-Host 'All CyberNews infrastructure smoke checks passed.'
} finally {
    Pop-Location
}
