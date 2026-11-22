[CmdletBinding()]
param(
    [string]$DockerExe = 'docker'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$components = 'auth', 'collector', 'articles', 'community', 'moderation', 'notifications'

Push-Location $root
try {
    foreach ($service in $components) {
        $tag = "cybernews/${service}:lab3"
        & $DockerExe build --build-context runtime=./services/runtime --tag $tag "./services/$service"
        if ($LASTEXITCODE) { throw "Docker build failed for $service." }
    }
    & $DockerExe build --file gateway/Dockerfile.k8s --tag cybernews/gateway:lab3 .
    if ($LASTEXITCODE) { throw 'Docker build failed for Gateway.' }
    foreach ($component in $components + 'gateway') {
        & $DockerExe image inspect --format '{{index .RepoTags 0}} {{.Id}} {{.Size}} {{.Config.User}}' "cybernews/${component}:lab3"
        if ($LASTEXITCODE) { throw "Missing image $component." }
    }
} catch {
    Write-Error "FAIL: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
} finally {
    Pop-Location
}
