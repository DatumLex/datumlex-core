$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$pythonExe = Join-Path $backendRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Execute scripts/setup.ps1 primeiro.' }
if (-not (Test-Path -LiteralPath (Join-Path $backendRoot '.env'))) { throw 'Configure backend/.env antes da coleta.' }
& $pythonExe (Join-Path $backendRoot 'scripts\scheduled_datajud_sync.py')
if ($LASTEXITCODE -ne 0) { throw 'A coleta terminou com falhas; consulte backend/data/datajud-scheduler.log.' }
