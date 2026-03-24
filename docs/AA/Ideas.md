<!-- [AIGD] -->
# Ideas — Пробелы и идеи

## Секция Gaps

| ID | Слой | Класс | Описание | Разрешение | Статус | Корректирующее действие |
|---|---|---|---|---|---|---|
| GAP-001 | C2 | New | Отсутствуют автоматизированные тесты инфраструктуры | Code | Open | Рассмотреть Molecule / Testinfra для тестирования Ansible roles |
| GAP-002 | C3 | New | Нет мониторинга / алертинга (Prometheus, Grafana) | Docs+Code | Open | Рассмотреть добавление стека мониторинга как отдельного компонента C3 |
| GAP-003 | [C2-NF-001](C2/C2-NF-001.md) | Divergent | Keepalived описан как disabled, фактически `enable_keepalived: true` в inventory | Doc | Closed | Исправлено: актуализация 2026-03-24 (AAS-004 → Validated) |
| GAP-004 | DD | New | Отсутствует ротация логов (logrotate) для Squid access.log | Code | Open | Добавить конфигурацию logrotate в Ansible-роль или шаблон |
| GAP-005 | [C2-NF-002](C2/C2-NF-002.md) | New | Нет TLS на участке клиент → access proxy при использовании Basic Auth | Code | Open | Рассмотреть TLS termination на access-прокси или переход на CONNECT-only режим для защиты credentials |
| GAP-006 | C4-PB-002 | Divergent | CrowdSec memory values расходились с кодом (200→512, 64→128) | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-007 | DD-PDM | Divergent | logformat указан как custom `aiproxy`, фактически используется стандартный `squid` | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-008 | C4-TM-004 | Absent | Правила nftables для MTProxy port 443 не были задокументированы | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-009 | C4-PB-002 | Divergent | IP-адреса и имена хостов расходились с кодом (example IPs, generic names) | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-010 | ARR | Absent | Отсутствовал ARR.md (Architecture Requirements Repository) | Doc | Closed | Создан: актуализация 2026-03-15 |
| GAP-011 | §2.4 | New | Отсутствуют файлы TD-Metrics.md, TD-Events.md, TD-Logs.md (требуются по §2.4) | Doc | Open | Создать при следующей актуализации TD |
| GAP-012 | §2.4 | New | Отсутствует CC-CM.md (Configuration Management) | Doc | Open | Создать при следующей актуализации CC |
| GAP-013 | §2.3.1 | New | Группы C2/C3/C4 используют нестандартные коды (FR/NF/CN, SA/SU/NX и др.) вместо канонических (TSF/INT/SVC/CLI/LIB/DOC/NFR) | Doc | Open | Переклассификация при следующем Gate |
| GAP-014 | ADR-000005 | Divergent | Диаграмма MTProxy: google.com вместо cloudflare.com, порт 4443 вместо 2083, отсутствовала двухуровневая архитектура | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-015 | ADR-000003 | Divergent | Диаграмма SNI routing: порт 3129 вместо 3128, google.com вместо cloudflare.com, неверные имена upstream | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-016 | ADR-000006 | Divergent | Диаграмма VRRP: priority=50 вместо 90, pgrep вместо killall -0 | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-017 | ADR-000007 | Divergent | Диаграмма Ansible: несуществующие роли (squid_access, keepalived, nginx_sni, clients), generic host names | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-018 | TD-deployment | Divergent | VIP IP 45.151.144.129 вместо 1.2.3.4, отсутствовал nginx на upstream, Squid Upstream :443 вместо localhost:3128 | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-019 | TD-network | Divergent | Отсутствовал nginx SNI Router на upstream нодах, порт 2083 показан как внешний | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-020 | CC-lifecycle | Divergent | Состояние implemented вместо current, переход outdated→draft вместо outdated→review, V1-V17 вместо V1-V22 | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-021 | DD-LDM | Divergent | url_regex вместо dstdom_regex, logformat aiproxy вместо squid | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-022 | DD-PDM | Divergent | Отсутствовали nginx конфиги на обоих уровнях, logformat aiproxy вместо squid, nftables на access — не Ansible | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-023 | DD-SourceMap | Divergent | Nginx шаблоны/конфиги упрощены до единой записи, отсутствовал nftables шаблон | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-024 | C2-FR-002 | Divergent | Auth realm «AI Proxy» вместо «Squid Proxy Authentication» | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-025 | C2-FR-004 | Divergent | Тип кэш-хранилища aufs вместо ufs, maximum_object_size 512 MB вместо 50 MB, refresh_pattern отсутствует в шаблоне, cache_dir fixed 100 MB вместо формулы | Doc | Closed | Частично 2026-03-15, полностью 2026-03-24 (C2-FR-004, TD-TA) |
| GAP-026 | C2-NF-001-vrrp | Divergent | Backup priority=50 вместо 90, логика failover note некорректна | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-027 | C2-NF-001-upstream | Divergent | Алгоритм fallback «sourcehash» — в реальности Squid перестраивает userhash-кольцо среди живых peers | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-028 | C2-NF-002-anon | Divergent | forwarded_for delete вместо off, request_header_access deny all вместо выборочных заголовков, visible_hostname localhost отсутствует в коде | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-029 | C2-CN-001 | Divergent | nginx SNI Router отсутствовал в access tier потоке | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-030 | C3-component | Divergent | nginx SNI Router отсутствовал на upstream tier, MTProxy routing упрощён — отсутствовали TLS relay и upstream nginx | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-031 | C1-BC-001 | Divergent | MTProxy показан с прямой связью от access; в реальности mtg работает только на upstream нодах. AI API cloud показывал только 4 из 9+ провайдеров | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-032 | C1-BC-002 | Divergent | MTProxy sequence — отсутствовал двухуровневый relay (access nginx → upstream nginx → mtg), показан единый nginx | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-033 | C1-BC-003 | Divergent | Отсутствовали 5 AI-провайдеров: Mistral AI, Groq, DeepSeek, Cerebras, SambaNova | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-034 | C2-FR-001 | Divergent | ACL тип url_regex вместо dstdom_regex | Doc | Closed | Исправлено: актуализация 2026-03-15 |
| GAP-035 | C1-BC-002 | Divergent | actors.puml: MTProxy порт :4443 вместо SNI route :2083, SNI=cloudflare.com вместо git.example.com, cache_peer без порта :80 | Doc | Closed | Исправлено: пропагация 2026-03-17 |
| GAP-036 | C2-CN-001 | Divergent | two-tier-flow.puml: nftables вместо UFW, cache_peer :443 вместо :80, отсутствовал PROXY protocol | Doc | Closed | Исправлено: пропагация 2026-03-17 |
| GAP-037 | C3-SU-001 | Divergent | Upstream Squid: порт 443 вместо 80, DNS множественные резолверы вместо unbound localhost, nftables вместо UFW | Doc | Closed | Исправлено: пропагация 2026-03-17 |
| GAP-038 | C2-NF-001 | Divergent | Upstream nodes: 2 вместо 1, inventory upstreams 2 ноды вместо 1 | Doc | Closed | Исправлено: пропагация 2026-03-17 |
| GAP-039 | C2-NF-002 | Divergent | forwarded_for delete вместо off, table inet filter вместо UFW, nftables rules вместо UFW tasks | Doc | Closed | Исправлено: пропагация 2026-03-17 |
| GAP-040 | docs/AA | Divergent | mtproxy_fake_tls_domain cloudflare.com вместо git.example.com: C3-MT-001, C3-NX-001, C2-FR-006, C2-CN-002, C4-RL-002, DE-CF-001, DE-SC-001, ARR, DD-Glossary, ADR-000003-sni-routing.puml | Doc | Closed | Исправлено: пропагация 2026-03-17 |
| GAP-041 | DD-PDM | Divergent | /etc/nftables.conf entity с table inet filter вместо UFW Firewall | Doc | Closed | Исправлено: пропагация 2026-03-17 |
| GAP-042 | C2-FR-008 | Divergent | Inventory пример: upstream-2 вместо 1 upstream | Doc | Closed | Исправлено: пропагация 2026-03-17 |
| GAP-043 | docs/AA | Divergent | mtproxy_fake_tls_domain git.example.com вместо example.gov.ru: C2-FR-006, C2-CN-002, C3-MT-001, C3-NX-001, C4-RL-002, C4-PB-002, DE-CF-001, DE-SC-001, ARR, DD-Glossary, ADR-000003/000005.puml, C1-BC-002-actors.puml | Doc | Closed | Исправлено: пропагация 2026-03-17 |
| GAP-044 | C3, C4, TD | Absent | DNS Resolver (Unbound) — роль `dns_resolver` и компонент полностью отсутствовали в документации | Doc | Closed | Исправлено: актуализация 2026-03-24 (C3-CR, C4-SR, TD-TA, ARR, C3-DN-001.md, C4-RL-004.md) |
| GAP-045 | C4 | Absent | Шаблон `check_and_restart_squid.sh.j2` не был задокументирован в C4-SR | Doc | Closed | Исправлено: актуализация 2026-03-24 (C4-TM-005) |
| GAP-046 | ARR | Divergent | AAS-004: Keepalived описан как «потребуется при росте», фактически уже включён (`enable_keepalived: true`) | Doc | Closed | Исправлено: актуализация 2026-03-24 (AAS-004 → Validated) |
| GAP-047 | C4-PB-001/002, DE-CF-001 | Divergent | `enable_keepalived`, `crowdsec_enabled`, `mtproxy_enabled` показаны как `false`, фактически `true` в inventory; `read_timeout` 15 min вместо 30 min | Doc | Closed | Исправлено: актуализация 2026-03-24 |
| GAP-048 | C2-PR, TD-Matrices | Divergent | Упоминания `aufs` вместо `ufs` в реестре C2-PR.md и матрице TD-Matrices.md §M8 | Doc | Closed | Исправлено: актуализация 2026-03-24 |

