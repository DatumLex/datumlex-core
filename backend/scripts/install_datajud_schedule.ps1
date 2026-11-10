[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$At = '19:40',
    [string]$TaskName,
    [switch]$RunNow,
    [ValidateRange(1,2147483647)][int]$Target = 20000,
    [ValidateRange(25,1000)][ValidateScript({ $_ % 25 -eq 0 })][int]$BatchSize = 1000,
    [ValidateRange(1,100)][int]$DoctrineLimit = 50,
    [ValidatePattern('^(doctrine|pangea|tjdft|ementas|djen)(,(doctrine|pangea|tjdft|ementas|djen))*$')]
    [string]$Sources = 'doctrine,pangea,tjdft,ementas,djen'
)
$ErrorActionPreference = 'Stop'

$backendRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $backendRoot '.venv\Scripts\python.exe'
$runner = Join-Path (Split-Path -Parent $backendRoot) 'scripts\run-etl.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not $TaskName) {
    $pathBytes = [Text.Encoding]::UTF8.GetBytes($backendRoot.ToLowerInvariant())
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $suffix = ([BitConverter]::ToString($hasher.ComputeHash($pathBytes))).Replace('-', '').Substring(0, 8) }
    finally { $hasher.Dispose() }
    $TaskName = "DatumLex-Local-$suffix"
}
$scheduledTime = [DateTime]::ParseExact($At, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)

if (-not (Test-Path -LiteralPath $powershell)) {
    throw 'Windows PowerShell is required for the scheduled ETL entry point.'
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    $ownedActions = @($existing.Actions | Where-Object {
        $_.WorkingDirectory -and
        [IO.Path]::GetFullPath($_.WorkingDirectory).TrimEnd('\','/') -eq $backendRoot.TrimEnd('\','/')
    })
    if ($ownedActions.Count -ne @($existing.Actions).Count -or $ownedActions.Count -eq 0) {
        throw 'The task name belongs to another installation. Choose another TaskName.'
    }
}

$arguments = "-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -WindowStyle Hidden -File `"$runner`" -Mode all -Once -Target $Target -BatchSize $BatchSize -DoctrineLimit $DoctrineLimit -Sources $Sources"
[pscustomobject]@{
    TaskName = $TaskName
    Execute = $powershell
    Arguments = $arguments
    WorkingDirectory = $backendRoot
    DailyAt = $At
}
if (-not $PSCmdlet.ShouldProcess($TaskName, 'Install or update the daily ETL/NLP schedule')) { return }

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment Python was not found at $python. Run scripts/setup.ps1 first."
}
if (-not (Test-Path -LiteralPath $runner)) {
    throw "The ETL runner was not found at $runner."
}
& $python (Join-Path $backendRoot 'scripts\check_etl_setup.py')
if ($LASTEXITCODE -ne 0) { throw 'Prepare the ETL installation before enabling its schedule.' }

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument $arguments `
    -WorkingDirectory $backendRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $scheduledTime
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask `
    -TaskName $taskName `
    -Description "DatumLex ETL/NLP daily cycle for this clone; TJDFT target $Target." `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force `
    -ErrorAction Stop | Out-Null

if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    throw "A tarefa '$taskName' não foi encontrada após o registro."
}

if ($RunNow) { Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop }
Write-Host "Task '$TaskName' installed for $At in the Windows time zone."
Write-Host "Status: $(Join-Path $backendRoot 'data\operations\etl-all.json')"
Write-Host "Logs: $(Join-Path $backendRoot 'data\operations\etl-logs')"
