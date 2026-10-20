$ErrorActionPreference = 'Stop'
try {
    Import-Certificate -FilePath (Join-Path $PSScriptRoot 'DatumLex-Raiz.crt') -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
} catch { Write-Error $_; exit 1 }
