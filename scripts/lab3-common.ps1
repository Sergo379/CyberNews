$script:Lab3Namespace = 'cybernews-lab3'
$script:Lab3Backends = @('auth', 'collector', 'articles', 'community', 'moderation', 'notifications')
$script:Lab3SecretKeys = @(
    'POSTGRES_PASSWORD', 'AUTH_DB_PASSWORD', 'COLLECTOR_DB_PASSWORD', 'ARTICLE_DB_PASSWORD',
    'COMMUNITY_DB_PASSWORD', 'MODERATION_DB_PASSWORD', 'NOTIFICATION_DB_PASSWORD',
    'JWT_SECRET', 'INTERNAL_AUTH_SECRET', 'ARTICLE_IMPORT_SECRET', 'ARTICLE_READ_SECRET',
    'COMMUNITY_MODERATION_SECRET', 'RABBITMQ_PASSWORD'
)

function Invoke-Lab3Kubectl {
    begin { $commandArgs = $args }
    process {
        # On Windows PowerShell native stderr does not determine the exit code.
        $ErrorActionPreference = 'Continue'
        $globalArgs = @('--context', $script:Lab3Context, '--namespace', $script:Lab3Namespace)
        if ($MyInvocation.ExpectingInput) {
            $_ | & $script:Lab3Kubectl @globalArgs @commandArgs
        } else {
            & $script:Lab3Kubectl @globalArgs @commandArgs
        }
        if ($LASTEXITCODE -ne 0) { throw "kubectl $($commandArgs[0]) failed (exit $LASTEXITCODE)." }
    }
}

function Initialize-Lab3Cluster([string]$Exe) {
    $script:Lab3Kubectl = $Exe
    $script:Lab3Context = (& $Exe config current-context | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $script:Lab3Context -cne 'docker-desktop') {
        throw 'The current context must be the local Docker Desktop context (docker-desktop).'
    }
    $view = Invoke-Lab3Kubectl config view --minify -o json | ConvertFrom-Json
    $cluster = $view.clusters[0].cluster
    $address = [Uri]$cluster.server
    if ($address.Scheme -ne 'https' -or $address.Host -notin @('kubernetes.docker.internal', '127.0.0.1', 'localhost') -or
        $cluster.'insecure-skip-tls-verify') {
        throw 'The selected Kubernetes cluster is not the trusted local Docker Desktop endpoint.'
    }
    $nodes = Invoke-Lab3Kubectl get nodes -o json --request-timeout=10s | ConvertFrom-Json
    $ready = @($nodes.items | Where-Object {
        $_.status.conditions | Where-Object { $_.type -eq 'Ready' -and $_.status -eq 'True' }
    })
    if ($ready.Count -eq 0 -or -not @($nodes.items | Where-Object {
        $_.metadata.name -in @('docker-desktop', 'desktop-control-plane')
    }).Count) {
        throw 'Could not confirm a Ready Docker Desktop Kubernetes node.'
    }
    Write-Host "Context: $script:Lab3Context, namespace: $script:Lab3Namespace"
}

function Read-Lab3SecretFile([string]$Path) {
    $entries = @{}
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line -match '^\s*(#.*)?$') { continue }
        if ($line -cnotmatch '^([A-Z_]+)=([0-9a-f]{64})$') { throw 'Invalid lab3.env format.' }
        $key = $Matches[1]
        if ($key -cnotin $script:Lab3SecretKeys -or $entries.ContainsKey($key)) {
            throw 'Unexpected or duplicate key in lab3.env.'
        }
        $entries[$key] = $Matches[2]
    }
    if ($entries.Count -ne $script:Lab3SecretKeys.Count -or
        @($entries.Values | Sort-Object -Unique).Count -ne $script:Lab3SecretKeys.Count) {
        throw 'lab3.env must contain all required, distinct secrets.'
    }
    return $entries
}

function Assert-Lab3Origin([string]$BaseUrl) {
    $uri = [Uri]$BaseUrl
    if ($uri.Scheme -ne 'http' -or $uri.Host -notin @('127.0.0.1', 'localhost') -or
        $uri.Port -eq 8080 -or $uri.AbsolutePath -ne '/' -or $uri.Query -or $uri.UserInfo -or $uri.Fragment) {
        throw 'Use the loopback Gateway port-forward URL (default http://127.0.0.1:18080).'
    }
    $result = Invoke-RestMethod -Uri "$($BaseUrl.TrimEnd('/'))/health" -UseBasicParsing -TimeoutSec 12
    if ($result.service -ne 'gateway' -or $result.status -ne 'ok' -or $result.environment -ne 'kubernetes') {
        throw 'The URL did not identify itself as the Kubernetes Gateway.'
    }
}

