# Shared helpers for the Windows deployment scripts: find a release, download (and join) assets,
# verify SHA-256 checksums.
Set-StrictMode -Version Latest

function Get-DevEnvRelease {
    param([string]$Repo = 'gibovski/ai-devenv-claude', [string]$Version = 'latest')
    $headers = @{ 'User-Agent' = 'devenv-deploy'; 'Accept' = 'application/vnd.github+json' }
    if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $($env:GITHUB_TOKEN)" }
    $url = if ($Version -eq 'latest') { "https://api.github.com/repos/$Repo/releases/latest" } else { "https://api.github.com/repos/$Repo/releases/tags/$Version" }
    Invoke-RestMethod -Uri $url -Headers $headers
}

function Save-DevEnvAsset {
    <# Downloads <Name> from the release, joining <Name>.partNN files when the asset was split. Returns the local path. #>
    param([Parameter(Mandatory)]$Release, [Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][string]$Dir)
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    $dest = Join-Path $Dir $Name
    $assets = @($Release.assets | Where-Object { $_.name -eq $Name })
    $parts = @($Release.assets | Where-Object { $_.name -like "$Name.part*" } | Sort-Object name)
    if ($assets.Count -eq 0 -and $parts.Count -eq 0) { throw "Release $($Release.tag_name) has no asset named $Name" }
    $todo = if ($assets.Count -gt 0) { $assets } else { $parts }
    $files = @()
    foreach ($a in $todo) {
        $out = Join-Path $Dir $a.name
        if (-not (Test-Path $out) -or (Get-Item $out).Length -ne $a.size) {
            Write-Host "Downloading $($a.name) ($([math]::Round($a.size / 1MB)) MB)..."
            try {
                Start-BitsTransfer -Source $a.browser_download_url -Destination $out -ErrorAction Stop
            } catch {
                $ProgressPreference = 'SilentlyContinue'
                Invoke-WebRequest -Uri $a.browser_download_url -OutFile $out -UseBasicParsing
            }
        }
        $files += $out
    }
    if ($parts.Count -gt 0 -and $assets.Count -eq 0) {
        Write-Host "Joining $($files.Count) parts into $Name..."
        $fs = [IO.File]::Create($dest)
        try {
            foreach ($f in $files) { $in = [IO.File]::OpenRead($f); try { $in.CopyTo($fs) } finally { $in.Dispose() } }
        } finally { $fs.Dispose() }
        $files | Remove-Item -Force
    }
    return $dest
}

function Test-DevEnvChecksum {
    param([Parameter(Mandatory)][string]$File, [Parameter(Mandatory)][string]$SumsFile)
    $name = Split-Path $File -Leaf
    $line = Get-Content $SumsFile | Where-Object { $_ -match "\s\*?$([regex]::Escape($name))$" } | Select-Object -First 1
    if (-not $line) { throw "No checksum for $name in $SumsFile" }
    $want = ($line -split '\s+')[0].ToLower()
    Write-Host "Verifying SHA-256 of $name..."
    $got = (Get-FileHash -Algorithm SHA256 -Path $File).Hash.ToLower()
    if ($got -ne $want) { throw "Checksum mismatch for $name (expected $want, got $got)" }
    Write-Host "Checksum OK."
}

Export-ModuleMember -Function Get-DevEnvRelease, Save-DevEnvAsset, Test-DevEnvChecksum
