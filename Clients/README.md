# Клиентские конфигурации для AI Proxy

Примеры конфигураций клиентов для работы с AI-ассистентами через корпоративный прокси-сервер.

## Структура

```
Clients/
├── Claude/          # Конфигурация для Claude Code (VSCode)
├── Gemini/          # Конфигурация для Gemini Code Assist (VSCode)
├── FoxyProxy/       # Конфигурация для FoxyProxy (браузер)
└── PowerShell/
    ├── register-vars.ps1   # Установка переменных окружения
    └── unregister-vars.ps1 # Удаление переменных окружения
```

## Настройки VSCode

Для открытия файла `settings.json` в VSCode используйте:
- **Комбинация клавиш:** `Ctrl+Shift+P` → введите `Preferences: Open User Settings (JSON)`
- **Или меню:** File → Preferences → Settings → иконка `{}` в правом верхнем углу
- **Консольная команда открытия файла:**
  ```powershell
  code "$env:APPDATA\Code\User\settings.json"
  ```


### Claude

Добавьте в пользовательские настройки VSCode (`settings.json`) объект из файла [`Claude/settings.json`](Claude/settings.json).

### Gemini

Добавьте в пользовательские настройки VSCode (`settings.json`) объект из файла [`Gemini/settings.json`](Gemini/settings.json).

> **Примечание:** Замените `MY_PROJECT_ID` на идентификатор вашего проекта в Google Cloud.

## FoxyProxy (настройка браузера)

Файл [`FoxyProxy/FoxyProxy.json`](FoxyProxy/FoxyProxy.json) содержит конфигурацию для браузерного расширения [FoxyProxy](https://getfoxyproxy.org/).

Конфигурация настраивает проксирование только для AI-сервисов:
- **Gemini** — gemini.google.com, aistudio.google.com, googleapis.com
- **ChatGPT** — chatgpt.com, openai.com
- **Claude** — claude.ai, anthropic.com
- **Grok** — grok.com
- **X AI** — x.ai
- **DeepL** — deepl.com
- **Alibaba Cloud AI** — dashscope.aliyuncs.com, alibabacloud.com
- **Microsoft AI** — bing.com, copilot.microsoft.com, azure OpenAI и др.
- **Cursor** — cursor.sh, cursor.com
- **GitHub Copilot** — github.com, githubcopilot.com, copilot-proxy.githubusercontent.com
- **CloudFlare** — cloudflare.com
- **VSCode CDN** — vscode-cdn.net
- **Все домены зоны .ai**

### Импорт конфигурации

1. Установите расширение FoxyProxy для вашего браузера
2. Отредактируйте файл `FoxyProxy.json`, заменив:
   - `ai-proxy.example.com` — на адрес корпоративного прокси-сервера
   - `USERNAME` и `PASSWORD` — на ваши учетные данные
3. Откройте настройки расширения
4. Перейдите в раздел **Import** → **Import from URL or file**
5. Выберите отредактированный файл `FoxyProxy.json`

> **Альтернативно:** можно импортировать файл без изменений, а затем отредактировать адрес прокси и учетные данные напрямую в интерфейсе настроек FoxyProxy.

## PowerShell (настройка CLI окружения PowerShell)

Назначение персистентных переменных окружения в Windows PowerShell. Применяйте в крайнем случае, так как их действие глобальнее, чем примеры конфигурации выше, и может повлиять на другие приложения.

### Регистрация переменных окружения скриптом или в консоли PowerShell

Скрипт [`PowerShell/register-vars.ps1`](PowerShell/register-vars.ps1) устанавливает переменные окружения прокси на уровне пользователя Windows.

В этом скрипте:
1. Замените `user:password` на ваши учетные данные
2. Замените `ai-proxy.example.com:443` на адрес корпоративного прокси-сервера (AI proxy)
3. При необходимости добавьте дополнительные адреса в `NO_PROXY`

Установка переменной для текущего пользователя:
```powershell
[Environment]::SetEnvironmentVariable("...", "...", "User")
```
Если нужно совсем глобально, то для установки на уровне всей системы используйте "Machine" вместо "User". В этом случае вам потребуются права администратора.

После выполнения скрипта необходимо перелогиниться (для User) или перезагрузить систему (для Machine), для применения настроек.

#### Удаление переменных окружения

Скрипт [`PowerShell/unregister-vars.ps1`](PowerShell/unregister-vars.ps1) удаляет ранее установленные переменные окружения прокси

### Альтернативный способ - настройка профиля PowerShell

Альтернативный способ — добавить переменные окружения в профиль PowerShell. Они будут устанавливаться при каждом запуске сессии PowerShell.

**Расположение файла профиля:**
- PowerShell Core: `$HOME\Documents\PowerShell\Microsoft.PowerShell_profile.ps1`
- Windows PowerShell: `$HOME\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`

Проверить путь к профилю можно командой:
```powershell
$PROFILE
```

Если файл не существует, создайте его:
```powershell
New-Item -Path $PROFILE -ItemType File -Force
```

Добавьте в файл профиля следующие строки:

```powershell
# AI Proxy - переменные окружения
$env:HTTP_PROXY = "http://user:password@proxy.example.com:443"
$env:HTTPS_PROXY = "http://user:password@proxy.example.com:443"
$env:NO_PROXY = "localhost,127.0.0.1,::1,.local"
```

> **Примечание:** В отличие от `[Environment]::SetEnvironmentVariable()`, переменные через `$env:` устанавливаются только для текущей сессии PowerShell и её дочерних процессов. Это удобно, если вы не хотите применять прокси глобально ко всей системе.

Для применения изменений перезапустите PowerShell или выполните:
```powershell
. $PROFILE
```

**Для удаления переменных** в этом сценарии достаточно очистить отредактированный вами файл профиля.
