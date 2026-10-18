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

& (Join-Path $PSScriptRoot 'set-no-proxy.ps1')
