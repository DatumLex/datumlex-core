param([ValidateSet('Install','Start','Stop','Backup')][string]$Action = 'Install')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Docker {
    & $script:Docker @args
    if ($LASTEXITCODE -ne 0) { throw 'O Docker informou uma falha. Consulte a mensagem acima.' }
}
function Invoke-Compose {
    Invoke-Docker compose --project-directory $PSScriptRoot --env-file "$PSScriptRoot\.env" -f "$PSScriptRoot\compose.yaml" @args
}
function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()
}
function Write-Utf8([string]$Path, [string]$Value) {
    [IO.File]::WriteAllText($Path, $Value, (New-Object Text.UTF8Encoding($false)))
}
function Find-Docker {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @("$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe")) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}
function Wait-Docker {
    $ErrorActionPreference = 'Continue'
    & $script:Docker info --format '{{.OSType}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        foreach ($candidate in @("$env:ProgramFiles\Docker\Docker\Docker Desktop.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe")) {
            if (Test-Path -LiteralPath $candidate) { Start-Process -FilePath $candidate -WindowStyle Hidden; break }
        }
        Write-Host 'Aguardando Docker. Conclua a configuracao inicial do Docker Desktop se solicitada.'
        $ready = $false
        for ($i = 0; $i -lt 90; $i++) {
            Start-Sleep -Seconds 4
            & $script:Docker info --format '{{.OSType}}' 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        }
        if (-not $ready) { throw 'Abra o Docker Desktop. Se o Windows pedir reinicializacao/WSL, conclua e execute Instalar.cmd novamente.' }
    }
    $ErrorActionPreference = 'Stop'
    $osType = & $script:Docker info --format '{{.OSType}}'
    if ($osType -ne 'linux') { throw 'No Docker Desktop, selecione Linux containers.' }
    Invoke-Docker compose version
}

