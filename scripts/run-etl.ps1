param(
    [ValidateSet('collect','process','all')][string]$Mode='all',
    [ValidateRange(25,1000)][ValidateScript({ $_ % 25 -eq 0 })][int]$BatchSize=1000,
    [ValidateRange(1,2147483647)][int]$Target=20000,
    [ValidateRange(1,100)][int]$DoctrineLimit=50,
    [ValidatePattern('^(doctrine|pangea|tjdft|ementas|djen)(,(doctrine|pangea|tjdft|ementas|djen))*$')]
    [string]$Sources='doctrine,pangea,tjdft,ementas,djen',
    [switch]$Once,[switch]$Follow
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$python=Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/setup.ps1 -BackendOnly -Migrate first.' }
& $python (Join-Path $projectRoot 'backend/scripts/check_etl_setup.py')
if ($LASTEXITCODE -ne 0) { throw 'ETL setup is not ready. Correct the reported issue before collecting.' }
$arguments=@('-u',(Join-Path $projectRoot 'tools\nlp_validation\elt.py'),'--mode',$Mode,'--batch-size',"$BatchSize",'--target',"$Target",'--doctrine-limit',"$DoctrineLimit",'--sources',$Sources)
if ($Once) { $arguments+='--once' }
if ($Follow) { $arguments+='--follow' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'The cycle ended with a failure. Check scripts/status.ps1 and backend/data/operations/etl-logs.' }
