<!-- [AIGD] -->
# Servers — Серверная инфраструктура

## Содержание

| Директория | Описание |
|------------|----------|
| [deploy/](deploy/) | Ansible playbook, inventory, Jinja2-шаблоны конфигураций |
| [examples/](examples/README.md) | Конечные примеры Squid, nginx, HTTPS/ACME, MTProxy, DNS, firewall, systemd и остальных управляемых настроек |

## deploy/

Автоматизированное развёртывание прокси-инфраструктуры через Ansible. Подробнее: [deploy/README.md](deploy/README.md).

## examples/

Примеры результирующих конфигураций на вымышленных узлах. Они генерируются из
действующих шаблонов и задач без чтения рабочего inventory и секретов.
Полный состав, сценарий и команда обновления: [examples/README.md](examples/README.md).

| Файл | Описание |
|------|----------|
| [examples/access/squid.conf](examples/access/squid.conf) | Эталонная конфигурация Squid для access-прокси |
| [examples/access/keepalived.conf](examples/access/keepalived.conf) | Эталонная конфигурация Keepalived для access-прокси |
| [examples/upstream/squid.conf](examples/upstream/squid.conf) | Эталонная конфигурация Squid для upstream-прокси |
| [examples/access/nginx/](examples/access/nginx/) | Клиентский HTTPS, MTProxy relay, двухузловой ACME и SNI routing |
| [examples/upstream/nginx/](examples/upstream/nginx/) | TLS-терминаторы Squid transit и MTProxy, карты SNI |
| [examples/manifest.json](examples/manifest.json) | Соответствие каждого примера его пути установки и источнику в деплойменте |

## Связанная документация

- [docs/AA/C3-CR.md](../docs/AA/C3-CR.md) — Компонентный контекст (описание компонентов)
- [docs/AA/C4-SR.md](../docs/AA/C4-SR.md) — Уровень кода (детальная декомпозиция)
- [docs/AA/ADL.md](../docs/AA/ADL.md) — Архитектурные решения
<!-- [/AIGD] -->
