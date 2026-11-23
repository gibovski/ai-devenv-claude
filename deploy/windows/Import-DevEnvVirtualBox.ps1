<#
.SYNOPSIS
  Fallback for machines without Hyper-V: download the latest OVA and import it into VirtualBox.

.DESCRIPTION
  Downloads devenv-<tag>-amd64.ova (joining split parts), verifies its checksum, imports it with
  VBoxManage, forwards host ports 8080 -> 80 (UI) and 2222 -> 22 (SSH) on the NAT adapter, and starts
  the VM headless. Note: VirtualBox and Hyper-V conflict on some Windows builds; prefer New-DevEnvVM.ps1.

.EXAMPLE
  .\Import-DevEnvVirtualBox.ps1 -MemoryGB 8 -CPUs 4
#>
[CmdletBinding()]
param(
    [string]$VMName = 'devenv',
    [string]$Version = 'latest',
    [string]$Repo = 'gibovski/ai-devenv-claude',
    [string]$Path = (Join-Path $env:USERPROFILE 'DevEnv'),
    [int]$MemoryGB = 8,
    [int]$CPUs = 4,
    [int]$UiPort = 8080,
    [int]$SshPort = 2222
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DevEnvCommon.psm1') -Force

$vbox = Get-Command VBoxManage -ErrorAction SilentlyContinue
if (-not $vbox) {
    $candidate = Join-Path $env:ProgramFiles 'Oracle\VirtualBox\VBoxManage.exe'
    if (Test-Path $candidate) { $vbox = $candidate } else { throw 'VirtualBox is not installed (VBoxManage not found).' }
} else { $vbox = $vbox.Source }

$release = Get-DevEnvRelease -Repo $Repo -Version $Version
$tag = $release.tag_name
Write-Host "Using release $tag"
$dl = Join-Path $Path "download\$tag"
$ova = Save-DevEnvAsset -Release $release -Name "devenv-$tag-amd64.ova" -Dir $dl
$sums = Save-DevEnvAsset -Release $release -Name 'SHA256SUMS-amd64' -Dir $dl
Test-DevEnvChecksum -File $ova -SumsFile $sums

& $vbox showvminfo $VMName *> $null
if ($LASTEXITCODE -eq 0) { throw "A VirtualBox VM named $VMName already exists. Remove it or pass -VMName." }

Write-Host "Importing $VMName..."
& $vbox import $ova --vsys 0 --vmname $VMName --memory ($MemoryGB * 1024) --cpus $CPUs
if ($LASTEXITCODE -ne 0) { throw 'VBoxManage import failed.' }
& $vbox modifyvm $VMName --firmware efi --nic1 nat --natpf1 "ui,tcp,127.0.0.1,$UiPort,,80" --natpf1 "ssh,tcp,127.0.0.1,$SshPort,,22"
& $vbox startvm $VMName --type headless
if ($LASTEXITCODE -ne 0) { throw 'VBoxManage startvm failed.' }

Write-Host ''
Write-Host "VM '$VMName' is starting (first boot takes a few minutes)." -ForegroundColor Green
Write-Host "  Settings UI:  http://localhost:$UiPort/"
Write-Host "  SSH:          ssh -p $SshPort dev@localhost"
Write-Host "  One-time admin password: open the VM window in VirtualBox (Show) to read it from the console,"
Write-Host "  or run: & '$vbox' guestproperty get $VMName /DevEnv/AdminPassword   (when guest additions are present)"
