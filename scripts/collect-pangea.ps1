param(
    [string]$Query = 'responsabilidade civil',
    [string]$Courts = 'STJ,TJDFT,TJSP,TJMG,TJRJ,TJRS,TJPR,TRF1,TRF3,TST',
    [ValidateRange(1,100)][int]$PageSize = 100,
    [ValidateRange(1,1000)][int]$MaxPages = 10,
    [ValidateRange(0,2147483647)][int]$StartPage = 0
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$pythonExe = Join-Path $backendRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Execute scripts/setup.ps1 -Migrate primeiro.' }
Push-Location $backendRoot
try {
    & $pythonExe -c "import os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; from django.conf import settings; c=settings.DATABASES['default']; assert c['ENGINE']=='django.db.backends.sqlite3' or c.get('HOST') in ('localhost','127.0.0.1','::1'), 'Local database required'"
    if ($LASTEXITCODE -ne 0) { throw 'Configure um banco local antes da coleta.' }
    & $pythonExe (Join-Path $projectRoot 'tools\nlp_validation\collect_pangea_raw.py') --query $Query --courts $Courts --page-size $PageSize --max-pages $MaxPages --start-page $StartPage
    if ($LASTEXITCODE -ne 0) { throw 'Coleta bruta parcial; paginas ja arquivadas foram preservadas.' }
    & $pythonExe (Join-Path $projectRoot 'tools\nlp_validation\elt.py') --mode process --sources pangea --once
    if ($LASTEXITCODE -ne 0) { throw 'Importacao interrompida. Confira o historico Pangea antes de retomar.' }
} finally { Pop-Location }
