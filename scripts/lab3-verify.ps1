[CmdletBinding()]
param(
    [string]$KubectlExe = 'kubectl',
    [string]$BaseUrl = 'http://127.0.0.1:18080'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lab3-common.ps1')

function Assert-Lab3([bool]$Condition, [string]$Description) {
    if (-not $Condition) { throw $Description }
}

function Read-Lab3Http([string]$Path, [string]$Media = 'application/json', [int]$Code = 200) {
    try {
        $response = Invoke-WebRequest -Uri "$origin$Path" -UseBasicParsing -TimeoutSec 12 -MaximumRedirection 0
    } catch {
        $failure = $_.Exception.Response
        if ($failure -and $Code -ne 200 -and [int]$failure.StatusCode -eq $Code) { return }
        throw "GET $Path did not return HTTP $Code."
    }
    Assert-Lab3 ([int]$response.StatusCode -eq $Code) "Wrong HTTP status for $Path."
    Assert-Lab3 (([string]$response.Headers['Content-Type']).StartsWith($Media)) "Wrong content type for $Path."
    return $response
}

function Test-Lab3Workload($Workload) {
    $name = $Workload.metadata.name
    $container = $Workload.spec.template.spec.containers[0]
    $resources = $container.resources
    Assert-Lab3 ($Workload.spec.replicas -eq $Workload.status.readyReplicas) "$name is not fully Ready."
    Assert-Lab3 ($resources.requests.cpu -and $resources.requests.memory -and $resources.limits.cpu -and $resources.limits.memory) "$name misses resource bounds."
    Assert-Lab3 ($container.livenessProbe -and $container.readinessProbe -and $container.startupProbe) "$name misses probes."
    Assert-Lab3 ($Workload.spec.template.spec.automountServiceAccountToken -eq $false) "$name mounts a Kubernetes API token."
    Assert-Lab3 (@(Get-Lab3ReadyEndpoints $name).Count -eq $Workload.spec.replicas) "$name has an unexpected number of Ready Service endpoints."
    Write-Host "PASS: $name $($Workload.status.readyReplicas)/$($Workload.spec.replicas) Ready; CPU $($resources.requests.cpu)/$($resources.limits.cpu); memory $($resources.requests.memory)/$($resources.limits.memory)"
}

try {
    Initialize-Lab3Cluster $KubectlExe
    $origin = $BaseUrl.TrimEnd('/')
    Assert-Lab3Origin $origin
    $ns = Invoke-Lab3Kubectl get namespace $script:Lab3Namespace -o json | ConvertFrom-Json
    Assert-Lab3 ($ns.status.phase -eq 'Active' -and $ns.metadata.labels.'app.kubernetes.io/part-of' -eq 'cybernews') 'Invalid lab namespace.'

    $deployments = Invoke-Lab3Kubectl get deployments -o json | ConvertFrom-Json
    $statefulsets = Invoke-Lab3Kubectl get statefulsets -o json | ConvertFrom-Json
    $expectedDeployments = $script:Lab3Backends + 'gateway'
    $expectedStatefulSets = @('postgres', 'rabbitmq')
    foreach ($name in $expectedDeployments) {
        $item = @($deployments.items | Where-Object { $_.metadata.name -eq $name })
        Assert-Lab3 ($item.Count -eq 1) "Deployment $name is missing."
        Test-Lab3Workload $item[0]
    }
    foreach ($name in $expectedStatefulSets) {
        $item = @($statefulsets.items | Where-Object { $_.metadata.name -eq $name })
        Assert-Lab3 ($item.Count -eq 1 -and $item[0].spec.replicas -eq 1) "StatefulSet $name is missing or not single-replica."
        Test-Lab3Workload $item[0]
    }

    $services = Invoke-Lab3Kubectl get services -o json | ConvertFrom-Json
    foreach ($name in $expectedDeployments + $expectedStatefulSets + @('postgres-headless', 'rabbitmq-headless')) {
        $service = $services.items | Where-Object { $_.metadata.name -eq $name } | Select-Object -First 1
        Assert-Lab3 ($service.spec.type -eq 'ClusterIP' -and -not $service.spec.externalIPs) "$name is missing or externally exposed."
        Assert-Lab3 (-not @($service.spec.ports | Where-Object { $_.nodePort }).Count) "$name exposes a NodePort."
    }
    $claims = Invoke-Lab3Kubectl get pvc -o json | ConvertFrom-Json
    foreach ($name in 'postgres-data', 'rabbitmq-data') {
        $claim = $claims.items | Where-Object { $_.metadata.name -eq $name } | Select-Object -First 1
        Assert-Lab3 ($claim.status.phase -eq 'Bound' -and $claim.status.accessModes -contains 'ReadWriteOnce') "PVC $name is not Bound ReadWriteOnce."
        Write-Host "PASS: PVC $name Bound ($($claim.spec.storageClassName))"
    }
    $pods = Invoke-Lab3Kubectl get pods -o json | ConvertFrom-Json
    $active = @($pods.items | Where-Object { $_.metadata.labels.'app.kubernetes.io/component' -in @('backend', 'gateway', 'database', 'broker') })
    foreach ($pod in $active) {
        Assert-Lab3 ($pod.status.phase -eq 'Running' -and $pod.status.containerStatuses[0].ready -eq $true -and
            $pod.status.containerStatuses[0].imageID) "Pod $($pod.metadata.name) is not ready."
    }
    $jobs = Invoke-Lab3Kubectl get jobs -o json | ConvertFrom-Json
    foreach ($name in $script:Lab3Backends) {
        Assert-Lab3 ([bool]($jobs.items | Where-Object {
            $_.metadata.labels.'app.kubernetes.io/name' -eq "migrate-$name" -and $_.status.succeeded -eq 1
        } | Select-Object -First 1)) "Migration Job for $name has no successful run."
        Invoke-Lab3Kubectl exec "deployment/$name" '--' alembic current --check-heads
    }
    $credentials = Invoke-Lab3Kubectl get secrets -l app.kubernetes.io/component=credentials -o 'custom-columns=NAME:.metadata.name,IMMUTABLE:.immutable' --no-headers
    Assert-Lab3 (@($credentials | Where-Object { $_ -match '\s+true\s*$' }).Count -eq 8) 'Expected eight immutable credential objects.'
    $policies = @(Invoke-Lab3Kubectl get networkpolicies -l app.kubernetes.io/part-of=cybernews -o name)
    Assert-Lab3 ($policies.Count -eq 8 -and $policies -contains 'networkpolicy.networking.k8s.io/default-deny-cybernews') 'Expected the Lab 3 ingress policies.'
    Invoke-Lab3Kubectl exec deployment/gateway '--' nginx -t
    Invoke-Lab3Kubectl exec rabbitmq-0 '--' rabbitmq-diagnostics -q check_running

    foreach ($path in '/', '/admin/', '/login', '/register', '/profile') {
        $html = Read-Lab3Http $path 'text/html'
        Assert-Lab3 ($html.Content -match '/js/app\.js' -and $html.Headers['Content-Security-Policy']) "$path did not serve the frontend or CSP."
    }
    Read-Lab3Http '/internal/v1/health' 'application/json' 404
    $closed = @{ auth = '/me'; collector = '/status'; articles = '/admin/articles'; community = '/bookmarks'; moderation = '/reports'; notifications = '/unread-count' }
    foreach ($service in $script:Lab3Backends) {
        $prefix = "/api/v1/$service"
        $health = (Read-Lab3Http "$prefix/health").Content | ConvertFrom-Json
        $ready = (Read-Lab3Http "$prefix/ready").Content | ConvertFrom-Json
        Assert-Lab3 ($health.service -eq $service -and $health.status -eq 'ok' -and $ready.status -eq 'ready') "$service did not report a healthy and ready backend."
        $docs = Read-Lab3Http "$prefix/docs" 'text/html'
        $schema = (Read-Lab3Http "$prefix/openapi.json").Content | ConvertFrom-Json
        Assert-Lab3 ($docs.Content -match '\./openapi\.json' -and $schema.openapi -and $schema.servers[0].url -eq $prefix) "$service Swagger or OpenAPI is invalid."
        Assert-Lab3 (-not @($schema.paths.PSObject.Properties.Name | Where-Object { $_ -match '^/internal(?:/|$)' }).Count) "$service advertises an internal endpoint."
        Read-Lab3Http "$prefix/internal/v1/health" 'application/json' 404
        Read-Lab3Http ($prefix + $closed[$service]) 'application/json' 401
        Write-Host "PASS: $service health, readiness, Swagger, OpenAPI, Guest and internal path"
    }
    $catalog = (Read-Lab3Http '/api/v1/articles/?limit=1').Content | ConvertFrom-Json
    $categories = @(((Read-Lab3Http '/api/v1/articles/categories').Content | ConvertFrom-Json) | Where-Object { $_.id })
    Assert-Lab3 ($null -ne $catalog.total -and $categories.Count -gt 0) 'Public catalog contract is invalid.'
    if ($catalog.total -gt 0) {
        $story = $catalog.items[0].id
        $null = Read-Lab3Http "/article/$story" 'text/html'
        $null = Read-Lab3Http "/api/v1/articles/$story"
    }
    Write-Host "PASS: Lab 3 read-only verification; $($catalog.total) articles, $($categories.Count) categories."
} catch {
    Write-Error "FAIL: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
}
