<!-- [AIGD] -->
# DE-DM-001 — Белый список доменов (Domain Lists)

## Описание

Белый список доменов — перечень разрешённых доменов AI API, определяющий, какие HTTPS-запросы пропускаются через прокси. Все домены, не входящие в список, отклоняются (whitelist-подход). Список определяется в inventory.yml и рендерится в Squid ACL на access-прокси.

Два типа записей:
- **Exact match** (`allowed_domains`) — точное совпадение с доменом (Squid `dstdomain` ACL)
- **Regex match** (`allowed_domain_patterns`) — совпадение по регулярному выражению (Squid `url_regex` ACL)

## Атрибуты

| Атрибут | Тип | Описание | Обязательность |
|---|---|---|---|
| pattern | string | Паттерн домена (FQDN для exact, regex для regex) | Обязательный |
| type | enum {exact, regex} | Тип совпадения | Обязательный (определяется источником) |
| action | enum {allow} | Действие — всегда allow (whitelist) | Обязательный |

## Хранилище

### Источник (SSOT) — inventory.yml

| Параметр | Значение |
|---|---|
| **Путь** | `Servers/deploy/inventory.yml` |
| **Секция** | `all.vars.allowed_domains` (exact), `all.vars.allowed_domain_patterns` (regex) |
| **Формат** | YAML list of strings |

**Пример:**
```yaml
# AI-GENERATED — NOT REVIEWED: SECTION START
allowed_domains:
  - dashscope.aliyuncs.com
  - .alibabacloud.com
  - copilot-proxy.githubusercontent.com

allowed_domain_patterns:
  - '\.ai$'
  - '(^|\.)cloudflare\.com$'
  - '(^|\.)(chatgpt|openai)\.com$'
  - '(^|\.)(claude\.(ai|com)|(anthropic|claudeusercontent)\.com|sentry\.io)$'
# AI-GENERATED — NOT REVIEWED: SECTION END
```

### Целевое хранилище — squid.conf ACL

| Параметр | Значение |
|---|---|
| **Путь** | `/etc/squid/squid.conf` (на access-прокси) |
| **Формат** | Squid ACL directives |
| **Генерация** | Ansible Jinja2 template |
| **Компонент** | [C3-SA-001](../../C3/C3-SA-001.md) — Squid Access Proxy |

**Пример рендеринга:**
```
# AI-GENERATED — NOT REVIEWED: SECTION START
acl allowed_domains dstdomain dashscope.aliyuncs.com .alibabacloud.com copilot-proxy.githubusercontent.com
acl allowed_domain_patterns url_regex \.ai$ (^|\.)cloudflare\.com$ ...
http_access allow CONNECT allowed_domains
http_access allow CONNECT allowed_domain_patterns
http_access deny CONNECT all
# AI-GENERATED — NOT REVIEWED: SECTION END
```

## Жизненный цикл

| Стадия | Действие | Актор | Инструмент |
|---|---|---|---|
| **Create** | Добавление домена в inventory | DevOps-инженер | Текстовый редактор |
| **Store** | Рендеринг в squid.conf ACL | Ansible | Jinja2 template |
| **Use** | Фильтрация CONNECT-запросов | Squid | ACL engine |
| **Update** | Изменение inventory + re-deploy | DevOps-инженер + Ansible | playbook re-run |
| **Archive** | Git history | VCS | Git |
| **Dispose** | Удаление из inventory + re-deploy | DevOps-инженер + Ansible | playbook re-run |

## Безопасность

| Параметр | Значение |
|---|---|
| **Уровень конфиденциальности** | Низкий |
| **Обоснование** | Содержит публичные домены AI API |
| **Файловые права** | 644 (squid.conf) |

## Связанные требования

- [C2-FR-003](../../C2/C2-FR-003.md) — Фильтрация доменов (whitelist)
- [C2-FR-001](../../C2/C2-FR-001.md) — Проксирование запросов к AI API
- [C3-SA-001](../../C3/C3-SA-001.md) — Squid Access Proxy (компонент, применяющий whitelist)
<!-- [/AIGD] -->
