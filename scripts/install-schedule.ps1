[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$At = '19:40',
    [string]$TaskName,
    [ValidateRange(1,2147483647)][int]$Target = 20000,
    [ValidateRange(25,1000)][ValidateScript({ $_ % 25 -eq 0 })][int]$BatchSize = 1000,
    [ValidateRange(1,100)][int]$DoctrineLimit = 50,
    [ValidatePattern('^(doctrine|pangea|tjdft|ementas|djen)(,(doctrine|pangea|tjdft|ementas|djen))*$')]
    [string]$Sources = 'doctrine,pangea,tjdft,ementas,djen',
    [switch]$RunNow
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $projectRoot 'backend\scripts\install_datajud_schedule.ps1') `
    -At $At -TaskName $TaskName -Target $Target -BatchSize $BatchSize `
    -DoctrineLimit $DoctrineLimit -Sources $Sources -RunNow:$RunNow -WhatIf:$WhatIfPreference
