[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lab3-common.ps1')
$directory = Join-Path (Split-Path $PSScriptRoot -Parent) 'secrets'
$path = Join-Path $directory 'lab3.env'

if (Test-Path -LiteralPath $path) {
    $null = Read-Lab3SecretFile $path
    Write-Host 'Reusing the existing secrets/lab3.env.'
    return
}

$null = New-Item -ItemType Directory -Path $directory -Force
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $lines = foreach ($key in $script:Lab3SecretKeys) {
        $bytes = New-Object byte[] 32
        $random.GetBytes($bytes)
        "$key=$([BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant())"
    }
    $file = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $data = [Text.Encoding]::ASCII.GetBytes(($lines -join "`n") + "`n")
        $file.Write($data, 0, $data.Length)
    } finally {
        $file.Dispose()
    }
} finally {
    $random.Dispose()
}
Write-Host 'Created independent secrets in secrets/lab3.env.'
