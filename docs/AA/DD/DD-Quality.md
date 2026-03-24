<!-- [AIGD] -->
# DD-Quality — Правила качества данных

## Описание

Документ определяет измерения качества данных (по модели DAMA DMBOK 8 измерений), пороговые значения и процедуры контроля для сущностей данных проекта AI Assistants Proxy.

## Измерения качества данных (DAMA 8)

### 1. Полнота (Completeness)

| Правило | Сущность | Порог | Проверка |
|---|---|---|---|
| Все обязательные параметры inventory.yml должны быть заданы | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ansible playbook: undefined variable → fatal error |
| Каждый access-прокси хост имеет `ansible_host`, `keepalived_state`, `keepalived_priority` | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ansible template rendering |
| Каждый upstream хост имеет `ansible_host` | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ansible template rendering |
| Хотя бы один домен в `allowed_domains` или `allowed_domain_patterns` | [DE-DM-001](DE/DE-DM-001.md) | >= 1 | Ansible assert / Squid startup |
| Файл passwd содержит хотя бы одну учётную запись (если `enable_auth: true`) | [DE-CR-001](DE/DE-CR-001.md) | >= 1 | htpasswd -v |

### 2. Валидность (Validity)

| Правило | Сущность | Порог | Проверка |
|---|---|---|---|
| Паттерны `allowed_domain_patterns` — валидные регулярные выражения | [DE-DM-001](DE/DE-DM-001.md) | 100% | Squid startup (syntax check) |
| IP-адреса в `ansible_host` — валидные IPv4 | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ansible: ipaddr filter |
| `mtproxy_secret` — hex-строка корректной длины | [DE-SC-001](DE/DE-SC-001.md) | 100% | mtg validate |
| `keepalived_vrid` — integer в диапазоне 1–255 | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ansible assert |
| Порты (`squid_port`, `mtproxy_local_port`) — integer в диапазоне 1–65535 | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ansible assert |

### 3. Точность (Accuracy)

| Правило | Сущность | Порог | Проверка |
|---|---|---|---|
| IP-адреса в ACL upstream соответствуют фактическим IP access-прокси | [DE-AC-001](DE/DE-AC-001.md) | 100% | Ansible: генерация ACL из `ansible_host` access-прокси |
| VIP (`keepalived_vip`) принадлежит подсети access-нод | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ручная верификация при развёртывании |
| Домены в whitelist соответствуют актуальным эндпоинтам AI API | [DE-DM-001](DE/DE-DM-001.md) | >= 95% | Периодическая ручная ревизия |

### 4. Согласованность (Consistency)

| Правило | Сущность | Порог | Проверка |
|---|---|---|---|
| Переменные inventory согласованы между хостами одной группы | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ansible: group_vars задают общие значения |
| `keepalived_state` MASTER ровно у одной ноды access tier | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ручная проверка inventory |
| `keepalived_priority` уникально для каждой access-ноды | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ручная проверка inventory |
| Все access-ноды используют одинаковый `keepalived_vrid` | [DE-CF-001](DE/DE-CF-001.md) | 100% | group_vars |
| Секрет MTProxy одинаков на всех upstream-нодах | [DE-SC-001](DE/DE-SC-001.md) | 100% | global vars в inventory |

### 5. Своевременность (Timeliness)

| Правило | Сущность | Порог | Проверка |
|---|---|---|---|
| Записи access.log создаются в near-real-time (< 1 сек задержки) | [DE-LG-001](DE/DE-LG-001.md) | < 1 с | Squid buffered I/O |
| CrowdSec acquisition обрабатывает записи с задержкой < 30 сек | [DE-LG-001](DE/DE-LG-001.md) | < 30 с | CrowdSec tail mode |
| Конфигурации применяются после запуска playbook < 5 мин | [DE-CF-001](DE/DE-CF-001.md) | < 5 мин | Ansible execution time |

### 6. Уникальность (Uniqueness)

| Правило | Сущность | Порог | Проверка |
|---|---|---|---|
| Нет дублирующихся пользователей в passwd | [DE-CR-001](DE/DE-CR-001.md) | 100% | htpasswd: замена при совпадении имени |
| Нет дублирующихся IP в ACL upstream | [DE-AC-001](DE/DE-AC-001.md) | 100% | Jinja2 template: `| unique` filter |
| Нет дублирующихся доменов в whitelist | [DE-DM-001](DE/DE-DM-001.md) | 100% | Ansible: `| unique` filter в шаблоне |
| Имена хостов inventory уникальны | [DE-CF-001](DE/DE-CF-001.md) | 100% | YAML-ключи (уникальность по определению) |

### 7. Целостность (Integrity)

| Правило | Сущность | Порог | Проверка |
|---|---|---|---|
| Перекрёстные ссылки inventory → шаблоны валидны | [DE-CF-001](DE/DE-CF-001.md) | 100% | Ansible: template rendering (missing variable → error) |
| cache_peer IP в squid.conf access = ansible_host upstream | [DE-AC-001](DE/DE-AC-001.md) | 100% | Jinja2 template: итерация по `groups['upstreams']` |
| access_proxies ACL в squid.conf upstream = ansible_host access | [DE-AC-001](DE/DE-AC-001.md) | 100% | Jinja2 template: итерация по `groups['access_proxies']` |
| nginx upstream backend ports = `mtproxy_local_port` | [DE-CF-001](DE/DE-CF-001.md) | 100% | Jinja2 template: единая переменная |

### 8. Доступность (Accessibility)

| Правило | Сущность | Порог | Проверка |
|---|---|---|---|
| Конфигурации читаемы сервисными пользователями | Все DE | 100% | Ansible: file module с mode/owner/group |
| passwd читаем Squid-процессом (proxy:proxy) | [DE-CR-001](DE/DE-CR-001.md) | 100% | Файловые права: 640, группа proxy |
| access.log читаем CrowdSec (proxy:proxy) | [DE-LG-001](DE/DE-LG-001.md) | 100% | CrowdSec acquisition с правами proxy |
| mtg.toml читаем mtproxy-процессом | [DE-SC-001](DE/DE-SC-001.md) | 100% | Файловые права: 640, группа mtproxy |
| Чувствительные файлы не читаемы другими (o-r) | [DE-CR-001](DE/DE-CR-001.md), [DE-SC-001](DE/DE-SC-001.md) | 100% | Файловые права: 640 (не 644) |

## Сводная матрица

| Измерение | DE-CR-001 | DE-AC-001 | DE-DM-001 | DE-CF-001 | DE-LG-001 | DE-SC-001 |
|---|---|---|---|---|---|---|
| Полнота | >= 1 запись | Auto | >= 1 домен | 100% обяз. | Auto | 100% |
| Валидность | htpasswd формат | IPv4 | regex valid | Типы значений | logformat | hex valid |
| Точность | — | IP = ansible_host | Актуальные API | VIP в подсети | — | — |
| Согласованность | — | — | — | group_vars | — | Единый secret |
| Своевременность | — | — | — | < 5 мин deploy | < 1 с запись | — |
| Уникальность | Уник. username | Уник. IP | Уник. домен | Уник. host | — | Уник. name |
| Целостность | — | inventory ↔ conf | — | template refs | — | inventory ↔ conf |
| Доступность | 640 proxy | 644 root | 644 proxy | VCS | 640 proxy | 640 mtproxy |

## Связанные документы

- [DD-Catalog.md](DD-Catalog.md) — Каталог сущностей
- [DD-Governance.md](DD-Governance.md) — Управление данными
- [DD-Security.md](DD-Security.md) — Безопасность данных
<!-- [/AIGD] -->
