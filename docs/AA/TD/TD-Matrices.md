<!-- [AIGD] -->
# TD-Matrices — Матрицы трассируемости M1–M10

## Описание

Матрицы трассируемости обеспечивают сквозную прослеживаемость между слоями архитектуры C1–C4, технической документацией (TD), архитектурой данных (DD) и архитектурными решениями (ADL).

---

## M1: C2 → C3 (Требование → Компонент)

Показывает, какие компоненты (C3) реализуют каждое требование (C2).

| C2 \ C3 | C3-SA-001 Squid Access | C3-SU-001 Squid Upstream | C3-NX-001 nginx SNI | C3-KA-001 Keepalived | C3-CS-001 CrowdSec | C3-MT-001 MTProxy | C3-AD-001 Ansible |
|---|---|---|---|---|---|---|---|
| [C2-FR-001](../C2/C2-FR-001.md) Проксирование | **X** | **X** | | | | | |
| [C2-FR-002](../C2/C2-FR-002.md) Аутентификация | **X** | | | | | | |
| [C2-FR-003](../C2/C2-FR-003.md) Фильтрация доменов | **X** | | | | | | |
| [C2-FR-004](../C2/C2-FR-004.md) Кеширование | **X** | | | | | | |
| [C2-FR-005](../C2/C2-FR-005.md) Журналирование | **X** | | | | **X** | | |
| [C2-FR-006](../C2/C2-FR-006.md) MTProxy | | | **X** | | | **X** | |
| [C2-FR-007](../C2/C2-FR-007.md) Конфигурации клиентов | | | | | | | **X** |
| [C2-FR-008](../C2/C2-FR-008.md) Развёртывание | **X** | **X** | **X** | **X** | **X** | **X** | **X** |
| [C2-NF-001](../C2/C2-NF-001.md) Доступность | **X** | **X** | | **X** | | | |
| [C2-NF-002](../C2/C2-NF-002.md) Безопасность | **X** | **X** | | | **X** | **X** | |
| [C2-NF-003](../C2/C2-NF-003.md) Производительность | **X** | **X** | | | | | |
| [C2-NF-004](../C2/C2-NF-004.md) Масштабируемость | **X** | **X** | | | | | |
| [C2-NF-005](../C2/C2-NF-005.md) Наблюдаемость | **X** | | | **X** | **X** | | |
| [C2-CN-001](../C2/C2-CN-001.md) Двухуровневая арх. | **X** | **X** | | | | | |
| [C2-CN-002](../C2/C2-CN-002.md) Co-deployment | | | **X** | | | | |

---

## M2: C3 → C4 (Компонент → Код)

Показывает, какие артефакты кода (C4) реализуют каждый компонент (C3).

| C3 \ C4 | [C4-PB-001](../C4/C4-PB-001.md) playbook | [C4-PB-002](../C4/C4-PB-002.md) inventory | [C4-TM-001](../C4/C4-TM-001.md) squid-access | [C4-TM-002](../C4/C4-TM-002.md) squid-upstream | [C4-TM-003](../C4/C4-TM-003.md) keepalived | [C4-TM-004](../C4/C4-TM-004.md) nftables | [C4-RL-001](../C4/C4-RL-001.md) crowdsec | [C4-RL-002](../C4/C4-RL-002.md) nginx | [C4-RL-003](../C4/C4-RL-003.md) mtproxy |
|---|---|---|---|---|---|---|---|---|---|
| C3-SA-001 Squid Access | **X** | **X** | **X** | | | | | | |
| C3-SU-001 Squid Upstream | **X** | **X** | | **X** | | **X** | | | |
| C3-NX-001 nginx SNI | **X** | **X** | | | | | | **X** | |
| C3-KA-001 Keepalived | **X** | **X** | | | **X** | | | | |
| C3-CS-001 CrowdSec | **X** | **X** | | | | | **X** | | |
| C3-MT-001 MTProxy | **X** | **X** | | | | | | | **X** |
| C3-AD-001 Ansible | **X** | **X** | **X** | **X** | **X** | **X** | **X** | **X** | **X** |

---

## M3: C1 → C2 (Бизнес-контекст → Требования)

Показывает, какие требования C2 порождены каждым объектом бизнес-контекста C1.

| C1 \ C2 | FR-001 | FR-002 | FR-003 | FR-004 | FR-005 | FR-006 | FR-007 | FR-008 | NF-001 | NF-002 | NF-003 | NF-004 | NF-005 | CN-001 | CN-002 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [C1-BC-001](../C1/C1-BC-001.md) Целевая система | **X** | | | **X** | | **X** | | | | | | | | **X** | **X** |
| [C1-BC-002](../C1/C1-BC-002.md) Стейкхолдеры | | **X** | | | **X** | | **X** | **X** | | | | | | | |
| [C1-BC-003](../C1/C1-BC-003.md) Внешние системы | **X** | | **X** | | | **X** | | | | **X** | | | | | |
| [C1-BC-004](../C1/C1-BC-004.md) Бизнес-цели | | | | | **X** | | | **X** | **X** | **X** | **X** | **X** | **X** | | |

---

