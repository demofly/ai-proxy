<!-- [AIGD] -->
# DD-Governance — Управление данными

## Описание

Документ определяет роли, ответственности, политики и процессы управления данными проекта AI Assistants Proxy. Управление данными в IaC-проекте отличается от классического: источник истины — inventory.yml в VCS, автоматическая пропагация — через Ansible.

## Роли управления данными

| Роль | Описание | Назначение | Ответственности |
|---|---|---|---|
| **Data Owner** | Владелец данных, принимающий решения о содержимом | DevOps-инженер | Определяет состав учётных данных, домены whitelist, секреты, конфигурационные параметры. Утверждает изменения в inventory.yml |
| **Data Steward** | Хранитель данных, обеспечивающий качество и пропагацию | Ansible (автоматически) | Генерирует конфигурационные файлы из inventory.yml через Jinja2-шаблоны. Обеспечивает согласованность между хостами |
| **Data Consumer** | Потребитель данных | Squid, CrowdSec, Keepalived, mtg | Сервисные процессы, читающие конфигурации и генерирующие данные (логи) |
| **Data Producer** | Источник данных | Squid (логи), CrowdSec (blacklists), htpasswd (credentials) | Генерируют данные в процессе работы |

## Матрица CRUD (роль x сущность)

| Сущность | DevOps-инженер | Ansible | Squid | CrowdSec | htpasswd CLI |
|---|---|---|---|---|---|
| [DE-CR-001](DE/DE-CR-001.md) Credentials | Решает (Owner) | — | Read | — | Create/Update/Delete |
| [DE-AC-001](DE/DE-AC-001.md) ACL | Определяет (inventory) | Create (render) | Read | Read/Update (nftables) | — |
| [DE-DM-001](DE/DE-DM-001.md) Domain Lists | Create/Update (inventory) | Create (render) | Read | — | — |
| [DE-CF-001](DE/DE-CF-001.md) Config Params | Create/Update/Delete | Create (render) | Read | Read | — |
| [DE-LG-001](DE/DE-LG-001.md) Log Records | Read (анализ) | — | Create | Read (acquisition) | — |
| [DE-SC-001](DE/DE-SC-001.md) Secrets | Create/Update (inventory) | Create (render) | — | — | — |

## Политики управления данными

### Источник истины (Single Source of Truth)

| Сущность | SSOT | Обоснование |
|---|---|---|
| Config Parameters | `inventory.yml` | Единая точка определения всех параметров |
| Credentials | `/etc/squid/passwd` | Прямое управление через htpasswd CLI |
| ACL | `inventory.yml` → generated configs | IP-адреса определяются в inventory, ACL генерируются автоматически |
| Domain Lists | `inventory.yml` (allowed_domains*) | Списки определяются в inventory |
| Secrets | `inventory.yml` | Секреты определяются в inventory, пропагируются Ansible |
| Log Records | `/var/log/squid/access.log` | Генерируются Squid daemon'ом |

### Политика изменений

Процесс внесения изменений в данные:

1. **Редактирование inventory.yml** — DevOps-инженер вносит изменения в источник истины
2. **Запуск playbook** — `ansible-playbook playbook.yml` пропагирует изменения на все целевые хосты
3. **Верификация** — Ansible handlers перезапускают затронутые сервисы; `--check` режим для предварительной проверки
4. **Контроль версий** — изменения фиксируются в Git (VCS)

### Политика доступа к данным

| Уровень доступа | Файловые права | Примеры файлов |
|---|---|---|
| **Чувствительные данные** | 640 (owner: root, group: service) | passwd, mtg.toml, keepalived.conf |
| **Конфигурации** | 644 (owner: root, group: root) | squid.conf, nftables.conf |
| **Журналы** | 640 (owner: proxy, group: proxy) | access.log |

### Политика резервного копирования

| Сущность | Стратегия | Частота |
|---|---|---|
| inventory.yml | Git (VCS) | Каждое изменение |
| Конфигурации серверов | Regenerable (из inventory + templates) | Не требуется (regenerable) |
| passwd | Ручное резервное копирование | По необходимости |
| access.log | logrotate + архивация | Ежедневно |
| Секреты | Git (inventory.yml) | Каждое изменение |

### Политика Ansible no_log

Задачи Ansible, обрабатывающие чувствительные данные, обязаны использовать директиву `no_log: true` для предотвращения утечки секретов в вывод:

| Контекст | Переменные, требующие no_log | Обоснование |
|---|---|---|
| Пароли | `keepalived_auth_pass`, пароли пользователей | Credentials — высокий уровень конфиденциальности |
| Секреты | `mtproxy_secret` | Компрометация позволяет подключиться к MTProxy |
| Шаблоны с секретами | mtg.toml.j2, keepalived.conf.j2 | Рендеринг содержит значения секретов |

## Связанные документы

- [DD-Quality.md](DD-Quality.md) — Правила качества данных
- [DD-Security.md](DD-Security.md) — Безопасность данных
- [DD-Lifecycle.md](DD-Lifecycle.md) — Жизненный цикл данных
- [CC-RACI.md](../CC/CC-RACI.md) — Роли и ответственности (RACI)
<!-- [/AIGD] -->
