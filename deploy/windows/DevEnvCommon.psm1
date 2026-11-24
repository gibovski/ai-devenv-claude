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
    $split = $parts.Count -gt 0 -and $assets.Count -eq 0
    if ($split -and (Test-Path $dest)) {
        # Joined on an earlier run (the parts were deleted then); the caller's checksum step verifies it.
        Write-Host "Using $Name downloaded earlier."
        return $dest
    }
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
    if ($split) {
        Write-Host "Joining $($files.Count) parts into $Name..."
        # Join into a temporary file so an interrupted join never looks like a finished download.
        $tmp = "$dest.partial"
        $fs = [IO.File]::Create($tmp)
        try {
            foreach ($f in $files) { $in = [IO.File]::OpenRead($f); try { $in.CopyTo($fs) } finally { $in.Dispose() } }
        } finally { $fs.Dispose() }
        Move-Item -Force $tmp $dest
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

# ---------- SSH to the VM (backup and restore) ----------
# The VM's host keys change whenever it is recreated, so these local-network connections skip the
# known_hosts check instead of failing with "REMOTE HOST IDENTIFICATION HAS CHANGED".
$script:SshOpts = @('-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=NUL', '-o', 'LogLevel=ERROR', '-o', 'ConnectTimeout=15')

function Get-DevEnvAddress {
    <# The VM's IPv4 address from Hyper-V, or the address given. #>
    param([string]$VMName = 'devenv', [string]$Address)
    if ($Address) { return $Address }
    if (-not (Get-Command Get-VMNetworkAdapter -ErrorAction SilentlyContinue)) {
        throw 'Cannot ask Hyper-V for the VM address. Run PowerShell as administrator, or pass -Address <ip>.'
    }
    $ip = (Get-VMNetworkAdapter -VMName $VMName -ErrorAction Stop).IPAddresses | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' } | Select-Object -First 1
    if (-not $ip) { throw "VM '$VMName' has no IPv4 address yet. Is it running? (Start-VM $VMName), or pass -Address <ip>." }
    return $ip
}

function Initialize-DevEnvSshKey {
    <# A key pair just for the dev environment VMs, so you type the VM password once per VM, not per step. #>
    if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
        throw 'The Windows SSH client is missing. In an administrator PowerShell run: Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0'
    }
    $dir = Join-Path $env:USERPROFILE '.ssh'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $key = Join-Path $dir 'devenv_ed25519'
    if (-not (Test-Path $key)) {
        # cmd passes the empty passphrase reliably on every PowerShell version.
        cmd /c "ssh-keygen -q -t ed25519 -C devenv -N `"`" -f `"$key`"" | Out-Null
        if (-not (Test-Path $key)) { throw "ssh-keygen could not create $key" }
    }
    return $key
}

function Connect-DevEnv {
    <# Makes sure the VM accepts our key: the first time it asks for the VM's password for user dev. #>
    param([Parameter(Mandatory)][string]$Address, [Parameter(Mandatory)][string]$Key, [string]$PasswordHint)
    $base = @('-i', $Key) + $script:SshOpts
    # LogLevel=QUIET instead of 2>$null: redirecting a native command's stderr can stop Windows PowerShell 5.1.
    & ssh @base -o BatchMode=yes -o LogLevel=QUIET "dev@$Address" true
    if ($LASTEXITCODE -eq 0) { return }
    $pub = (Get-Content "$Key.pub" -Raw).Trim()
    $install = "umask 077; mkdir -p ~/.ssh; grep -qxF '$pub' ~/.ssh/authorized_keys 2>/dev/null || echo '$pub' >> ~/.ssh/authorized_keys"
    # Start-Process keeps ssh on this console even when the caller collects output, so the password
    # prompts (and the "choose a new password" prompts of a new VM) stay visible.
    $interactive = "-i `"$Key`" $($script:SshOpts -join ' ') -t dev@$Address `"$install`""
    Write-Host ''
    Write-Host "Log in to the VM as 'dev' once, so this PC can connect without a password from now on." -ForegroundColor Cyan
    if ($PasswordHint) { Write-Host $PasswordHint -ForegroundColor Cyan }
    # A VM that has never been logged in to asks for a new password and then closes the connection,
    # so try a second time.
    for ($i = 1; $i -le 2; $i++) {
        Start-Process -FilePath ssh -ArgumentList $interactive -NoNewWindow -Wait | Out-Null
        & ssh @base -o BatchMode=yes -o LogLevel=QUIET "dev@$Address" true
        if ($LASTEXITCODE -eq 0) { return }
        if ($i -eq 1) { Write-Host 'Once more, with the password you just set (or the same one):' -ForegroundColor Cyan }
    }
    throw "Could not log in to dev@$Address. Check the address and the password, then run this again."
}

