<!-- [AIGD] -->
# DE-CF-001 — Конфигурационные параметры

## Описание

Конфигурационные параметры — переменные Ansible inventory, определяющие поведение всех компонентов системы AI Assistants Proxy. Inventory.yml является единственным источником истины (SSOT) для конфигурации. Параметры пропагируются через Jinja2-шаблоны на целевые серверы.

## Атрибуты

| Атрибут | Тип | Описание | Обязательность |
|---|---|---|---|
| name | string | Имя параметра (ключ YAML) | Обязательный |
| value | any (string, integer, boolean, list, map) | Значение параметра | Обязательный |
| type | enum {string, integer, boolean, list, map} | Тип данных значения | Обязательный (определяется YAML) |
| default | any | Значение по умолчанию (из defaults/main.yml роли) | Необязательный |
| scope | enum {access, upstream, global} | Область применения | Обязательный (определяется секцией YAML) |

## Хранилище

| Параметр | Значение |
|---|---|
| **Путь (SSOT)** | `Servers/deploy/inventory.yml` |
| **Формат** | YAML |
| **Кодировка** | UTF-8 |
| **Управление** | Git (VCS) |

## Структура параметров по scope

### Global (`all.vars`)

| Параметр | Тип | Значение по умолчанию | Описание |
|---|---|---|---|
| `ansible_user` | string | `root` | Пользователь SSH для Ansible |
| `ansible_python_interpreter` | string | `/usr/bin/python3` | Путь к Python |
| `read_timeout` | string | `30 minutes` | Таймаут чтения для долгих API |
| `crowdsec_enabled` | boolean | `true` | Включение CrowdSec IPS |
| `crowdsec_memory_mb` | integer | `512` | Лимит памяти CrowdSec (МБ) |
| `crowdsec_fw_bouncer_memory_mb` | integer | `128` | Лимит памяти bouncer (МБ) |
| `mtproxy_enabled` | boolean | `true` | Включение MTProxy |
| `mtproxy_fake_tls_domain` | string | `example.gov.ru` | Fake-TLS домен для DPI |
| `mtproxy_hostname` | string | `tgproxy.example.com` | Публичный домен MTProxy |
| `mtproxy_version` | string | `2.1.8` | Версия mtg |
| `mtproxy_local_port` | integer | `2083` | Локальный порт mtg |
| `mtproxy_secret` | string (hex) | — | Секрет MTProxy |
| `mtproxy_max_connections` | integer | `100` | Макс. подключений per IP |
| `dns_servers` | list[string] | `[9.9.9.9, 8.8.8.8, 1.1.1.1]` | DNS-серверы |
| `allowed_domains` | list[string] | — | Белый список доменов (exact) |
| `allowed_domain_patterns` | list[string] | — | Белый список доменов (regex) |

### Access (`access_proxies.vars`)

| Параметр | Тип | Значение по умолчанию | Описание |
|---|---|---|---|
| `proxy_role` | string | `access` | Роль прокси |
| `squid_port` | integer | `443` | Публичный порт Squid |
| `enable_auth` | boolean | `true` | Включение аутентификации |
| `enable_logging` | boolean | `true` | Включение журналирования |
| `enable_caching` | boolean | `true` | Включение кеширования |
| `behind_nginx` | boolean | `true` | Squid за nginx |
| `squid_local_port` | integer | `3128` | Локальный порт Squid (за nginx) |
| `enable_keepalived` | boolean | `true` | Включение Keepalived |
| `keepalived_vip` | string (IPv4) | `1.2.3.4` | Виртуальный IP |
| `keepalived_vrid` | integer | `51` | VRRP Router ID |
| `keepalived_auth_pass` | string | — | Пароль VRRP |

### Access hosts (per-host)

| Параметр | Тип | Описание |
|---|---|---|
| `ansible_host` | string (IPv4) | IP-адрес хоста |
| `keepalived_state` | enum {MASTER, BACKUP} | Роль в VRRP |
| `keepalived_priority` | integer (1–255) | Приоритет VRRP |

### Upstream (`upstreams.vars`)

| Параметр | Тип | Значение по умолчанию | Описание |
|---|---|---|---|
| `proxy_role` | string | `upstream` | Роль прокси |
| `squid_port` | integer | `80` | Порт Squid (напрямую, без nginx) |
| `enable_auth` | boolean | `false` | Аутентификация отключена |
| `enable_logging` | boolean | `false` | Журналирование отключено |
| `enable_caching` | boolean | `false` | Кеширование отключено |

## Жизненный цикл

| Стадия | Действие | Актор | Инструмент |
|---|---|---|---|
| **Create** | Определение параметров | DevOps-инженер | Текстовый редактор |
| **Store** | VCS + рендеринг на серверы | Git + Ansible | Jinja2 templates |
| **Use** | Чтение сервисными процессами | Squid, nginx, Keepalived, mtg, CrowdSec | Парсеры конфигураций |
| **Update** | Изменение inventory + re-deploy | DevOps-инженер + Ansible | playbook re-run |
| **Archive** | Git history | VCS | Git |
| **Dispose** | Удаление параметра + re-deploy | DevOps-инженер + Ansible | playbook re-run |

## Безопасность

| Параметр | Значение |
|---|---|
| **Уровень конфиденциальности** | Низкий-Средний |
| **Обоснование** | Содержит IP-адреса серверов и параметры инфраструктуры |
| **Чувствительные параметры** | `mtproxy_secret`, `keepalived_auth_pass` → см. [DE-SC-001](DE-SC-001.md) |
| **Контроль изменений** | Git (VCS) — полная история |

## Связанные требования

- [C2-FR-008](../../C2/C2-FR-008.md) — Автоматизированное развёртывание (Ansible)
- [C2-FR-001](../../C2/C2-FR-001.md) — Проксирование (cache_peer, squid_port)
- [C2-NF-001](../../C2/C2-NF-001.md) — Высокая доступность (keepalived_*)
- [C2-NF-003](../../C2/C2-NF-003.md) — Производительность (SMP, memory)
- [C3-AD-001](../../C3/C3-AD-001.md) — Ansible Deployment System
<!-- [/AIGD] -->
