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

[Environment]::SetEnvironmentVariable(
  "NO_PROXY",
  "localhost,127.0.0.1,::1,.local",
  "User"
)