function Invoke-DevEnvRemote {
    <# Runs one of the scripts in .\remote on the VM and returns its output lines. #>
    param([Parameter(Mandatory)][string]$Address, [Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)][string]$Script)
    $text = (Get-Content -Raw (Join-Path $PSScriptRoot "remote\$Script")) -replace "`r`n", "`n"
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text))
    $base = @('-i', $Key) + $script:SshOpts
    $out = & ssh @base "dev@$Address" "echo $b64 | base64 -d | bash"
    $code = $LASTEXITCODE
    $out | ForEach-Object { Write-Host "  $_" }
    if ($code -ne 0) { throw "$Script failed on the VM (exit code $code)." }
    return $out
}

function Copy-DevEnvFile {
    <# scp in either direction; remote paths look like dev@<ip>:file #>
    param([Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)][string]$From, [Parameter(Mandatory)][string]$To)
    $base = @('-i', $Key) + $script:SshOpts
    & scp @base -q $From $To
    if ($LASTEXITCODE -ne 0) { throw "Copying $From to $To failed." }
}

function Backup-DevEnvState {
    <# Saves the VM's settings, credentials (still encrypted, with their key) and queue to a local file. #>
    param([Parameter(Mandatory)][string]$Address, [Parameter(Mandatory)][string]$OutFile, [string]$PasswordHint)
    $key = Initialize-DevEnvSshKey
    Connect-DevEnv -Address $Address -Key $key -PasswordHint $PasswordHint
    Write-Host "Backing up dev@$Address ..."
    Invoke-DevEnvRemote -Address $Address -Key $key -Script 'backup.sh' | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutFile) | Out-Null
    Copy-DevEnvFile -Key $key -From "dev@${Address}:devenv-backup.tgz" -To $OutFile
    & ssh @(@('-i', $key) + $script:SshOpts) "dev@$Address" 'rm -f ~/devenv-backup.tgz' | Out-Null
    if ((Get-Item $OutFile).Length -lt 100) { throw "The backup file $OutFile looks empty." }
    return (Resolve-Path $OutFile).Path
}

function Restore-DevEnvState {
    <# Puts a backup made by Backup-DevEnvState onto a VM (replacing what the VM had) and restarts its stack. #>
    param([Parameter(Mandatory)][string]$Address, [Parameter(Mandatory)][string]$BackupFile, [string]$PasswordHint)
    if (-not (Test-Path $BackupFile)) { throw "Backup file not found: $BackupFile" }
    $key = Initialize-DevEnvSshKey
    Connect-DevEnv -Address $Address -Key $key -PasswordHint $PasswordHint
    Write-Host "Restoring $BackupFile to dev@$Address ..."
    Copy-DevEnvFile -Key $key -From (Resolve-Path $BackupFile).Path -To "dev@${Address}:devenv-backup.tgz"
    Invoke-DevEnvRemote -Address $Address -Key $key -Script 'restore.sh' | Out-Null
}

Export-ModuleMember -Function Get-DevEnvRelease, Save-DevEnvAsset, Test-DevEnvChecksum, Get-DevEnvAddress, Initialize-DevEnvSshKey,
    Connect-DevEnv, Invoke-DevEnvRemote, Copy-DevEnvFile, Backup-DevEnvState, Restore-DevEnvState
