param([ValidateRange(1,100)][int]$DoctrineLimit=50,[int]$JurisprudenceTarget=20000)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$pythonExe=Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Execute scripts/setup.ps1 -Migrate primeiro.' }
& $pythonExe -u (Join-Path $projectRoot 'tools\nlp_validation\collect_priority.py') --doctrine-limit $DoctrineLimit --jurisprudence-target $JurisprudenceTarget
if ($LASTEXITCODE -ne 0) { throw 'Carga parcial: consulte backend/data/operations/priority-collection.json.' }