## Секция Ideas

| ID | Описание | Приоритет | Разрешение | Связанные артефакты |
|---|---|---|---|---|
| IDEA-001 | Централизованный мониторинг с Prometheus + Grafana: сбор метрик Squid, CrowdSec, Keepalived, системных ресурсов | Medium | Docs+Code | [C2-NF-005](C2/C2-NF-005.md), GAP-002 |
| IDEA-002 | Автоматическая ротация MTProxy secrets: периодическая генерация нового secret и обновление конфигурации клиентов | Low | Code | [C2-FR-006](C2/C2-FR-006.md) |
| IDEA-003 | Ansible Vault для шифрования секретов в inventory: htpasswd хеши, MTProxy secret, IP-адреса | High | Code | [C2-NF-002](C2/C2-NF-002.md), [CC-Risks](CC/CC-Risks.md) |
| IDEA-004 | Добавление Wireguard VPN как альтернативного транспорта между access и upstream нодами | Low | Code | [C2-CN-001](C2/C2-CN-001.md), [C2-NF-002](C2/C2-NF-002.md) |
| IDEA-005 | Интеграция с корпоративным LDAP/AD для аутентификации вместо htpasswd | Medium | Code | [C2-FR-002](C2/C2-FR-002.md) |
<!-- [/AIGD] -->
