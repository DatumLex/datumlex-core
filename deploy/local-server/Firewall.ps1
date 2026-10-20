param([Parameter(Mandatory=$true)][string]$ServerIP)
$ErrorActionPreference = 'Stop'
try {
    $ip = [System.Net.IPAddress]::Parse($ServerIP)
    if ($ip.AddressFamily -ne 'InterNetwork') { throw 'IPv4 necessario.' }
    if (-not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $ServerIP)) {
        throw 'O IP precisa pertencer a este servidor.'
    }
    $ruleName = 'DatumLex-HTTPS-Local'
    if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
        Set-NetFirewallRule -Name $ruleName -Enabled True -Profile Private,Domain -Action Allow
        Get-NetFirewallRule -Name $ruleName | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress $ServerIP -RemoteAddress LocalSubnet
    } else {
        New-NetFirewallRule -Name $ruleName -DisplayName 'DatumLex HTTPS - rede local' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 443 -LocalAddress $ServerIP -RemoteAddress LocalSubnet -Profile Private,Domain | Out-Null
    }
} catch { Write-Error $_; exit 1 }
