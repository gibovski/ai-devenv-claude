<#
.SYNOPSIS
  Download the latest AI Dev Environment image and create a Hyper-V Generation 2 VM from it.

.DESCRIPTION
  Finds the newest release of gibovski/ai-devenv-claude, downloads the amd64 VHDX (joining split parts),
  verifies its SHA-256 checksum, creates a Gen 2 VM with Secure Boot (Microsoft UEFI CA template),
  attaches it to a virtual switch, starts it, waits for its IP address and prints the settings URL and
  the one-time admin password reported by the VM.

  Run in an elevated PowerShell (Run as administrator) with Hyper-V enabled.

.EXAMPLE
  .\New-DevEnvVM.ps1
.EXAMPLE
  .\New-DevEnvVM.ps1 -VMName devenv2 -MemoryGB 16 -CPUs 8 -DiskSizeGB 200 -SwitchName "External"
#>
[CmdletBinding()]
param(
    [string]$VMName = 'devenv',
    [string]$Version = 'latest',
    [string]$Repo = 'gibovski/ai-devenv-claude',
    [string]$Path = (Join-Path $env:PUBLIC 'Documents\Hyper-V\DevEnv'),
    [int]$MemoryGB = 8,
    [int]$CPUs = 4,
    [int]$DiskSizeGB = 100,
    [string]$SwitchName = 'Default Switch',
    [switch]$Replace
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DevEnvCommon.psm1') -Force

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this script in an elevated PowerShell (Run as administrator).' }
if (-not (Get-Command New-VM -ErrorAction SilentlyContinue)) {
    throw 'Hyper-V is not enabled. Run: Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All  (then reboot)'
}
if (Get-VM -Name $VMName -ErrorAction SilentlyContinue) {
    if (-not $Replace) { throw "A VM named $VMName already exists. Use -Replace to delete and recreate it, or -VMName to pick another name." }
    Write-Host "Removing existing VM $VMName..."
    Stop-VM -Name $VMName -TurnOff -Force -ErrorAction SilentlyContinue
    $old = (Get-VMHardDiskDrive -VMName $VMName).Path
    Remove-VM -Name $VMName -Force
    $old | Where-Object { $_ } | Remove-Item -Force -ErrorAction SilentlyContinue
}
if (-not (Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue)) { throw "Virtual switch '$SwitchName' not found. Available: $((Get-VMSwitch).Name -join ', ')" }

$release = Get-DevEnvRelease -Repo $Repo -Version $Version
$tag = $release.tag_name
Write-Host "Using release $tag"
$dl = Join-Path $Path "download\$tag"
$zipName = "devenv-$tag-amd64.vhdx.zip"
$zip = Save-DevEnvAsset -Release $release -Name $zipName -Dir $dl
$sums = Save-DevEnvAsset -Release $release -Name 'SHA256SUMS-amd64' -Dir $dl
Test-DevEnvChecksum -File $zip -SumsFile $sums

$vmDir = Join-Path $Path $VMName
New-Item -ItemType Directory -Force -Path $vmDir | Out-Null
Write-Host 'Extracting VHDX...'
Expand-Archive -Path $zip -DestinationPath $vmDir -Force
$vhdx = Join-Path $vmDir "devenv-$tag-amd64.vhdx"
$final = Join-Path $vmDir "$VMName.vhdx"
Move-Item -Force $vhdx $final
if ((Get-VHD $final).Size -lt ($DiskSizeGB * 1GB)) { Resize-VHD -Path $final -SizeBytes ($DiskSizeGB * 1GB) }

# Fixed memory with nested virtualization needs MemoryGB free right now. On a busier PC fall back to
# dynamic memory, which Hyper-V does not allow together with nested virtualization.
$freeGB = [math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB)
$fixed = $freeGB -ge ($MemoryGB + 1)
$startGB = if ($fixed) { $MemoryGB } else { [math]::Max(2, [math]::Min(4, $MemoryGB)) }
$minGB = [math]::Min(2, $startGB)
Write-Host "Creating VM $VMName ($CPUs vCPU, $MemoryGB GB RAM, $DiskSizeGB GB disk, switch '$SwitchName')..."
New-VM -Name $VMName -Generation 2 -MemoryStartupBytes ($startGB * 1GB) -VHDPath $final -SwitchName $SwitchName -Path $Path | Out-Null
if ($fixed) {
    Set-VMMemory -VMName $VMName -DynamicMemoryEnabled $false
    Set-VMProcessor -VMName $VMName -Count $CPUs -ExposeVirtualizationExtensions $true
} else {
    Write-Host "Note: only $freeGB GB of RAM is free, so the VM uses dynamic memory ($startGB GB at start, $minGB-$MemoryGB GB) and nested virtualization is off. Docker agents work as normal. Close other apps and rerun with -Replace for a fixed $MemoryGB GB." -ForegroundColor Yellow
    Set-VMProcessor -VMName $VMName -Count $CPUs -ExposeVirtualizationExtensions $false
    Set-VMMemory -VMName $VMName -DynamicMemoryEnabled $true -StartupBytes ($startGB * 1GB) -MinimumBytes ($minGB * 1GB) -MaximumBytes ($MemoryGB * 1GB)
}
Set-VMFirmware -VMName $VMName -EnableSecureBoot On -SecureBootTemplate 'MicrosoftUEFICertificateAuthority'
Enable-VMIntegrationService -VMName $VMName -Name 'Guest Service Interface' -ErrorAction SilentlyContinue
Set-VM -Name $VMName -AutomaticStartAction Start -AutomaticStopAction ShutDown -CheckpointType Disabled -Notes "AI Dev Environment $tag"
try {
    Start-VM -Name $VMName
} catch {
    Write-Host ''
    Write-Host "VM '$VMName' was created but could not start: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Fix the cause (see Troubleshooting in docs/windows-guide.md), then run: Start-VM $VMName" -ForegroundColor Yellow
    exit 1
}

Write-Host 'Waiting for the VM to boot and report its address (first boot takes a few minutes)...'
$deadline = (Get-Date).AddMinutes(15)
$ip = $null
while ((Get-Date) -lt $deadline -and -not $ip) {
    Start-Sleep -Seconds 10
    $ip = (Get-VMNetworkAdapter -VMName $VMName).IPAddresses | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' } | Select-Object -First 1
}

function Get-GuestKvp([string]$Name) {
    $vm = Get-CimInstance -Namespace root\virtualization\v2 -ClassName Msvm_ComputerSystem -Filter "ElementName='$Name'"
    $kvp = Get-CimAssociatedInstance -InputObject $vm -ResultClassName Msvm_KvpExchangeComponent
    $out = @{}
    foreach ($item in @($kvp.GuestExchangeItems)) {
        if (-not $item) { continue }
        $x = [xml]$item
        $n = ($x.INSTANCE.PROPERTY | Where-Object { $_.NAME -eq 'Name' }).VALUE
        $v = ($x.INSTANCE.PROPERTY | Where-Object { $_.NAME -eq 'Data' }).VALUE
        $out[$n] = $v
    }
    return $out
}

$password = $null
$deadline = (Get-Date).AddMinutes(10)
while ((Get-Date) -lt $deadline -and -not $password) {
    try { $kv = Get-GuestKvp $VMName; $password = $kv['DevEnvAdminPassword'] } catch { }
    if (-not $password) { Start-Sleep -Seconds 10 }
}

Write-Host ''
Write-Host "VM '$VMName' is running." -ForegroundColor Green
if ($ip) { Write-Host "  Settings UI:  http://$ip/   (or http://devenv.local/)" } else { Write-Host "  No IP address reported after 15 minutes. Check the VM console: vmconnect localhost $VMName  (log in as dev and run: ip -4 addr)" -ForegroundColor Yellow; Write-Host '  Settings UI:  http://devenv.local/  (if the VM has an address)' }
if ($password) { Write-Host "  Admin password (one-time): $password" } else { Write-Host "  Admin password: shown on the VM console. Run: vmconnect localhost $VMName" }
Write-Host "  SSH:          ssh dev@$(if ($ip) { $ip } else { 'devenv.local' })  (same one-time password, you will be asked to change it)"
