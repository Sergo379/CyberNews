$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root '.env'

if (Test-Path -LiteralPath $envFile) {
    Write-Host '.env already exists.'
    exit 0
}

$passwordKeys = @(
    'POSTGRES_PASSWORD', 'AUTH_DB_PASSWORD', 'COLLECTOR_DB_PASSWORD',
    'ARTICLE_DB_PASSWORD', 'COMMUNITY_DB_PASSWORD', 'MODERATION_DB_PASSWORD',
    'NOTIFICATION_DB_PASSWORD', 'RABBITMQ_PASSWORD'
)
$examplePath = Join-Path $root '.env.example'
$template = [IO.File]::ReadAllText($examplePath)
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    foreach ($name in $passwordKeys) {
        $bytes = New-Object byte[] 32
        $rng.GetBytes($bytes)
        $secret = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
        $template = $template.Replace("$name=`r`n", "$name=$secret`r`n").Replace("$name=`n", "$name=$secret`n")
    }
} finally {
    $rng.Dispose()
}

$contents = [Text.Encoding]::UTF8.GetBytes($template)
$file = [IO.File]::Open($envFile, [IO.FileMode]::CreateNew)
try {
    $file.Write($contents, 0, $contents.Length)
} finally {
    $file.Dispose()
}

Write-Host 'Created .env with random passwords.'
