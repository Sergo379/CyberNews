[CmdletBinding()]
param(
    [string]$KubectlExe = 'kubectl',
    [string]$BaseUrl = 'http://127.0.0.1:18080'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lab3-common.ps1')

function Read-Community([string]$RequestId) {
    $result = Invoke-RestMethod -Uri "$origin/api/v1/community/health" -UseBasicParsing -TimeoutSec 12 -Headers @{'X-Request-ID' = $RequestId}
    if ($result.service -ne 'community' -or $result.status -ne 'ok') { throw 'Gateway did not route a healthy Community response.' }
}

function Restart-OneCommunityPod([string[]]$Before, [bool]$CheckRemaining) {
    $victim = $Before[0]
    Invoke-Lab3Kubectl delete pod $victim --wait=false
    if ($CheckRemaining) {
        1..8 | ForEach-Object { Read-Community "lab3-during-recovery-$($_)" }
    }
    $after = @(Wait-Lab3Community $Before.Count $victim)
    $replacement = @($after | Where-Object { $Before -cnotcontains $_ })
    if ($replacement.Count -ne 1) { throw 'Expected one replacement Pod.' }
    Read-Community 'lab3-after-recovery'
    Write-Host "PASS: removed $victim; replacement $($replacement[0]); $($after.Count) Ready; Gateway HTTP 200"
}

try {
    Initialize-Lab3Cluster $KubectlExe
    $origin = $BaseUrl.TrimEnd('/')
    Assert-Lab3Origin $origin
    $deployment = Invoke-Lab3Kubectl get deployment community -o json | ConvertFrom-Json
    if ($deployment.metadata.namespace -ne 'cybernews-lab3' -or
        $deployment.metadata.labels.'app.kubernetes.io/part-of' -ne 'cybernews' -or
        $deployment.metadata.labels.'app.kubernetes.io/version' -ne 'lab3') {
        throw 'The selected Community Deployment is not the lab3 resource.'
    }
    $original = $deployment.spec.replicas
    $before = @(Wait-Lab3Community $original)
    Write-Host "Initial Ready endpoints ($original): $($before -join ', ')"
    try {
        Invoke-Lab3Kubectl scale deployment community --replicas=3
        $scaled = @(Wait-Lab3Community 3)
        Write-Host "Ready endpoints after scale (3): $($scaled -join ', ')"
        $marker = 'lab3-balancing-' + [Guid]::NewGuid().ToString('N')
        1..45 | ForEach-Object { Read-Community "$marker-$_" }
        foreach ($pod in $scaled) {
            $logs = Invoke-Lab3Kubectl logs $pod --since=5m
            $requests = @($logs | Select-String -SimpleMatch $marker).Count
            if ($requests -eq 0) { throw "No correlated requests reached $pod." }
            Write-Host "PASS: $pod received $requests requests through the Community Service."
        }
        Restart-OneCommunityPod $scaled $true
        Invoke-Lab3Kubectl scale deployment community --replicas=1
        $single = @(Wait-Lab3Community 1)
        Restart-OneCommunityPod $single $false
    } finally {
        Invoke-Lab3Kubectl scale deployment community "--replicas=$original"
        $null = Wait-Lab3Community $original
    }
    Write-Host "PASS: Community restored to $original replica(s)."
} catch {
    Write-Error "FAIL: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
}