## M4: Компонент → Интерфейс

Показывает интерфейсы (порты, протоколы) каждого компонента.

| Компонент | Порт | Протокол | Направление | Назначение |
|---|---|---|---|---|
| C3-SA-001 Squid Access | 127.0.0.1:3128 | HTTP CONNECT (PROXY protocol) | Входящий | Клиентские подключения через nginx SNI Router (:443) |
| C3-SA-001 Squid Access | →upstream:80 | HTTP CONNECT | Исходящий | Каскадирование на upstream (cache_peer) |
| C3-SU-001 Squid Upstream | 80 | HTTP CONNECT | Входящий | Запросы от access-прокси (plain HTTP) |
| C3-SU-001 Squid Upstream | 443 | HTTPS | Исходящий | Запросы к AI API |
| C3-NX-001 nginx SNI | 443 | TLS (L4 stream) | Входящий | Внешние TLS-подключения |
| C3-NX-001 nginx SNI | → backend | TCP | Исходящий | Маршрутизация по SNI на внутренние сервисы |
| C3-KA-001 Keepalived | 112 (VRRP) | VRRP multicast | Двунаправленный | VRRP heartbeat между access-нодами |
| C3-KA-001 Keepalived | VIP | — | Виртуальный | Виртуальный IP для клиентов |
| C3-CS-001 CrowdSec | 8080 | HTTP | Входящий | Local API (cscli, bouncer) |
| C3-CS-001 CrowdSec | — | HTTPS | Исходящий | CrowdSec Central API |
| C3-MT-001 MTProxy | 127.0.0.1:2083 | fake-TLS / MTProto | Входящий | Telegram-клиенты (через nginx SNI :443) |
| C3-MT-001 MTProxy | — | TCP | Исходящий | Telegram Data Centers |

---

## M5: Требование → ADR

Показывает, какие архитектурные решения (ADR) обосновывают реализацию требований.

| Требование | ADR |
|---|---|
| [C2-FR-001](../C2/C2-FR-001.md) Проксирование | [ADR-000001](../ADR/ADR-000001.md), [ADR-000002](../ADR/ADR-000002.md) |
| [C2-FR-002](../C2/C2-FR-002.md) Аутентификация | [ADR-000002](../ADR/ADR-000002.md) |
| [C2-FR-003](../C2/C2-FR-003.md) Фильтрация | [ADR-000002](../ADR/ADR-000002.md) |
| [C2-FR-004](../C2/C2-FR-004.md) Кеширование | [ADR-000002](../ADR/ADR-000002.md) |
| [C2-FR-005](../C2/C2-FR-005.md) Журналирование | [ADR-000002](../ADR/ADR-000002.md), [ADR-000004](../ADR/ADR-000004.md) |
| [C2-FR-006](../C2/C2-FR-006.md) MTProxy | [ADR-000005](../ADR/ADR-000005.md), [ADR-000003](../ADR/ADR-000003.md) |
| [C2-FR-007](../C2/C2-FR-007.md) Конфигурации клиентов | [ADR-000007](../ADR/ADR-000007.md) |
| [C2-FR-008](../C2/C2-FR-008.md) Развёртывание | [ADR-000007](../ADR/ADR-000007.md) |
| [C2-NF-001](../C2/C2-NF-001.md) Доступность | [ADR-000006](../ADR/ADR-000006.md) |
| [C2-NF-002](../C2/C2-NF-002.md) Безопасность | [ADR-000004](../ADR/ADR-000004.md), [ADR-000001](../ADR/ADR-000001.md) |
| [C2-NF-003](../C2/C2-NF-003.md) Производительность | [ADR-000002](../ADR/ADR-000002.md) |
| [C2-NF-004](../C2/C2-NF-004.md) Масштабируемость | [ADR-000001](../ADR/ADR-000001.md) |
| [C2-NF-005](../C2/C2-NF-005.md) Наблюдаемость | [ADR-000002](../ADR/ADR-000002.md), [ADR-000004](../ADR/ADR-000004.md) |
| [C2-CN-001](../C2/C2-CN-001.md) Двухуровневая арх. | [ADR-000001](../ADR/ADR-000001.md) |
| [C2-CN-002](../C2/C2-CN-002.md) Co-deployment | [ADR-000003](../ADR/ADR-000003.md) |

---

## M6: Требование → Тест

*Placeholder.* Проект представляет собой IaC-инфраструктуру на базе Ansible. Автоматизированные тесты на данный момент не реализованы. При появлении тестов (molecule, testinfra, serverspec) матрица будет заполнена.

| Требование | Тест ID | Тип | Статус |
|---|---|---|---|
| — | — | — | Тесты не реализованы |

---

## M7: Онтология → Артефакт (покрытие)

Показывает покрытие типов объектов управления каждого слоя.

### C1

