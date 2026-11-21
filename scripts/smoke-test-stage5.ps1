[CmdletBinding()]
param(
    [string]$PythonExe = 'python',
    [string]$DockerExe = 'docker',
    [switch]$Demo
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$project = 'cybernews-stage5-' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
$compose = @('compose', '-f', 'compose.yaml', '-f', 'tests/stage2.compose.yaml',
    '-f', 'tests/stage3.compose.yaml', '-f', 'tests/stage4.compose.yaml', '-p', $project)
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
    RABBITMQ_USER = 'cybernews_test_broker'
    RABBITMQ_VHOST = 'cybernews-stage4'
    ACCESS_TOKEN_TTL_SECONDS = '900'
    ADMIN_SESSION_TTL_SECONDS = $(if ($Demo) { '900' } else { '300' })
    CYBERNEWS_TEST_PROJECT = $project
    CYBERNEWS_TEST_DOCKER = $DockerExe
    CYBERNEWS_TEST_SUPER_EMAIL = 'stage5-admin@example.com'
    CYBERNEWS_TEST_SUPER_PASSWORD = (New-Secret)
    CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD = (New-Secret)
}
foreach ($key in @('POSTGRES_PASSWORD', 'AUTH_DB_PASSWORD', 'COLLECTOR_DB_PASSWORD', 'ARTICLE_DB_PASSWORD',
        'COMMUNITY_DB_PASSWORD', 'MODERATION_DB_PASSWORD', 'NOTIFICATION_DB_PASSWORD',
        'RABBITMQ_PASSWORD', 'JWT_SECRET', 'INTERNAL_AUTH_SECRET', 'ARTICLE_IMPORT_SECRET',
        'ARTICLE_READ_SECRET', 'COMMUNITY_MODERATION_SECRET')) {
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
    Invoke-TestCompose up -d --build --wait --wait-timeout 125 postgres rabbitmq auth articles collector community moderation notifications gateway
    $address = (Invoke-TestCompose port gateway 8080 | Out-String).Trim()
    if ($address -notmatch '^127\.0\.0\.1:[0-9]+$') { throw 'Unexpected test Gateway bind address.' }
    $env:CYBERNEWS_TEST_BASE_URL = "http://$address"
    if ($Demo) {
        Write-Host "Isolated demo: $env:CYBERNEWS_TEST_BASE_URL ($project)"
        Write-Host 'Create a temporary Super Admin. Use only test credentials in this terminal.'
        Invoke-TestCompose exec auth python -m app.bootstrap
        Write-Host "Demo: $env:CYBERNEWS_TEST_BASE_URL  |  Admin: $env:CYBERNEWS_TEST_BASE_URL/admin/"
        $null = Read-Host 'Press Enter after the demonstration to stop this isolated stack'
        return
    }
    $data = @{
        email = $override.CYBERNEWS_TEST_SUPER_EMAIL
        nickname = 'stage5-root'
        password = $override.CYBERNEWS_TEST_SUPER_PASSWORD
        admin_password = $override.CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD
    } | ConvertTo-Json -Compress
    Invoke-TestCompose cp tests/bootstrap_cli.py auth:/tmp/stage5-bootstrap-test.py
    $data | & $DockerExe @compose exec -T auth python /tmp/stage5-bootstrap-test.py
    if ($LASTEXITCODE -ne 0) { throw 'Test administrator bootstrap failed.' }

    & $PythonExe -m pytest -q --tb=short tests/test_stage5.py -k 'not live_catalog'
    if ($LASTEXITCODE -ne 0) { throw 'Stage 5 pytest suite failed.' }
    Write-Host 'PASS: Stage 5 browser, Gateway and isolated data flows.'
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
