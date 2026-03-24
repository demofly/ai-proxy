<!-- [AIGD] -->
# DD-Catalog — Каталог сущностей данных

## Описание

Каталог содержит реестр всех сущностей данных (Data Entities, DE) проекта AI Assistants Proxy. Проект представляет собой IaC-систему (Ansible), не использующую традиционные СУБД. Данные хранятся в конфигурационных файлах, файлах паролей, журналах и TOML-конфигурациях на целевых серверах.

## Группы сущностей

| Код группы | Название | Описание |
|---|---|---|
| CR | Credentials | Учётные данные для аутентификации |
| AC | Access Control | Списки управления доступом |
| DM | Domain Management | Управление списками доменов |
| CF | Configuration | Конфигурационные параметры |
| LG | Logging | Записи журналов |
| SC | Secrets | Секреты и ключи |

## Реестр сущностей данных

| ID | Название | Группа | Описание | Хранилище | Владелец | DE-файл |
|---|---|---|---|---|---|---|
| DE-CR-001 | Учётные данные прокси (Credentials) | CR | Логины/пароли для Basic Auth | passwd file на access proxy | DevOps-инженер | [DE-CR-001](DE/DE-CR-001.md) |
| DE-AC-001 | Списки управления доступом (ACL) | AC | IP-адреса access-прокси для upstream ACL | squid.conf, nftables.conf | Ansible (auto) | [DE-AC-001](DE/DE-AC-001.md) |
| DE-DM-001 | Белый список доменов (Domain Lists) | DM | Разрешённые домены AI API | squid.conf (ACL) | DevOps-инженер | [DE-DM-001](DE/DE-DM-001.md) |
| DE-CF-001 | Конфигурационные параметры | CF | Параметры inventory.yml | inventory.yml, generated configs | DevOps-инженер | [DE-CF-001](DE/DE-CF-001.md) |
| DE-LG-001 | Записи журнала доступа (Log Records) | LG | Squid access.log на access tier | Файловая система access proxy | Squid (auto) | [DE-LG-001](DE/DE-LG-001.md) |
| DE-SC-001 | Секреты (Secrets) | SC | MTProxy secret, Keepalived password | mtg.toml, inventory.yml, keepalived.conf | DevOps-инженер | [DE-SC-001](DE/DE-SC-001.md) |

## Статистика

| Группа | Количество DE | Уровень конфиденциальности |
|---|---|---|
| CR — Credentials | 1 | Высокий |
| AC — Access Control | 1 | Средний |
| DM — Domain Management | 1 | Низкий |
| CF — Configuration | 1 | Низкий-Средний |
| LG — Logging | 1 | Средний |
| SC — Secrets | 1 | Высокий |
| **Итого** | **6** | — |

## Связанные документы

- [DD-CDM.md](DD-CDM.md) — Концептуальная модель данных
- [DD-LDM.md](DD-LDM.md) — Логическая модель данных
- [DD-PDM.md](DD-PDM.md) — Физическая модель данных
- [DD-Security.md](DD-Security.md) — Классификация безопасности
- [DD-SourceMap.md](DD-SourceMap.md) — Карта источников данных
<!-- [/AIGD] -->