function Get-Lab3ReadyEndpoints([string]$Service) {
    $slices = Invoke-Lab3Kubectl get endpointslices -l "kubernetes.io/service-name=$Service" -o json | ConvertFrom-Json
    return @($slices.items | ForEach-Object { $_.endpoints } |
        Where-Object { $_.conditions.ready -eq $true -and $_.targetRef.kind -eq 'Pod' } |
        ForEach-Object { $_.targetRef.name } | Sort-Object -Unique)
}

function Wait-Lab3Community([int]$Count, [string]$RemovedPod = '') {
    $deadline = [DateTime]::UtcNow.AddSeconds(150)
    do {
        $ep = @(Get-Lab3ReadyEndpoints 'community')
        if ($ep.Count -eq $Count -and ($RemovedPod -eq '' -or $ep -cnotcontains $RemovedPod)) { return $ep }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Expected $Count Ready Community endpoints."
}

function Sync-Lab3Images([string]$DockerExe, [string]$ScratchDirectory) {
    $apps = $script:Lab3Backends + 'gateway'
    $tags = @($apps | ForEach-Object { "cybernews/$($_):lab3" })
    $built = @{}
    foreach ($image in $tags) {
        $id = (& $DockerExe image inspect --format '{{.Id}}' $image | Out-String).Trim()
        if ($LASTEXITCODE) { throw "Build missing image $image with lab3-build.ps1." }
        $built[$image] = $id
    }

    $nodes = (Invoke-Lab3Kubectl get nodes -o json | ConvertFrom-Json).items
    $kindNode = @($nodes | Where-Object { $_.metadata.name -eq 'desktop-control-plane' })
    if ($kindNode.Count -eq 0) {
        Write-Host 'Image availability will be verified by Kubernetes on Docker Desktop kubeadm.'
        return
    }
    if ($nodes.Count -ne 1) { throw 'The kind image loader expects the local single-node lab cluster.' }
    $name = $kindNode[0].metadata.name
    $label = (& $DockerExe inspect --format '{{index .Config.Labels "io.x-k8s.kind.cluster"}}' $name | Out-String).Trim()
    if ($LASTEXITCODE -or $label -cne 'desktop') { throw 'Cannot identify the local Docker Desktop kind container.' }

    $runtimeImages = & $DockerExe exec $name crictl images -o json | ConvertFrom-Json
    if ($LASTEXITCODE) { throw 'Could not read the Kubernetes node image store.' }
    $missing = @($tags | Where-Object {
        $tag = $_
        -not @($runtimeImages.images | Where-Object { $_.id -eq $built[$tag] -and $_.repoTags -contains "docker.io/$tag" }).Count
    })
    if (-not $missing.Count) {
        Write-Host 'All seven images are present in the Kubernetes node image store.'
        return
    }

    $null = New-Item -ItemType Directory -Force -Path $ScratchDirectory
    $file = 'cybernews-images-' + [Guid]::NewGuid().ToString('N') + '.tar'
    $archive = Join-Path $ScratchDirectory $file
    $platform = 'linux/' + $kindNode[0].status.nodeInfo.architecture
    if ($platform -notin @('linux/amd64', 'linux/arm64')) { throw 'Unsupported node architecture.' }
    try {
        & $DockerExe image save --platform $platform --output $archive @missing
        if ($LASTEXITCODE) { throw 'Could not export the selected local images.' }
        # Stream the raw tar. Windows PowerShell text pipelines can corrupt binary data.
        $command = Get-Command $DockerExe -CommandType Application -ErrorAction Stop | Select-Object -First 1
        $settings = New-Object System.Diagnostics.ProcessStartInfo
        $settings.FileName = $command.Source
        $settings.Arguments = "exec -i $name ctr --namespace k8s.io images import --platform $platform -"
        $settings.CreateNoWindow = $true
        $settings.UseShellExecute = $false
        $settings.RedirectStandardInput = $true
        $process = [Diagnostics.Process]::Start($settings)
        try {
            $inputFile = [IO.File]::OpenRead($archive)
            try { $inputFile.CopyTo($process.StandardInput.BaseStream) }
            finally {
                $inputFile.Dispose()
                $process.StandardInput.Close()
            }
            $process.WaitForExit()
            if ($process.ExitCode) { throw 'Could not import the images into Kubernetes containerd.' }
        } finally { $process.Dispose() }
    } finally {
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive }
    }
}
