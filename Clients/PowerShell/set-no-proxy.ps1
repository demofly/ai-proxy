# Update NO_PROXY only; preserve proxy endpoints, credentials and custom exclusions.
# Explicit UTF-8 decoding also supports Windows PowerShell 5.1 without a BOM.
$ErrorActionPreference = 'Stop'
$noProxyPath = Join-Path $PSScriptRoot '..\no_proxy.txt'
$noProxyDefaults = [IO.File]::ReadAllText($noProxyPath, [Text.Encoding]::UTF8).Trim()
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
