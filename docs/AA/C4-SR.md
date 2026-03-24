<!-- [AIGD] -->
# C4-SR -- Реестр артефактов уровня кода

> Слой C4 описывает конкретные артефакты IaC (Ansible playbook, inventory, templates, roles),
> реализующие компонентную архитектуру из [C3-CR](C3-CR.md).

## Группы артефактов

| Код группы | Название | Описание |
|---|---|---|
| **PB** | Playbooks / Inventory | Главный плейбук и файл инвентори |
| **TM** | Templates | Jinja2-шаблоны конфигурационных файлов |
| **RL** | Roles | Ansible-роли (tasks, handlers, templates, defaults) |

### PB: Playbooks / Inventory

| ID | Название | Тип артефакта | Файл | Родительский C3 | Описание | Уровень | Детальный файл |
|---|---|---|---|---|---|---|---|
| C4-PB-001 | Главный плейбук | playbook | `Servers/deploy/playbook.yml` | [C3-AD-001](C3/C3-AD-001.md) | Оркестрация развёртывания всей инфраструктуры AI Proxy | 4 -- Conformant | [C4-PB-001](C4/C4-PB-001.md) |
| C4-PB-002 | Инвентори | inventory | `Servers/deploy/inventory.yml` | [C3-AD-001](C3/C3-AD-001.md) | Определение хостов, групп и переменных конфигурации | 4 -- Conformant | [C4-PB-002](C4/C4-PB-002.md) |

### TM: Templates

| ID | Название | Тип артефакта | Файл | Родительский C3 | Описание | Уровень | Детальный файл |
|---|---|---|---|---|---|---|---|
| C4-TM-001 | Шаблон Squid Access | template | `Servers/deploy/templates/squid-access.conf.j2` | [C3-SA-001](C3/C3-SA-001.md) | Конфигурация Squid для access-прокси (аутентификация, ACL, upstream peers, анонимизация) | 4 -- Conformant | [C4-TM-001](C4/C4-TM-001.md) |
| C4-TM-002 | Шаблон Squid Upstream | template | `Servers/deploy/templates/squid-upstream.conf.j2` | [C3-SU-001](C3/C3-SU-001.md) | Конфигурация Squid для upstream-прокси (анонимный транспорт, ACL по IP) | 4 -- Conformant | [C4-TM-002](C4/C4-TM-002.md) |
| C4-TM-003 | Шаблон Keepalived | template | `Servers/deploy/templates/keepalived.conf.j2` | [C3-KA-001](C3/C3-KA-001.md) | Конфигурация VRRP для отказоустойчивости access-прокси (VIP, health check) | 4 -- Conformant | [C4-TM-003](C4/C4-TM-003.md) |
| C4-TM-004 | Шаблон nftables Upstream | template | `Servers/deploy/templates/nftables-upstream.conf.j2` | [C3-SU-001](C3/C3-SU-001.md) | Правила межсетевого экрана для upstream-узлов (ограничение доступа к Squid) | 4 -- Conformant | [C4-TM-004](C4/C4-TM-004.md) |

### TM (дополнительные)

| ID | Название | Тип артефакта | Файл | Родительский C3 | Описание | Уровень | Детальный файл |
|---|---|---|---|---|---|---|---|
| C4-TM-005 | Шаблон health check Squid | template | `Servers/deploy/templates/check_and_restart_squid.sh.j2` | [C3-KA-001](C3/C3-KA-001.md) | Скрипт проверки и авторестарта Squid для Keepalived vrrp_script (cooldown, lockfile) | 4 -- Conformant | [C4-TM-005](C4/C4-TM-005.md) |

### RL: Roles

| ID | Название | Тип артефакта | Файл | Родительский C3 | Описание | Уровень | Детальный файл |
|---|---|---|---|---|---|---|---|
| C4-RL-001 | Роль CrowdSec | role | `Servers/deploy/roles/crowdsec/` | [C3-CS-001](C3/C3-CS-001.md) | Установка и настройка CrowdSec IPS с firewall bouncer | 4 -- Conformant | [C4-RL-001](C4/C4-RL-001.md) |
| C4-RL-002 | Роль nginx | role | `Servers/deploy/roles/nginx/` | [C3-NX-001](C3/C3-NX-001.md) | SNI-маршрутизация на порту 443 для co-deployment Squid + MTProxy | 4 -- Conformant | [C4-RL-002](C4/C4-RL-002.md) |
| C4-RL-003 | Роль MTProxy | role | `Servers/deploy/roles/mtproxy/` | [C3-MT-001](C3/C3-MT-001.md) | Развёртывание Telegram MTProxy (mtg) с управлением секретами и firewall | 4 -- Conformant | [C4-RL-003](C4/C4-RL-003.md) |
| C4-RL-004 | Роль DNS Resolver | role | `Servers/deploy/roles/dns_resolver/` | [C3-DN-001](C3/C3-DN-001.md) | Установка и настройка Unbound: каскадный DNS, DNSSEC, авторасчёт ресурсов | 4 -- Conformant | [C4-RL-004](C4/C4-RL-004.md) |

## Матрица трассируемости C3 -> C4

| C3 | C4 артефакты |
|---|---|
| [C3-AD-001](C3/C3-AD-001.md) | [C4-PB-001](C4/C4-PB-001.md), [C4-PB-002](C4/C4-PB-002.md) |
| [C3-SA-001](C3/C3-SA-001.md) | [C4-TM-001](C4/C4-TM-001.md) |
| [C3-SU-001](C3/C3-SU-001.md) | [C4-TM-002](C4/C4-TM-002.md), [C4-TM-004](C4/C4-TM-004.md) |
| [C3-KA-001](C3/C3-KA-001.md) | [C4-TM-003](C4/C4-TM-003.md), [C4-TM-005](C4/C4-TM-005.md) |
| [C3-DN-001](C3/C3-DN-001.md) | [C4-RL-004](C4/C4-RL-004.md) |
| [C3-CS-001](C3/C3-CS-001.md) | [C4-RL-001](C4/C4-RL-001.md) |
| [C3-NX-001](C3/C3-NX-001.md) | [C4-RL-002](C4/C4-RL-002.md) |
| [C3-MT-001](C3/C3-MT-001.md) | [C4-RL-003](C4/C4-RL-003.md) |
<!-- [/AIGD] -->