| Тип объекта | Статус | Артефакт |
|---|---|---|
| Целевая система | Covered | [C1-BC-001](../C1/C1-BC-001.md) |
| Стейкхолдеры | Covered | [C1-BC-002](../C1/C1-BC-002.md) |
| Внешние системы | Covered | [C1-BC-003](../C1/C1-BC-003.md) |
| Акторы / Personas | Covered | [C1-BC-002](../C1/C1-BC-002.md) |
| Бизнес-цели и KPI | Covered | [C1-BC-004](../C1/C1-BC-004.md) |
| Регуляторная среда | Covered | [C1-BC-004](../C1/C1-BC-004.md) |
| Контракты и SLA | Covered | [C1-BC-004](../C1/C1-BC-004.md) |
| Границы системы | Covered | [C1-BC-001](../C1/C1-BC-001.md) |
| Бизнес-сущности данных | Covered | [C1-BC-003](../C1/C1-BC-003.md) |
| Потоки ценности | Covered | [C1-BC-004](../C1/C1-BC-004.md) |

### C2

| Тип объекта | Статус | Артефакт |
|---|---|---|
| Функциональные требования (FR) | Covered | C2-FR-001 — C2-FR-008 |
| Нефункциональные требования (NF) | Covered | C2-NF-001 — C2-NF-005 |
| Ограничения и допущения (CN) | Covered | C2-CN-001, C2-CN-002 |
| Мета-уровень | Covered | [C2-META.md](../C2/C2-META.md) |

---

## M8: Компонент → Сущность данных (DE)

Показывает, какие сущности данных использует каждый компонент.

| Компонент | Сущности данных | Операции |
|---|---|---|
| C3-SA-001 Squid Access | HTTP-запросы (DE-RQ-001), Учётные данные (DE-CR-001), Белый список доменов (DE-WL-001), Access log (DE-LG-001), Кэш (DE-CA-001) | Read/Write |
| C3-SU-001 Squid Upstream | HTTP-запросы (DE-RQ-001) | Read (passthrough) |
| C3-NX-001 nginx SNI | SNI-маппинг (DE-SN-001) | Read |
| C3-KA-001 Keepalived | VRRP-конфигурация (DE-VR-001) | Read |
| C3-CS-001 CrowdSec | Access log (DE-LG-001), Решения IPS (DE-IP-001) | Read/Write |
| C3-MT-001 MTProxy | MTProxy secret (DE-MS-001) | Read |
| C3-AD-001 Ansible | Inventory (DE-IN-001), Все конфигурации | Read/Write |

---

## M9: Сущность данных → Хранилище

Показывает, где физически хранится каждая сущность данных.

| Сущность данных | ID | Хранилище | Формат | Расположение |
|---|---|---|---|---|
| HTTP-запросы | DE-RQ-001 | Транзитное (in-memory) | TCP stream | Squid worker memory |
| Учётные данные | DE-CR-001 | Файловая система (access node) | htpasswd (plaintext MD5/bcrypt) | `/etc/squid/passwd` |
| Белый список доменов | DE-WL-001 | Файловая система (access node) | Текстовый список | `/etc/squid/allowed_domains.txt` |
| Access log | DE-LG-001 | Файловая система (access node) | Текстовый лог (logformat) | `/var/log/squid/access.log` |
| Кэш | DE-CA-001 | Файловая система (access node) | Squid ufs | `/var/spool/squid/` |
| SNI-маппинг | DE-SN-001 | Файловая система (upstream node) | nginx stream config | `/etc/nginx/stream.d/` |
| VRRP-конфигурация | DE-VR-001 | Файловая система (access node) | keepalived.conf | `/etc/keepalived/keepalived.conf` |
| Решения IPS | DE-IP-001 | CrowdSec Local DB + nftables | SQLite + nftables rules | `/var/lib/crowdsec/data/`, nftables ruleset |
| MTProxy secret | DE-MS-001 | Файловая система (upstream node) | Hex string (systemd env) | systemd unit / inventory |
| Inventory | DE-IN-001 | Git-репозиторий | YAML | `inventory.yml` |

---

## M10: Компонент → Технология

Показывает технологическую платформу каждого компонента.

| Компонент | Технология | Версия | Radar-статус | Описание |
|---|---|---|---|---|
| C3-SA-001 Squid Access | Squid | 6.x | Adopt | HTTP/HTTPS proxy, access tier |
| C3-SU-001 Squid Upstream | Squid | 6.x | Adopt | HTTP/HTTPS proxy, upstream tier |
| C3-NX-001 nginx SNI | nginx | 1.x | Adopt | L4 stream SNI routing |
| C3-KA-001 Keepalived | Keepalived | 2.x | Adopt | VRRP failover |
| C3-CS-001 CrowdSec | CrowdSec | 1.x | Adopt | IPS + reputation |
| C3-MT-001 MTProxy | mtg | 2.1.8 | Adopt | Telegram MTProxy (Go) |
| C3-AD-001 Ansible | Ansible | ≥2.15 | Adopt | IaC, configuration management |
| Все ноды | Ubuntu | 24.04 LTS | Adopt | Primary target OS |
| Все ноды | Debian | bookworm | Adopt | Secondary target OS |
| C3-SA-001, C3-SU-001 | htpasswd | — | Adopt | Basic authentication (apache2-utils) |
| C3-SU-001, C3-MT-001 | nftables | — | Adopt | Linux firewall |
<!-- [/AIGD] -->
