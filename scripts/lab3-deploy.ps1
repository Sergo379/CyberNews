[CmdletBinding()]
param(
    [string]$KubectlExe = 'kubectl',
    [string]$DockerExe = 'docker'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'lab3-common.ps1')

function Get-Lab3Metadata([string]$Name, [string]$Component) {
    return @{
        name = $Name
        namespace = $script:Lab3Namespace
        labels = @{
            'app.kubernetes.io/name' = $Name
            'app.kubernetes.io/component' = $Component
            'app.kubernetes.io/part-of' = 'cybernews'
            'app.kubernetes.io/version' = 'lab3'
        }
    }
}

function Add-Lab3Secret([string]$Name, [hashtable]$Mapping) {
    $encoded = @{}
    foreach ($entry in $Mapping.GetEnumerator()) {
        $bytes = [Text.Encoding]::UTF8.GetBytes($privateValues[$entry.Value])
        $encoded[$entry.Key] = [Convert]::ToBase64String($bytes)
    }
    # Read in memory only, then refuse to overwrite credentials behind existing PVCs.
    $current = Invoke-Lab3Kubectl get secret $Name --ignore-not-found -o json
    if ($current) {
        $resource = $current | ConvertFrom-Json
        if (-not $resource.immutable -or @($resource.data.PSObject.Properties).Count -ne $encoded.Count) {
            throw "Existing secret $Name differs from the local configuration."
        }
        foreach ($key in $encoded.Keys) {
            if ($resource.data.$key -cne $encoded[$key]) {
                throw "Existing secret $Name differs from secrets/lab3.env."
            }
        }
        return
    }
    @{
        apiVersion = 'v1'
        kind = 'Secret'
        type = 'Opaque'
        immutable = $true
        metadata = Get-Lab3Metadata $Name 'credentials'
        data = $encoded
    } | ConvertTo-Json -Depth 8 -Compress | Invoke-Lab3Kubectl create -f -
}

function Add-Lab3ConfigFile([string]$Name, [string]$Key, [string]$Path) {
    $content = [IO.File]::ReadAllText((Join-Path $root $Path)).Replace("`r`n", "`n")
    @{
        apiVersion = 'v1'
        kind = 'ConfigMap'
        metadata = Get-Lab3Metadata $Name 'configuration'
        data = @{$Key = $content}
    } | ConvertTo-Json -Depth 8 -Compress | Invoke-Lab3Kubectl apply --server-side --field-manager cybernews-lab3 -f -
}

