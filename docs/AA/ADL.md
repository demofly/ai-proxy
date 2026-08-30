<!-- [AIGD] -->
# ADL — Журнал архитектурных решений

**Последняя правка AI:** 2026-08-29T07:00:00Z

## Реестр ADR

| ID | Название | Статус | Дата | Классификация | Детальный файл |
|---|---|---|---|---|---|
| ADR-000001 | Двухуровневая архитектура проксирования | Implemented | 2025-01-15 | Segment × Technology | [ADR-000001](ADR/ADR-000001.md) |
| ADR-000002 | Squid как прокси-движок | Implemented | 2025-01-15 | Capability × Technology | [ADR-000002](ADR/ADR-000002.md) |
| ADR-000003 | nginx SNI-маршрутизация для co-deployment | Implemented | 2025-01-20 | Capability × Technology | [ADR-000003](ADR/ADR-000003.md) |
| ADR-000004 | CrowdSec как IPS | Implemented | 2025-01-20 | Capability × Technology | [ADR-000004](ADR/ADR-000004.md) |
| ADR-000005 | MTProxy co-deployment на upstream-нодах | Implemented | 2025-02-01 | Segment × Application | [ADR-000005](ADR/ADR-000005.md) |
| ADR-000006 | Keepalived VRRP для отказоустойчивости access-уровня | Implemented | 2025-02-01 | Capability × Technology | [ADR-000006](ADR/ADR-000006.md) |
| ADR-000007 | Ansible как IaC-инструмент | Implemented | 2025-01-10 | Capability × Technology | [ADR-000007](ADR/ADR-000007.md) |
| ADR-000008 | Бюджет памяти узла: пределы служб с двукратным запасом и проверка выполнимости | Implemented | 2026-08-28 | Capability × Technology | [ADR-000008](ADR/ADR-000008.md) |
| ADR-000009 | Собственный кеширующий резолвер с каскадом access → upstream | Active | 2026-08-29 | Capability × Technology | [ADR-000009](ADR/ADR-000009.md) |

## Статистика

| Статус | Количество |
|---|---|
| Active | 9 |
| Proposed | 0 |
| Deprecated | 0 |
| Retired | 0 |
| **Итого** | **9** |

## Классификация

| Тип | Segment | Capability |
|---|---|---|
| Application | ADR-000005 | — |
| Technology | ADR-000001 | ADR-000002, ADR-000003, ADR-000004, ADR-000006, ADR-000007, ADR-000008, ADR-000009 |

## Связанные артефакты

- Консолидированное описание архитектуры: [AAD.md](AAD.md)
- Архив ADR: [ADL-archive.md](ADL-archive.md)
- Техническая документация: [TD.md](TD.md)
- Требования: [C2-PR.md](C2-PR.md)

## Статус соответствия

| Дата | Уровень | Обоснование | Корректирующее действие |
|------|---------|-------------|-------------------------|
| 2026-08-29 | 4 - Conformant | Реестр решений сверен с составом карточек и их статусами | - |
<!-- [/AIGD] -->
