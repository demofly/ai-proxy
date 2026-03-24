<!-- [AIGD] -->
# ARR — Architecture Requirements Repository

## Dashboard

| Слой | Всего | Conformance ≥3 | Conformance <3 | Средний | Open Gaps |
|---|---|---|---|---|---|
| C1 | 4 | 4 | 0 | 4.0 | 0 |
| C2 | 15 | 15 | 0 | 4.0 | 2 |
| C3 | 8 | 8 | 0 | 4.0 | 0 |
| C4 | 11 | 11 | 0 | 4.0 | 0 |
| TD | 4 | 4 | 0 | 4.0 | 0 |
| DD | 11 | 11 | 0 | 4.0 | 1 |
| ADL | 7 | 7 | 0 | 4.0 | 0 |
| CC | 5 | 5 | 0 | 4.0 | 0 |
| **Итого** | **65** | **65** | **0** | **4.0** | **4** |

## Ограничения (Constraints)

| ID | Тип | Описание | Источник | Связанные артефакты |
|---|---|---|---|---|
| ACN-001 | Technical | Двухуровневая архитектура: access (РФ) + upstream (вне РФ) — обязательное разделение | [ADR-000001](ADR/ADR-000001.md) | [C2-CN-001](C2/C2-CN-001.md) |
| ACN-002 | Technical | Порт 443 — единственный внешний порт (co-deployment через SNI) | [ADR-000003](ADR/ADR-000003.md) | [C2-CN-002](C2/C2-CN-002.md) |
| ACN-003 | Regulatory | Секреты в inventory.yml хранятся без шифрования (рекомендуется Ansible Vault) | [C4-PB-002](C4/C4-PB-002.md) | [Ideas.md](Ideas.md) IDEA-003 |
| ACN-004 | Technical | read_timeout = 30 minutes — длинные AI API ответы не должны обрываться | [C4-TM-001](C4/C4-TM-001.md) | [C2-FR-001](C2/C2-FR-001.md) |

## Принципы (Principles)

| ID | Описание | Обоснование | Связанные артефакты |
|---|---|---|---|
| APN-001 | Stateless access-прокси — никакого состояния кроме кэша | Горизонтальное масштабирование, VRRP failover | [C2-NF-004](C2/C2-NF-004.md), [ADR-000006](ADR/ADR-000006.md) |
| APN-002 | Анонимизация трафика на upstream — удаление всех идентифицирующих заголовков | Безопасность, невозможность атрибуции | [C2-NF-002](C2/C2-NF-002.md), [ADR-000001](ADR/ADR-000001.md) |
| APN-003 | Infrastructure as Code — вся инфраструктура определяется в коде | Воспроизводимость, версионирование, аудит | [ADR-000007](ADR/ADR-000007.md) |
| APN-004 | Default deny firewall — whitelist-only доступ на upstream | Минимизация поверхности атаки | [C2-NF-002](C2/C2-NF-002.md), [C4-TM-004](C4/C4-TM-004.md) |

## Допущения (Assumptions)

| ID | Описание | Статус | Связанные артефакты |
|---|---|---|---|
| AAS-001 | Access-прокси расположены в РФ, upstream — за рубежом | Active | [ADR-000001](ADR/ADR-000001.md) |
| AAS-002 | Все AI API доступны через HTTPS CONNECT tunneling | Active | [C2-FR-001](C2/C2-FR-001.md) |
| AAS-003 | Basic Auth достаточен для аутентификации (малая команда) | Active | [C2-FR-002](C2/C2-FR-002.md) |
| AAS-004 | Keepalived VRRP включён для отказоустойчивости access-уровня | Validated | [C2-NF-001](C2/C2-NF-001.md) |
| AAS-005 | Squid 6.x поддерживает все необходимые функции (SMP, userhash, PROXY protocol) | Validated | [ADR-000002](ADR/ADR-000002.md) |

## Зависимости (Dependencies)

| ID | Тип | От | К | Описание | Связанные артефакты |
|---|---|---|---|---|---|
| ADP-001 | Inter-Component | [C3-NX-001](C3/C3-NX-001.md) | [C3-SA-001](C3/C3-SA-001.md) | nginx → Squid Access (PROXY protocol на 127.0.0.1:3128) | [ADR-000003](ADR/ADR-000003.md) |
| ADP-002 | Inter-Component | [C3-SA-001](C3/C3-SA-001.md) | [C3-SU-001](C3/C3-SU-001.md) | Squid Access → Squid Upstream (cache_peer) | [ADR-000001](ADR/ADR-000001.md) |
| ADP-003 | Inter-Component | [C3-NX-001](C3/C3-NX-001.md) | [C3-MT-001](C3/C3-MT-001.md) | nginx → MTProxy (SNI routing example.gov.ru) | [ADR-000005](ADR/ADR-000005.md) |
| ADP-004 | Inter-Component | [C3-CS-001](C3/C3-CS-001.md) | [C3-SA-001](C3/C3-SA-001.md) | CrowdSec → Squid (acquisition access.log) | [ADR-000004](ADR/ADR-000004.md) |
| ADP-005 | External | [C3-SA-001](C3/C3-SA-001.md) | AI API | Squid Upstream → внешние AI API (OpenAI, Anthropic, Google и др.) | [C1-BC-003](C1/C1-BC-003.md) |
| ADP-006 | Inter-Component | [C3-KA-001](C3/C3-KA-001.md) | [C3-SA-001](C3/C3-SA-001.md) | Keepalived → Squid (health check: killall -0 squid) | [ADR-000006](ADR/ADR-000006.md) |
| ADP-007 | Inter-Component | [C3-DN-001](C3/C3-DN-001.md) | [C3-SA-001](C3/C3-SA-001.md), [C3-SU-001](C3/C3-SU-001.md) | Unbound DNS → Squid (dns_nameservers 127.0.0.1); access unbound → upstream unbound | — |

## Стандарты (Standards)

| ID | Стандарт | Соответствие | Описание | Связанные артефакты |
|---|---|---|---|---|
| AST-001 | Squid Configuration Best Practices | Full | Анонимизация, SMP, кеширование, ACL | [C3-SA-001](C3/C3-SA-001.md) |
| AST-002 | nftables Hardened Firewall | Full | Default deny, whitelist-only | [C4-TM-004](C4/C4-TM-004.md) |
| AST-003 | CrowdSec Community Collections | Full | linux, nginx, http-cve, whitelist-good-actors | [C3-CS-001](C3/C3-CS-001.md) |
| AST-004 | Ansible Best Practices | Full | Идемпотентность, roles, handlers, tags | [C3-AD-001](C3/C3-AD-001.md) |

## Кросс-ссылки

- [C1-BR.md](C1-BR.md) — бизнес-контекст
- [C2-PR.md](C2-PR.md) — требования
- [C3-CR.md](C3-CR.md) — компоненты
- [C4-SR.md](C4-SR.md) — спецификации кода
- [TD.md](TD.md) — техническая документация
- [ADL.md](ADL.md) — архитектурные решения
- [DD.md](DD.md) — архитектура данных
- [Ideas.md](Ideas.md) — gaps и идеи
<!-- [/AIGD] -->
