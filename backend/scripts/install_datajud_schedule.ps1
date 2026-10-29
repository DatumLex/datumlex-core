param(
    [string]$At = '19:40',
    [string]$TaskName,
    [switch]$RunNow,
    [int]$Target = 20000
)
$ErrorActionPreference = 'Stop'

$backendRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $backendRoot '.venv\Scripts\python.exe'
$runner = Join-Path (Split-Path -Parent $backendRoot) 'tools\nlp_validation\collect_until_target.py'
if (-not $TaskName) {
    $pathBytes = [Text.Encoding]::UTF8.GetBytes($backendRoot.ToLowerInvariant())
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $suffix = ([BitConverter]::ToString($hasher.ComputeHash($pathBytes))).Replace('-', '').Substring(0, 8) }
    finally { $hasher.Dispose() }
    $TaskName = "DatumLex-Local-$suffix"
}
$scheduledTime = [DateTime]::ParseExact($At, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python do ambiente virtual não encontrado: $python"
}
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Agendador do DatumLex não encontrado: $runner"
}

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$runner`" --target $Target" `
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
    -Description "Retoma jurisprudência local até $Target textos únicos; encerra ao atingir a meta." `
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
Write-Host "Tarefa '$TaskName' instalada para $At, no horário configurado no Windows."
Write-Host "Log: $(Join-Path $backendRoot 'data\datajud-scheduler.log')"
