param(
    [ValidateSet('collect','process','all')][string]$Mode='all',
    [ValidateRange(25,1000)][int]$BatchSize=1000,
    [int]$Target=20000,
    [ValidateRange(1,100)][int]$DoctrineLimit=50,
    [string]$Sources='doctrine,pangea,tjdft,ementas,djen',
    [switch]$Once,[switch]$Follow
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$python=Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Execute scripts/setup.ps1 -Migrate primeiro.' }
$arguments=@('-u',(Join-Path $projectRoot 'tools\nlp_validation\elt.py'),'--mode',$Mode,'--batch-size',"$BatchSize",'--target',"$Target",'--doctrine-limit',"$DoctrineLimit",'--sources',$Sources)
if ($Once) { $arguments+='--once' }
if ($Follow) { $arguments+='--follow' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Execucao parcial ou interrompida; consulte backend/data/operations/etl-<modo>.json.' }
