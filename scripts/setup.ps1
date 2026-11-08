param([switch]$Migrate, [switch]$SkipDependencies, [switch]$BackendOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$pythonExe = Join-Path $backendRoot '.venv\Scripts\python.exe'
$envFile = Join-Path $backendRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $backendRoot '.env.example') -Destination $envFile
    $secretBytes = New-Object byte[] 48
    $supportBytes = New-Object byte[] 32
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($secretBytes); $random.GetBytes($supportBytes) } finally { $random.Dispose() }
    $envText = [System.IO.File]::ReadAllText($envFile)
    $envText = $envText.Replace('DJANGO_SECRET_KEY=local-development-only-datumlex', ('DJANGO_SECRET_KEY=' + [Convert]::ToBase64String($secretBytes)))
    $envText = $envText.Replace('DATUMLEX_SUPPORT_PASSWORD=', ('DATUMLEX_SUPPORT_PASSWORD=' + [Convert]::ToBase64String($supportBytes)))
    [System.IO.File]::WriteAllText($envFile, $envText)
    Write-Host 'Created backend/.env from the example. Review the local configuration before collecting.'
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c "import sys; assert sys.version_info >= (3, 12), 'Python 3.12 or later is required'"
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or later.' }
        & py -3 -m venv (Join-Path $backendRoot '.venv')
    } else {
        & python -c "import sys; assert sys.version_info >= (3, 12), 'Python 3.12 or later is required'"
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or later.' }
        & python -m venv (Join-Path $backendRoot '.venv')
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment. Install a compatible Python version.' }
}
if (-not $SkipDependencies) {
    & $pythonExe -m pip install -r (Join-Path $backendRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    if (-not $BackendOnly) {
        Push-Location (Join-Path $projectRoot 'frontend')
        try {
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Check Node.js, npm, and connectivity.' }
        } finally { Pop-Location }
    }
}
if ($Migrate) {
    Push-Location $backendRoot
    try {
        & $pythonExe -c "import os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; from django.conf import settings; c=settings.DATABASES['default']; assert c['ENGINE']=='django.db.backends.sqlite3' or c.get('HOST') in ('localhost','127.0.0.1','::1'), 'Setup only supports a local database'"
        if ($LASTEXITCODE -ne 0) { throw 'Setup requires a local database configuration.' }
        & $pythonExe manage.py migrate --noinput
        if ($LASTEXITCODE -ne 0) { throw 'Migrations failed. Check the database and support configuration.' }
        & $pythonExe manage.py register_courts
        if ($LASTEXITCODE -ne 0) { throw 'Could not register the court catalog.' }
    } finally { Pop-Location }
}
Write-Host 'Setup finished. Review backend/.env and run setup.ps1 -Migrate -SkipDependencies if migrations were not selected.'
Write-Host 'Run one collection with scripts/run-etl.ps1 -Once. Use scripts/install-schedule.ps1 to enable daily runs.'
