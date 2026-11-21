[CmdletBinding()]
param(
    [string]$PythonExe = 'python',
    [string]$DockerExe = 'docker'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$project = 'cybernews-stage3-' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
$compose = @('compose', '-f', 'compose.yaml', '-f', 'tests/stage2.compose.yaml',
    '-f', 'tests/stage3.compose.yaml', '-p', $project)
$random = [Security.Cryptography.RandomNumberGenerator]::Create()

function New-Secret {
    $bytes = New-Object byte[] 32
    $random.GetBytes($bytes)
    return [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
}

function Invoke-TestCompose {
    & $DockerExe @compose @args
    if ($LASTEXITCODE -ne 0) { throw "Test Compose operation failed ($($args[0]), exit $LASTEXITCODE)." }
}

$override = @{
    POSTGRES_USER = 'cybernews_test_admin'
    ACCESS_TOKEN_TTL_SECONDS = '900'
    ADMIN_SESSION_TTL_SECONDS = '900'
    CYBERNEWS_TEST_PROJECT = $project
    CYBERNEWS_TEST_DOCKER = $DockerExe
    CYBERNEWS_TEST_SUPER_EMAIL = 'stage3-admin@example.com'
    CYBERNEWS_TEST_SUPER_PASSWORD = (New-Secret)
    CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD = (New-Secret)
}
foreach ($key in @('POSTGRES_PASSWORD', 'AUTH_DB_PASSWORD', 'COLLECTOR_DB_PASSWORD', 'ARTICLE_DB_PASSWORD',
        'COMMUNITY_DB_PASSWORD', 'MODERATION_DB_PASSWORD', 'NOTIFICATION_DB_PASSWORD',
        'RABBITMQ_PASSWORD', 'JWT_SECRET', 'INTERNAL_AUTH_SECRET', 'ARTICLE_IMPORT_SECRET')) {
    $override[$key] = New-Secret
}
$previous = @{}
$started = $false

Push-Location $root
try {
    foreach ($key in $override.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $override[$key], 'Process')
    }
    $previous['CYBERNEWS_TEST_BASE_URL'] = $env:CYBERNEWS_TEST_BASE_URL
    Invoke-TestCompose config --quiet
    $started = $true
    Invoke-TestCompose up -d --build --wait --wait-timeout 100 postgres auth articles collector gateway
    $address = (Invoke-TestCompose port gateway 8080 | Out-String).Trim()
    if ($address -notmatch '^127\.0\.0\.1:[0-9]+$') { throw 'Unexpected test Gateway bind address.' }
    $env:CYBERNEWS_TEST_BASE_URL = "http://$address"
    $data = @{
        email = $override.CYBERNEWS_TEST_SUPER_EMAIL
        nickname = 'stage3-root'
        password = $override.CYBERNEWS_TEST_SUPER_PASSWORD
        admin_password = $override.CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD
    } | ConvertTo-Json -Compress
    Invoke-TestCompose cp tests/bootstrap_cli.py auth:/tmp/stage3-bootstrap-test.py
    $data | & $DockerExe @compose exec -T auth python /tmp/stage3-bootstrap-test.py
    if ($LASTEXITCODE -ne 0) { throw 'Test administrator bootstrap failed.' }

    & $PythonExe -m pytest -q --tb=short tests/test_stage3_unit.py tests/test_stage3_api.py
    if ($LASTEXITCODE -ne 0) { throw 'Stage 3 pytest suite failed.' }
    Write-Host 'PASS: Stage 3 fixture and Gateway checks.'
} finally {
    try {
        if ($started) { Invoke-TestCompose down }
    } finally {
        foreach ($key in $previous.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
        }
        $random.Dispose()
        Pop-Location
    }
}