try {
    # Copy only a distribution made by build-package.py, never the developer workspace.
    $installRoot = Join-Path $env:LOCALAPPDATA 'DatumLexServer'
    $targetScripts = Join-Path $installRoot 'deploy\local-server'
    if ($Action -eq 'Install' -and [IO.Path]::GetFullPath($PSScriptRoot) -ne [IO.Path]::GetFullPath($targetScripts)) {
        $packageRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
        if (-not (Test-Path "$packageRoot\DISTRIBUTION.txt")) { throw 'Use o ZIP de distribuicao gerado por build-package.py.' }
        New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
        foreach ($item in @('backend','frontend','deploy','.dockerignore','DISTRIBUTION.txt')) {
            Copy-Item -LiteralPath (Join-Path $packageRoot $item) -Destination $installRoot -Recurse -Force
        }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$targetScripts\Servidor.ps1" -Action Install
        exit $LASTEXITCODE
    }
    $script:Docker = Find-Docker
    if (-not $script:Docker) {
        if ($Action -ne 'Install') { throw 'Docker Desktop nao encontrado. Execute Instalar.cmd.' }
        if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
            throw 'Instale Docker Desktop em https://docs.docker.com/desktop/setup/install/windows-install/ e execute Instalar.cmd novamente.'
        }
        Write-Host 'Instalando Docker Desktop. O Windows pode solicitar permissao ou reinicializacao.'
        & winget.exe install --exact --id Docker.DockerDesktop --source winget
        if ($LASTEXITCODE -ne 0) { throw 'Conclua a instalacao do Docker Desktop e execute Instalar.cmd novamente.' }
        $script:Docker = Find-Docker
        if (-not $script:Docker) { throw 'Reinicie o Windows e execute Instalar.cmd novamente.' }
    }
    Wait-Docker
    if ($Action -eq 'Install' -and -not (Test-Path "$PSScriptRoot\.env")) {
        Write-Host 'Enderecos IPv4 desta maquina (reserve o escolhido no roteador):'
        Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } | Format-Table InterfaceAlias,IPAddress
        $serverIP = (Read-Host 'Digite o IPv4 do servidor na rede local').Trim()
        $ip = [Net.IPAddress]::Parse($serverIP)
        if ($ip.AddressFamily -ne 'InterNetwork' -or $serverIP -notmatch '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)') { throw 'Informe um IPv4 privado da rede local.' }
        if (-not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $serverIP)) { throw 'O endereco nao pertence a esta maquina.' }
        # Restrict installation files, including generated credentials, to this Windows user and administrators.
        $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        & icacls.exe $installRoot /inheritance:r /grant:r "*${sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel proteger a pasta de instalacao.' }
        $support = New-Secret
        $content = "SERVER_HOST=$serverIP`nPOSTGRES_PASSWORD=$(New-Secret)`nDJANGO_SECRET_KEY=$(New-Secret)`nDATUMLEX_SUPPORT_PASSWORD=$support`nDATAJUD_API_KEY=`n"
        Write-Utf8 "$PSScriptRoot\.env" $content
        Write-Utf8 "$installRoot\ACESSO-INICIAL.txt" "Endereco: https://$serverIP`r`nUsuario: suport`r`nSenha: $support`r`nGuarde este arquivo em local privado. Crie os usuarios pelo menu Usuarios.`r`n"
    }
    if (-not (Test-Path "$PSScriptRoot\.env")) { throw 'Execute Instalar.cmd primeiro.' }
    $hostLine = Get-Content "$PSScriptRoot\.env" | Where-Object { $_ -match '^SERVER_HOST=' } | Select-Object -First 1
    $serverIP = $hostLine.Substring('SERVER_HOST='.Length)
    if ($Action -eq 'Stop') { Invoke-Compose stop; exit 0 }
    if ($Action -eq 'Backup') {
        $backupDir = Join-Path $installRoot 'backups'
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        Invoke-Compose exec -T db pg_dump -U datumlex -d datumlex -Fc -f /tmp/datumlex-backup.dump
        Invoke-Compose cp db:/tmp/datumlex-backup.dump "$backupDir\datumlex-$stamp.dump"
        Write-Host "Backup salvo em $backupDir. Copie para outra unidade ou maquina."
        exit 0
    }
    if ($Action -eq 'Install') {
        Invoke-Compose up -d --build --wait --wait-timeout 300
        Write-Host 'Configurando acesso pela rede local. Autorize a janela do Windows.'
        $firewall = Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\Firewall.ps1`" -ServerIP $serverIP"
        if ($firewall.ExitCode -ne 0) { throw 'Falha ao liberar o firewall. Execute Instalar.cmd novamente e autorize.' }
    } else {
        Invoke-Compose up -d --wait --wait-timeout 300
    }
    $clientDir = Join-Path $installRoot 'clientes'
    New-Item -ItemType Directory -Path $clientDir -Force | Out-Null
    # Export the PUBLIC certificate only; the CA private key remains in the Docker volume.
    Invoke-Compose cp web:/data/caddy/pki/authorities/local/root.crt "$clientDir\DatumLex-Raiz.crt"
    Import-Certificate -FilePath "$clientDir\DatumLex-Raiz.crt" -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
    Write-Utf8 "$clientDir\DatumLex.url" "[InternetShortcut]`r`nURL=https://$serverIP`r`n"
    Copy-Item "$PSScriptRoot\Configurar-Cliente.cmd" $clientDir -Force
    Copy-Item "$PSScriptRoot\Configurar-Cliente.ps1" $clientDir -Force
    # Validate TLS and health before reporting a successful installation.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $response = Invoke-WebRequest -UseBasicParsing -Uri "https://$serverIP/api/health/" -TimeoutSec 30
    if ($response.StatusCode -ne 200) { throw 'O servidor nao passou na verificacao de saude.' }
    if ($Action -eq 'Install') {
        $desktop = [Environment]::GetFolderPath('Desktop')
        $shell = New-Object -ComObject WScript.Shell
        foreach ($name in @('Iniciar','Parar','Backup')) {
            $shortcut = $shell.CreateShortcut("$desktop\DatumLex - $name.lnk")
            $shortcut.TargetPath = "$PSScriptRoot\$name.cmd"
            $shortcut.WorkingDirectory = $PSScriptRoot
            $shortcut.Save()
        }
        Copy-Item "$clientDir\DatumLex.url" "$desktop\DatumLex.url" -Force
        Write-Host "Instalacao concluida. Credenciais: $installRoot\ACESSO-INICIAL.txt"
        Write-Host "Copie SOMENTE a pasta $clientDir para os computadores clientes."
        Write-Host 'No Docker Desktop, ative iniciar ao entrar no Windows. Os containers retomam quando o Docker iniciar.'
    }
    Write-Host "DatumLex disponivel em https://$serverIP"
    Start-Process "https://$serverIP"
} catch {
    Write-Host "ERRO: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'A instalacao pode ser retomada executando Instalar.cmd. Dados e senhas existentes sao preservados.'
    exit 1
}
