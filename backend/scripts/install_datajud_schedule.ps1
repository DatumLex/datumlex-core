$ErrorActionPreference = 'Stop'

$backendRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $backendRoot '.venv\Scripts\python.exe'
$runner = Join-Path $backendRoot 'scripts\scheduled_datajud_sync.py'
$taskName = 'DatumLex DataJud TJDFT-STJ'

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
    -Argument "`"$runner`"" `
    -WorkingDirectory $backendRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '2:00 AM'
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask `
    -TaskName $taskName `
    -Description 'Sincroniza diariamente DataJud TJDFT/STJ e precedentes STJ do BNP/Pangea para o DatumLex.' `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force `
    -ErrorAction Stop | Out-Null

if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    throw "A tarefa '$taskName' não foi encontrada após o registro."
}

Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
Write-Host "Tarefa '$taskName' instalada e iniciada. A rotina continuará diariamente às 2h."
Write-Host "Log: $(Join-Path $backendRoot 'data\datajud-scheduler.log')"
