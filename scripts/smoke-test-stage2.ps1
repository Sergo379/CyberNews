[CmdletBinding()]
param(
    [switch]$RunPytest,
    [string]$PythonExe = 'python',
    [string]$DockerExe = 'docker'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$project = 'cybernews-stage2-' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
$compose = @('compose', '-f', 'compose.yaml', '-f', 'tests/stage2.compose.yaml', '-p', $project)
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

function Call-Api {
    param(
        [string]$Method,
        [string]$Path,
        [hashtable]$Body,
        [hashtable]$Headers = @{},
        [int]$Expected = 200
    )

    $options = @{
        Method = $Method; Uri = "$base/api/v1/$Path"; Headers = $Headers;
        TimeoutSec = 12; UseBasicParsing = $true
    }
    if ($null -ne $Body) {
        $options.Body = $Body | ConvertTo-Json -Compress
        $options.ContentType = 'application/json'
    }
    try {
        $reply = Invoke-WebRequest @options
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq $Expected) { return }
        $received = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 'network error' }
        throw "$Method $Path expected $Expected but got $received."
    }
    if ([int]$reply.StatusCode -ne $Expected) { throw "$Method $Path returned an unexpected status." }
    if ($reply.Content) { return $reply.Content | ConvertFrom-Json }
}

function Login-Account([string]$Email, [string]$Password) {
    $access = Call-Api -Method Post -Path 'auth/login' -Body @{ email = $Email; password = $Password }
    return @{ Authorization = "Bearer $($access.access_token)" }
}

function Add-AdminSession([hashtable]$Headers, [string]$Password) {
    $session = Call-Api -Method Post -Path 'auth/admin/unlock' -Headers $Headers -Body @{ admin_password = $Password }
    $Headers['X-Admin-Session'] = $session.admin_session
}

$override = @{
    POSTGRES_USER = 'cybernews_test_admin'
    ACCESS_TOKEN_TTL_SECONDS = '900'
    ADMIN_SESSION_TTL_SECONDS = '900'
    CYBERNEWS_TEST_PROJECT = $project
    CYBERNEWS_TEST_DOCKER = $DockerExe
    CYBERNEWS_TEST_SUPER_EMAIL = 'stage2-admin@example.com'
    CYBERNEWS_TEST_SUPER_PASSWORD = (New-Secret)
    CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD = (New-Secret)
}
foreach ($key in @('POSTGRES_PASSWORD', 'AUTH_DB_PASSWORD', 'COLLECTOR_DB_PASSWORD', 'ARTICLE_DB_PASSWORD',
        'COMMUNITY_DB_PASSWORD', 'MODERATION_DB_PASSWORD', 'NOTIFICATION_DB_PASSWORD', 'RABBITMQ_PASSWORD',
        'JWT_SECRET', 'INTERNAL_AUTH_SECRET')) {
    $override[$key] = New-Secret
}
$previous = @{}

Push-Location $root
try {
    foreach ($key in $override.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $override[$key], 'Process')
    }
    $previous['CYBERNEWS_TEST_BASE_URL'] = $env:CYBERNEWS_TEST_BASE_URL
    & $DockerExe @compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Invalid test Compose configuration.' }
    Invoke-TestCompose up -d --build --wait --wait-timeout 100 postgres auth moderation gateway

    $address = (Invoke-TestCompose port gateway 8080 | Out-String).Trim()
    if ($address -notmatch '^127\.0\.0\.1:[0-9]+$') { throw 'Unexpected test Gateway bind address.' }
    $base = "http://$address"
    $env:CYBERNEWS_TEST_BASE_URL = $base

    $data = @{
        email = $override.CYBERNEWS_TEST_SUPER_EMAIL; nickname = 'stage2-root';
        password = $override.CYBERNEWS_TEST_SUPER_PASSWORD;
        admin_password = $override.CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD
    } | ConvertTo-Json -Compress
    Invoke-TestCompose cp tests/bootstrap_cli.py auth:/tmp/stage2-bootstrap-test.py
    $data | & $DockerExe @compose exec -T auth python /tmp/stage2-bootstrap-test.py
    if ($LASTEXITCODE -ne 0) { throw 'Test administrator bootstrap failed.' }

    if ($RunPytest) {
        & $PythonExe -m pytest -q --tb=short tests/test_stage2.py
        if ($LASTEXITCODE -ne 0) { throw 'Stage 2 pytest suite failed.' }
    }

    $super = Login-Account $override.CYBERNEWS_TEST_SUPER_EMAIL $override.CYBERNEWS_TEST_SUPER_PASSWORD
    Add-AdminSession $super $override.CYBERNEWS_TEST_SUPER_ADMIN_PASSWORD
    $password = New-Secret
    $user = Call-Api -Method Post -Path 'auth/register' -Body @{
        email = 'smoke-member@example.com'; nickname = 'smoke-member'; password = $password
    } -Expected 201
    $member = Login-Account $user.email $password
    $complaint = Call-Api -Method Post -Path 'moderation/reports' -Headers $member -Body @{
        target_type = 'article'; target_id = [Guid]::NewGuid().ToString(); reason = 'Smoke report'
    } -Expected 201
    $null = Call-Api -Method Patch -Path "moderation/reports/$($complaint.id)" -Headers $super -Body @{ status = 'reviewed' }
    $restriction = Call-Api -Method Post -Path 'moderation/restrictions' -Headers $super -Body @{
        user_id = $user.id; reason = 'Smoke restriction'
    } -Expected 201

    Invoke-TestCompose stop auth moderation postgres
    Invoke-TestCompose up -d --wait --wait-timeout 100 postgres auth moderation gateway
    $null = Call-Api -Method Get -Path 'auth/admin/session' -Headers $super
    $profile = Call-Api -Method Get -Path 'auth/me' -Headers $member
    $permission = Call-Api -Method Get -Path 'moderation/comment-permission' -Headers $member
    $reviewed = Call-Api -Method Get -Path "moderation/reports/$($complaint.id)" -Headers $super
    if ($profile.id -ne $user.id -or $permission.allowed -ne $false -or $reviewed.status -ne 'reviewed') {
        throw 'Auth or moderation data did not survive restart.'
    }
    $null = Call-Api -Method Post -Path "moderation/restrictions/$($restriction.id)/lift" `
        -Headers $super -Body @{ reason = 'Smoke restoration' }
    $permission = Call-Api -Method Get -Path 'moderation/comment-permission' -Headers $member
    if ($permission.allowed -ne $true) { throw 'Commenting permission did not recover.' }
    Call-Api -Method Get -Path 'auth/internal/v1/principal' -Expected 404

    Invoke-TestCompose stop auth
    try {
        Call-Api -Method Get -Path 'moderation/comment-permission' -Headers $member -Expected 503
    } finally {
        Invoke-TestCompose start auth
    }
    Write-Host 'PASS: Stage 2 Gateway smoke, restart persistence and Auth dependency failure.'
} finally {
    try {
        Invoke-TestCompose down
    } finally {
        foreach ($key in $previous.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
        }
        $random.Dispose()
        Pop-Location
    }
}
