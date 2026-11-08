$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$pythonExe=Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Execute scripts/setup.ps1 -Migrate primeiro.' }
& $pythonExe -u (Join-Path $projectRoot 'tools\nlp_validation\collect_other_courts.py')
if ($LASTEXITCODE -ne 0) { throw 'Carga parcial: consulte backend/data/operations/other-courts-collection.json.' }
