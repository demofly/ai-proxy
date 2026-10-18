[Environment]::SetEnvironmentVariable(
  "HTTP_PROXY",
  "http://user:password@proxy.example.com:443",
  "User"      # или "Machine" для всей системы
)

[Environment]::SetEnvironmentVariable(
  "HTTPS_PROXY",
  "http://user:password@proxy.example.com:443",
  "User"      # или "Machine" для всей системы
)

$ErrorActionPreference = 'Stop'
$noProxyDefaults = 'localhost,.localhost,.local,.localdomain,.home.arpa,.ru,.su,.рф,.xn--p1ai,127.0.0.1,::1,[::1],::,0.0.0.0/8,10.0.0.0/8,100.64.0.0/10,127.0.0.0/8,169.254.0.0/16,172.16.0.0/12,192.0.0.0/29,192.0.0.8/32,192.0.0.170/31,192.0.2.0/24,192.168.0.0/16,198.18.0.0/15,198.51.100.0/24,203.0.113.0/24,224.0.0.0/4,240.0.0.0/4,64:ff9b:1::/48,100::/64,100:0:0:1::/64,2001:2::/48,2001:10::/28,2001:20::/28,2001:30::/28,2001:db8::/32,3fff::/20,5f00::/16,fc00::/7,fe80::/10,fec0::/10,ff00::/8'
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
