<#
.SYNOPSIS
  Restore a backup made by Backup-DevEnv.ps1 onto a dev environment VM.

.DESCRIPTION
  Replaces the VM's settings, credentials, controllers and queue with the ones in the backup and restarts
  its Docker stack. Afterwards, log in to the browser with the admin password you used before the backup
  and press Apply once. The VM's SSH password for "dev" is not changed.

  On a brand-new VM the first SSH login asks for the one-time password (printed by New-DevEnvVM.ps1 and
  shown on the VM console) and then for a new password of your choice.

.EXAMPLE
  .\Restore-DevEnv.ps1 -BackupFile "$env:USERPROFILE\Documents\DevEnv-backups\devenv-backup-20261124-090000.tgz"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BackupFile,
    [string]$VMName = 'devenv',
    [string]$Address
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DevEnvCommon.psm1') -Force

$ip = Get-DevEnvAddress -VMName $VMName -Address $Address
Restore-DevEnvState -Address $ip -BackupFile $BackupFile -PasswordHint "On a new VM, type the one-time password, then choose a new one."
Write-Host ''
Write-Host 'Restored.' -ForegroundColor Green
Write-Host "  Open http://$ip/ and log in as admin with the password you used before."
Write-Host '  Then open Apply and press Apply now, so the agents start with this image''s versions.'
