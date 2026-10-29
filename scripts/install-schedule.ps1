param([string]$At = '19:40', [switch]$RunNow)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $projectRoot 'backend\scripts\install_datajud_schedule.ps1') -At $At -RunNow:$RunNow
