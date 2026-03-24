<!-- [AIGD] -->
# DE-CR-001 — Учётные данные прокси (Credentials)

## Описание

Учётные данные прокси — пары логин/хеш пароля для аутентификации пользователей на access-прокси через HTTP Basic Auth. Хранятся в файле `/etc/squid/passwd` в формате htpasswd (NCSA). Используются Squid-хелпером `basic_ncsa_auth` для проверки подлинности при каждом CONNECT-запросе.

## Атрибуты

| Атрибут | Тип | Описание | Обязательность |
|---|---|---|---|
| username | string (ASCII, без пробелов) | Имя пользователя, уникальный идентификатор | Обязательный |
| password_hash | string (`$apr1$salt$hash`) | Хеш пароля в формате MD5-crypt (apr1) | Обязательный |
| realm | string | Область аутентификации Squid (задаётся глобально в squid.conf) | Обязательный (в конфигурации) |

## Хранилище

| Параметр | Значение |
|---|---|
| **Путь** | `/etc/squid/passwd` |
| **Формат** | htpasswd (NCSA): одна строка = `username:password_hash` |
| **Кодировка** | ASCII |
| **Файловые права** | 640 (`root:proxy`) |
| **Компонент** | [C3-SA-001](../../C3/C3-SA-001.md) — Squid Access Proxy |
| **Размер записи** | ~50 байт |

**Пример содержимого:**
```
# AI-GENERATED — NOT REVIEWED: SECTION START
john:$apr1$xyz123$abcdefghijklmnopqrstuv
alice:$apr1$abc456$uvwxyz1234567890abcdef
# AI-GENERATED — NOT REVIEWED: SECTION END
```

## Жизненный цикл

| Стадия | Действие | Актор | Инструмент |
|---|---|---|---|
| **Create** | Создание учётной записи | DevOps-инженер | `htpasswd -b /etc/squid/passwd <user> <pass>` |
| **Use** | Аутентификация запросов | Squid (`basic_ncsa_auth`) | Автоматически при CONNECT |
| **Update** | Смена пароля | DevOps-инженер | `htpasswd -b /etc/squid/passwd <user> <new_pass>` |
| **Archive** | N/A | — | Учётные записи не архивируются |
| **Dispose** | Удаление пользователя | DevOps-инженер | `htpasswd -D /etc/squid/passwd <user>` |

## Безопасность

| Параметр | Значение |
|---|---|
| **Уровень конфиденциальности** | Высокий |
| **Хеширование** | MD5-crypt (`$apr1$`) — Apache apr1 |
| **Файловые права** | 640 — чтение только root и группа proxy |
| **Ansible** | `no_log: true` для задач с паролями |
| **Передача пароля** | По безопасному каналу, однократно |
| **Логирование** | username логируется в access.log; password никогда не логируется |

**Угрозы:**
- Утечка passwd файла → доступ к хешам (brute-force); митигация: файловые права 640
- Перехват Basic Auth → MITM; митигация: HTTPS CONNECT tunnel (TLS до целевого сервера)
- Утечка через лог Ansible → `no_log: true`

## Связанные требования

- [C2-FR-002](../../C2/C2-FR-002.md) — Аутентификация и авторизация
- [C2-NF-002](../../C2/C2-NF-002.md) — Безопасность
- [C3-SA-001](../../C3/C3-SA-001.md) — Squid Access Proxy (компонент, использующий credentials)
<!-- [/AIGD] -->
