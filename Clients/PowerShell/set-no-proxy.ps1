# Update NO_PROXY only; preserve proxy endpoints, credentials and custom exclusions.
# Self-contained; save as UTF-8 with BOM for Windows PowerShell 5.1.
$ErrorActionPreference = 'Stop'
$noProxyDefaults = 'localhost,.localhost,.local,.localdomain,.home.arpa,.ru,.su,.рф,.xn--p1ai,127.0.0.1,::1,[::1],::,0.0.0.0/8,10.0.0.0/8,100.64.0.0/10,127.0.0.0/8,169.254.0.0/16,172.16.0.0/12,192.0.0.0/24,192.0.2.0/24,192.168.0.0/16,198.18.0.0/15,198.51.100.0/24,203.0.113.0/24,224.0.0.0/3,64:ff9b:1::/48,100::/63,2001:2::/48,2001:10::/28,2001:20::/27,2001:db8::/32,3fff::/20,5f00::/16,fc00::/6'
$noProxyUser = [Environment]::GetEnvironmentVariable('NO_PROXY', 'User')
$noProxyProcess = [Environment]::GetEnvironmentVariable('NO_PROXY', 'Process')
$noProxyEntries = @(
  ($noProxyDefaults + ',' + $noProxyUser + ',' + $noProxyProcess) -split ',' |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ } |
    Select-Object -Unique
)
$noProxyValue = $noProxyEntries -join ','
[Environment]::SetEnvironmentVariable('NO_PROXY', $noProxyValue, 'User')
[Environment]::SetEnvironmentVariable('NO_PROXY', $noProxyValue, 'Process')