Push-Location $root
try {
    Initialize-Lab3Cluster $KubectlExe
    $existingNamespace = Invoke-Lab3Kubectl get namespace $script:Lab3Namespace --ignore-not-found -o json
    if ($existingNamespace) {
        $labels = ($existingNamespace | ConvertFrom-Json).metadata.labels
        if ($labels.'app.kubernetes.io/part-of' -ne 'cybernews' -or
            $labels.'app.kubernetes.io/version' -ne 'lab3') {
            throw 'The target namespace exists without the CyberNews lab3 labels.'
        }
    }
    $classes = Invoke-Lab3Kubectl get storageclass -o json | ConvertFrom-Json
    $defaults = @($classes.items | Where-Object {
        $_.metadata.annotations.'storageclass.kubernetes.io/is-default-class' -eq 'true'
    })
    if ($defaults.Count -ne 1) { throw 'Expected one default StorageClass for the local PVCs.' }
    Write-Host "StorageClass: $($defaults[0].metadata.name)"

    Sync-Lab3Images $DockerExe (Join-Path $root '.test-artifacts/lab3')
    $privateValues = Read-Lab3SecretFile (Join-Path $root 'secrets/lab3.env')
    if (Test-Path -LiteralPath '.env') {
        $composeValues = @(
            Get-Content -LiteralPath '.env' | Where-Object { $_ -match '^[A-Z_]+=' } |
                ForEach-Object { ($_ -split '=', 2)[1].Trim().Trim('"', "'") }
        )
        foreach ($value in $privateValues.Values) {
            if ($composeValues -ccontains $value) { throw 'The lab3 and Compose credentials must be independent.' }
        }
    }

    Invoke-Lab3Kubectl apply -f k8s/namespace.yaml
    Invoke-Lab3Kubectl apply -f k8s/configmaps
    Add-Lab3ConfigFile 'postgres-init' '10-initialize.sh' 'infrastructure/postgres/10-initialize.sh'
    Add-Lab3ConfigFile 'rabbitmq-runtime' 'rabbitmq.conf' 'infrastructure/rabbitmq/rabbitmq.conf'

    $pgMapping = @{ POSTGRES_PASSWORD = 'POSTGRES_PASSWORD' }
    foreach ($key in $script:Lab3SecretKeys | Where-Object { $_ -like '*_DB_PASSWORD' }) { $pgMapping[$key] = $key }
    Add-Lab3Secret 'postgres-credentials' $pgMapping
    Add-Lab3Secret 'rabbitmq-credentials' @{ RABBITMQ_DEFAULT_PASS = 'RABBITMQ_PASSWORD' }
    $appKeys = @{
        auth = @('JWT_SECRET', 'INTERNAL_AUTH_SECRET')
        collector = @('INTERNAL_AUTH_SECRET', 'ARTICLE_IMPORT_SECRET')
        articles = @('INTERNAL_AUTH_SECRET', 'ARTICLE_IMPORT_SECRET', 'ARTICLE_READ_SECRET', 'RABBITMQ_PASSWORD')
        community = @('INTERNAL_AUTH_SECRET', 'ARTICLE_READ_SECRET', 'COMMUNITY_MODERATION_SECRET')
        moderation = @('INTERNAL_AUTH_SECRET', 'ARTICLE_READ_SECRET', 'COMMUNITY_MODERATION_SECRET')
        notifications = @('INTERNAL_AUTH_SECRET', 'ARTICLE_READ_SECRET', 'RABBITMQ_PASSWORD')
    }
    foreach ($application in $script:Lab3Backends) {
        $passwordKey = $application.ToUpperInvariant() + '_DB_PASSWORD'
        if ($application -eq 'articles') { $passwordKey = 'ARTICLE_DB_PASSWORD' }
        if ($application -eq 'notifications') { $passwordKey = 'NOTIFICATION_DB_PASSWORD' }
        $mapping = @{ DB_PASSWORD = $passwordKey }
        foreach ($key in $appKeys[$application]) { $mapping[$key] = $key }
        Add-Lab3Secret "$application-credentials" $mapping
    }

    Invoke-Lab3Kubectl apply -f k8s/networkpolicies
    Invoke-Lab3Kubectl apply -f k8s/services/storage.yaml -f k8s/storage
    Invoke-Lab3Kubectl apply -f k8s/statefulsets
    foreach ($component in 'postgres', 'rabbitmq') {
        Invoke-Lab3Kubectl rollout status "statefulset/$component" --timeout=240s
    }

    $jobs = @()
    foreach ($service in $script:Lab3Backends) {
        $jobs += (Invoke-Lab3Kubectl create -f "k8s/jobs/$service.yaml" -o name | Out-String).Trim()
    }
    Invoke-Lab3Kubectl wait --for=condition=complete @jobs --timeout=250s
    Invoke-Lab3Kubectl apply -f k8s/services/apps.yaml
    # The Collector performs a startup sync. Its first attempt needs a Ready Articles endpoint.
    Invoke-Lab3Kubectl apply -f k8s/deployments/articles.yaml
    Invoke-Lab3Kubectl rollout status deployment/articles --timeout=240s
    Invoke-Lab3Kubectl apply -f k8s/deployments
    foreach ($service in ($script:Lab3Backends | Where-Object { $_ -ne 'articles' }) + 'gateway') {
        Invoke-Lab3Kubectl rollout status "deployment/$service" --timeout=240s
    }
    Write-Host 'PASS: Lab 3 is Ready. Start a separate Gateway port-forward on 127.0.0.1:18080.'
} catch {
    Write-Error "FAIL: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
} finally {
    Pop-Location
}
