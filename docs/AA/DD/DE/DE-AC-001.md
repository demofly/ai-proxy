<!-- [AIGD] -->
# DE-AC-001 — Списки управления доступом (ACL)

## Описание

Списки управления доступом (ACL) — IP-адреса access-прокси, используемые для ограничения входящих подключений к upstream-прокси. Генерируются автоматически из inventory.yml при каждом запуске Ansible playbook. Применяются в двух контекстах: Squid ACL на upstream (фильтрация по source IP) и nftables на всех хостах (CrowdSec blacklists).

## Атрибуты

| Атрибут | Тип | Описание | Обязательность |
|---|---|---|---|
| source_ip | IPv4 address | IP-адрес access-прокси (из `ansible_host`) | Обязательный |
| destination_port | integer (1–65535) | Порт назначения (443 для Squid, различные для nftables) | Обязательный |
| action | enum {allow, deny} | Действие при совпадении правила | Обязательный |

## Хранилище

### Squid ACL (upstream)

| Параметр | Значение |
|---|---|
| **Путь** | `/etc/squid/squid.conf` (на upstream-прокси) |
| **Формат** | Squid ACL directives: `acl access_proxies src <IP1> <IP2> ...` |
| **Генерация** | Ansible Jinja2: итерация по `groups['access_proxies']` |
| **Компонент** | [C3-SU-001](../../C3/C3-SU-001.md) — Squid Upstream Proxy |

**Пример:**
```
# AI-GENERATED — NOT REVIEWED: SECTION START
acl access_proxies src 94.103.88.223 81.85.78.43
http_access allow access_proxies
http_access deny all
# AI-GENERATED — NOT REVIEWED: SECTION END
```

### nftables ACL (CrowdSec)

| Параметр | Значение |
|---|---|
| **Путь** | `/etc/nftables.conf` (на всех хостах) |
| **Формат** | nftables set + chain: `table inet crowdsec { set crowdsec-blacklists { ... } }` |
| **Генерация** | CrowdSec firewall bouncer (автоматически) |
| **Компонент** | [C3-CS-001](../../C3/C3-CS-001.md) — CrowdSec IPS |

## Жизненный цикл

| Стадия | Действие | Актор | Инструмент |
|---|---|---|---|
| **Create** | Генерация ACL из inventory | Ansible | Jinja2 template rendering |
| **Store** | Запись в squid.conf / nftables.conf | Ansible | template module |
| **Use** | Фильтрация трафика | Squid / nftables | ACL engine / kernel |
| **Update** | Перегенерация при изменении inventory | Ansible | playbook re-run |
| **Archive** | Git history (inventory.yml) | VCS | Git |
| **Dispose** | Замена файла целиком при re-deploy | Ansible | template module |

## Безопасность

| Параметр | Значение |
|---|---|
| **Уровень конфиденциальности** | Средний |
| **Обоснование** | Раскрывает IP-адреса инфраструктуры |
| **Файловые права** | 644 (squid.conf), 644 (nftables.conf) |
| **Автогенерация** | Исключает ручные ошибки в IP-адресах |

## Связанные требования

- [C2-FR-001](../../C2/C2-FR-001.md) — Проксирование запросов (upstream ACL)
- [C2-NF-002](../../C2/C2-NF-002.md) — Безопасность (nftables, CrowdSec)
- [C3-SU-001](../../C3/C3-SU-001.md) — Squid Upstream Proxy (Squid ACL)
- [C3-CS-001](../../C3/C3-CS-001.md) — CrowdSec IPS (nftables ACL)
<!-- [/AIGD] -->
