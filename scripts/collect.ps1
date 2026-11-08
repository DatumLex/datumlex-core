param([ValidateRange(25,1000)][int]$Limit = 1000, [int]$Target = 0)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Execute scripts/setup.ps1 -Migrate primeiro.' }
if ($Target -gt 0) {
    & $pythonExe (Join-Path $projectRoot 'tools\nlp_validation\collect_until_target.py') --target $Target
} else {
    & $pythonExe (Join-Path $projectRoot 'tools\nlp_validation\collect_batch.py') --limit $Limit
}
if ($LASTEXITCODE -ne 0) { throw 'Carga parcial: consulte backend/data/operations/jurisprudence-batch.json. Execute novamente para retomar.' }
