param([switch]$Migrate, [switch]$SkipDependencies)
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
    Write-Host 'Arquivo backend/.env criado a partir do exemplo. Preencha as configurações locais antes da coleta.'
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & python -m venv (Join-Path $backendRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente Python. Instale Python compatível.' }
}
if (-not $SkipDependencies) {
    & $pythonExe -m pip install -r (Join-Path $backendRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Falha na instalação das dependências Python.' }
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Falha no npm ci. Confira Node.js, npm e conectividade.' }
    } finally { Pop-Location }
}
if ($Migrate) {
    Push-Location $backendRoot
    try {
        & $pythonExe -c "import os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; from django.conf import settings; c=settings.DATABASES['default']; assert c['ENGINE']=='django.db.backends.sqlite3' or c.get('HOST') in ('localhost','127.0.0.1','::1'), 'Setup only supports a local database'"
        if ($LASTEXITCODE -ne 0) { throw 'A configuração não aponta para banco local.' }
        & $pythonExe manage.py migrate --noinput
        if ($LASTEXITCODE -ne 0) { throw 'Falha nas migrações. Confira banco e configurações de suporte.' }
        & $pythonExe manage.py register_courts
        if ($LASTEXITCODE -ne 0) { throw 'Falha no cadastro dos tribunais oficiais.' }
    } finally { Pop-Location }
}
Write-Host 'Instalação preparada. Configure backend/.env; para PostgreSQL, inicie o Compose e execute setup.ps1 -Migrate -SkipDependencies.'
