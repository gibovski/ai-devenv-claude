<#
.SYNOPSIS
  Back up the dev environment VM's settings, credentials and work queue to a file on this PC.

.DESCRIPTION
  Saves everything you entered in the browser (GitHub, Claude, Codex and Cloudflare credentials, agent
  counts, controllers and their tokens, the admin password), the queue with its uploads, and the key that
  decrypts the credentials. Restore it onto a new VM with Restore-DevEnv.ps1, or let
  New-DevEnvVM.ps1 -Replace do both for you.

  Works with every image version: it connects to the VM over SSH as user "dev". The first time, it asks
  for that user's password and then installs a key (%USERPROFILE%\.ssh\devenv_ed25519) so later runs
  don't ask again.

  The backup holds your credentials together with the key that decrypts them: keep it on this PC and
  never share it.

.EXAMPLE
  .\Backup-DevEnv.ps1
.EXAMPLE
  .\Backup-DevEnv.ps1 -Address 172.28.1.136 -OutFile D:\safe\devenv.tgz
#>
[CmdletBinding()]
param(
    [string]$VMName = 'devenv',
    [string]$Address,
    [string]$OutFile = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) ("DevEnv-backups\devenv-backup-{0:yyyyMMdd-HHmmss}.tgz" -f (Get-Date)))
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DevEnvCommon.psm1') -Force

$ip = Get-DevEnvAddress -VMName $VMName -Address $Address
$file = Backup-DevEnvState -Address $ip -OutFile $OutFile -PasswordHint "This is the password you use for 'ssh dev@$ip'."
Write-Host ''
Write-Host "Backup saved: $file" -ForegroundColor Green
Write-Host 'It contains your credentials and the key that decrypts them. Keep it on this PC and do not share it.' -ForegroundColor Yellow
Write-Host "Restore it onto a VM with: .\Restore-DevEnv.ps1 -BackupFile `"$file`""
