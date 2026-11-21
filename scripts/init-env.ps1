$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root '.env'
$exists = Test-Path -LiteralPath $envFile

$secretKeys = @('JWT_SECRET', 'INTERNAL_AUTH_SECRET', 'ARTICLE_IMPORT_SECRET')
if ($exists) {
    $original = [IO.File]::ReadAllText($envFile)
    $template = $original
} else {
    $template = [IO.File]::ReadAllText((Join-Path $root '.env.example'))
    $secretKeys += @(
        'POSTGRES_PASSWORD', 'AUTH_DB_PASSWORD', 'COLLECTOR_DB_PASSWORD',
        'ARTICLE_DB_PASSWORD', 'COMMUNITY_DB_PASSWORD', 'MODERATION_DB_PASSWORD',
        'NOTIFICATION_DB_PASSWORD', 'RABBITMQ_PASSWORD'
    )
}

$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    foreach ($name in $secretKeys) {
        $keyPattern = '(?m)^[ \t]*' + [regex]::Escape($name) + '[ \t]*='
        $empty = [regex]($keyPattern + '[ \t]*(?=\r?$)')
        $present = [regex]::IsMatch($template, $keyPattern)
        if ($present -and -not $empty.IsMatch($template)) { continue }

        $bytes = New-Object byte[] 32
        $rng.GetBytes($bytes)
        $secret = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
        if ($present) {
            $template = $empty.Replace($template, "$name=$secret", 1)
        } else {
            $template = $template.TrimEnd("`r", "`n") + "`n$name=$secret`n"
        }
    }
} finally {
    $rng.Dispose()
}

if ($exists -and $template -ceq $original) {
    Write-Host '.env already configured.'
    exit 0
}

$encoding = [Text.UTF8Encoding]::new($false)
if ($exists) {
    $pending = Join-Path $root ('.env.update.' + [Guid]::NewGuid().ToString('N'))
    try {
        [IO.File]::WriteAllText($pending, $template, $encoding)
        if ([IO.File]::ReadAllText($envFile) -cne $original) {
            throw '.env changed during initialization. Run this script again.'
        }
        [IO.File]::Replace($pending, $envFile, [NullString]::Value)
    } finally {
        if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending }
    }
} else {
    $stream = [IO.File]::Open($envFile, [IO.FileMode]::CreateNew)
    try {
        $contents = $encoding.GetBytes($template)
        $stream.Write($contents, 0, $contents.Length)
    } finally {
        $stream.Dispose()
    }
}
Write-Host 'Generated missing secrets in .env.'
