<!-- [AIGD] -->
# DD-Integration — Паттерны интеграции данных

## Описание

Документ описывает паттерны интеграции данных между компонентами проекта AI Assistants Proxy. Все интеграции реализуются через файловый обмен: шаблонизация (Ansible → configs), чтение файлов (CrowdSec → logs), API-взаимодействие (CrowdSec → nftables).

## Паттерны интеграции

### 1. Ansible Inventory → Jinja2 Templates → Target Config Files

**Тип:** Template Rendering (файловая генерация)

| Параметр | Значение |
|---|---|
| **Источник** | `inventory.yml` (SSOT) |
| **Трансформация** | Jinja2 template engine |
| **Приёмник** | Конфигурационные файлы на целевых серверах |
| **Триггер** | Запуск `ansible-playbook playbook.yml` |
| **Направление** | Push (управляющий хост → целевые) |
| **Идемпотентность** | Да (Ansible template module) |

**Потоки данных:**

| inventory.yml переменная | Шаблон (.j2) | Целевой файл | Хост |
|---|---|---|---|
| `allowed_domains`, `allowed_domain_patterns` | squid.conf.j2 | `/etc/squid/squid.conf` | access-прокси |
| `ansible_host` (access) | squid.conf.j2 | `/etc/squid/squid.conf` (ACL) | upstream-прокси |
| `keepalived_*` | keepalived.conf.j2 | `/etc/keepalived/keepalived.conf` | access-прокси |
| `mtproxy_*` | mtg.toml.j2 | `/etc/mtproxy/mtg.toml` | upstream-прокси |
| `crowdsec_*` | acquis.yaml.j2 | `/etc/crowdsec/acquis.yaml` | все хосты |
| `mtproxy_hostname` | nginx-stream.conf.j2 | `/etc/nginx/conf.d/stream.conf` | access-прокси |

### 2. Squid access.log → CrowdSec Acquisition

**Тип:** File Tailing (потоковое чтение файла)

| Параметр | Значение |
|---|---|
| **Источник** | `/var/log/squid/access.log` (Squid daemon) |
| **Трансформация** | CrowdSec parsers (squid log format → events) |
| **Приёмник** | CrowdSec decision engine |
| **Триггер** | Непрерывный (tail -f mode) |
| **Направление** | Pull (CrowdSec читает файл Squid) |
| **Задержка** | < 30 секунд |

**Конфигурация acquisition:**
```yaml
# AI-GENERATED — NOT REVIEWED: SECTION START
# /etc/crowdsec/acquis.yaml
filenames:
  - /var/log/squid/access.log
labels:
  type: squid
# AI-GENERATED — NOT REVIEWED: SECTION END
```

**Цепочка обработки:**
1. Squid записывает строку в access.log
2. CrowdSec acquisition (tail mode) обнаруживает новую строку
3. Parser преобразует строку в структурированное событие
4. Scenarios оценивают событие (brute-force, scan, abuse)
5. При срабатывании — decision (ban IP на время TTL)

### 3. CrowdSec → nftables (Bouncer API)

**Тип:** API-driven enforcement

| Параметр | Значение |
|---|---|
| **Источник** | CrowdSec Local API (decisions) |
| **Трансформация** | cs-firewall-bouncer |
| **Приёмник** | nftables kernel tables |
| **Триггер** | Polling (bouncer опрашивает LAPI) |
| **Направление** | Pull (bouncer читает decisions) → Push (bouncer обновляет nftables) |
| **Задержка** | < 10 секунд |

**Механизм:**
1. CrowdSec engine принимает решение (ban IP)
2. Firewall bouncer запрашивает новые decisions через LAPI
3. Bouncer добавляет IP в nftables set `crowdsec-blacklists` с таймаутом
4. nftables kernel автоматически дропает пакеты от заблокированных IP
5. По истечении TTL — IP автоматически удаляется из set

### 4. htpasswd CLI → passwd File

**Тип:** CLI-driven file management

| Параметр | Значение |
|---|---|
| **Источник** | Команда DevOps-инженера |
| **Трансформация** | htpasswd (хеширование пароля) |
| **Приёмник** | `/etc/squid/passwd` |
| **Триггер** | Ручной (добавление/удаление пользователя) |
| **Направление** | Push (CLI → файл) |
| **Идемпотентность** | Да (htpasswd -b перезаписывает при совпадении username) |

**Команды:**
```bash
# AI-GENERATED — NOT REVIEWED: SECTION START
# Добавление/обновление пользователя
htpasswd -b /etc/squid/passwd <username> <password>

# Удаление пользователя
htpasswd -D /etc/squid/passwd <username>

# Верификация
htpasswd -v /etc/squid/passwd <username>
# AI-GENERATED — NOT REVIEWED: SECTION END
```

## Сводная карта интеграций

| # | Источник | → | Приёмник | Тип | Данные |
|---|---|---|---|---|---|
| 1 | inventory.yml | → | squid.conf (access) | Template render | Домены, параметры, cache_peer |
| 2 | inventory.yml | → | squid.conf (upstream) | Template render | ACL IP, параметры |
| 3 | inventory.yml | → | keepalived.conf | Template render | VRRP state, priority, VIP, password |
| 4 | inventory.yml | → | mtg.toml | Template render | Secret, bind, параметры |
| 5 | inventory.yml | → | nginx stream.conf | Template render | MTProxy hostname, порты |
| 6 | access.log | → | CrowdSec | File tail | Log records |
| 7 | CrowdSec LAPI | → | nftables | Bouncer API | Ban decisions (IP + TTL) |
| 8 | htpasswd CLI | → | passwd file | CLI → file | User + password_hash |

## Связанные требования

- [C2-FR-001](../C2/C2-FR-001.md) — Проксирование (интеграция 1, 2)
- [C2-FR-002](../C2/C2-FR-002.md) — Аутентификация (интеграция 8)
- [C2-FR-005](../C2/C2-FR-005.md) — Журналирование (интеграция 6)
- [C2-FR-008](../C2/C2-FR-008.md) — Развёртывание (интеграции 1–5)
- [C2-NF-002](../C2/C2-NF-002.md) — Безопасность (интеграция 7)

## Связанные документы

- [DD-SourceMap.md](DD-SourceMap.md) — Карта источников данных
- [DD-PDM.md](DD-PDM.md) — Физическая модель (форматы файлов)
- [DD-Lifecycle.md](DD-Lifecycle.md) — Жизненный цикл данных
<!-- [/AIGD] -->
