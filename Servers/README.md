<!-- [AIGD] -->
# Servers — Серверная инфраструктура

## Содержание

| Директория | Описание |
|------------|----------|
| [deploy/](deploy/) | Ansible playbook, inventory, Jinja2-шаблоны конфигураций |
| [examples/](examples/) | Эталонные конфигурации Squid и Keepalived (справочные) |

## deploy/

Автоматизированное развёртывание прокси-инфраструктуры через Ansible. Подробнее: [deploy/README.md](deploy/README.md).

## examples/

Примеры результирующих конфигураций для справки:

| Файл | Описание |
|------|----------|
| [examples/access/squid.conf](examples/access/squid.conf) | Эталонная конфигурация Squid для access-прокси |
| [examples/access/keepalived.conf](examples/access/keepalived.conf) | Эталонная конфигурация Keepalived для access-прокси |
| [examples/upstream/squid.conf](examples/upstream/squid.conf) | Эталонная конфигурация Squid для upstream-прокси |

## Связанная документация

- [docs/AA/C3-CR.md](../docs/AA/C3-CR.md) — Компонентный контекст (описание компонентов)
- [docs/AA/C4-SR.md](../docs/AA/C4-SR.md) — Уровень кода (детальная декомпозиция)
- [docs/AA/ADL.md](../docs/AA/ADL.md) — Архитектурные решения
<!-- [/AIGD] -->
