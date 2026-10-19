# Примеры конечных конфигураций

Здесь лежат **отрендеренные конфиги**, а не Jinja2-шаблоны и не копии файлов
рабочих серверов. Их источник — действующие шаблоны и `copy.content` задач
[деплоймента](../deploy/). Пути установки и исходники каждого файла перечислены
в [manifest.json](manifest.json).

## Сценарий

Исходные параметры берутся только из публичного
[inventory.yml.sample](../deploy/inventory.yml.sample). Генератор включает
дополнительные возможности для демонстрации полного состава файлов:

- Два access: `203.0.113.1` и `203.0.113.2`; два upstream:
  `198.51.100.11` и `198.51.100.12`. Это документационные диапазоны.
- На каждом узле условно 961 МиБ RAM и 2 CPU, без соседних приложений.
- HTTPS-прокси `proxy.example.com:443`, TLS 1.2/1.3 для клиентов;
  межузловой Squid TLS с проверкой сертификата `transit.internal`.
- Публичный DoH `https://dns.example.com/q` на обоих access, TLS 1.2/1.3 и HTTP/2.
- Access → upstream только DoH через SNI :443, TLS 1.3 без проверки сертификата;
  постоянные HTTP/2-соединения с idle timeout 300 с, dnsproxy на loopback.
- HTTP-01 обоих HTTPS-имён через оба access с собственным сертификатом
  и ключом у каждого узла, поиском отсутствующего токена у соседа.
- MTProxy с fake-TLS SNI `max.ru`; межузловой relay использует TLS 1.3.
- CrowdSec, локальный Unbound, dnsproxy на access, healthcheck и автоматические обновления
  безопасности; Keepalived включён для демонстрации необязательного VRRP.

Это отдельный показательный сценарий. HTTPS и межузловой TLS по-прежнему
требуют явного включения в рабочем inventory; Keepalived также необязателен.
Реальные адреса, имена узлов, пользователи, пароли, сертификаты и ключи из
`deploy/inventory.yml`, `deploy/passwd`, `deploy/tls/` и `deploy/secrets/`
генератор **не читает**.

Показанный секрет MTProxy содержит нулевой ключ, а пароль VRRP — `DEMOONLY`.
Они публичны и предназначены только для примера. Для эксплуатации нужны свои
значения. Хеши паролей Squid, приватные ключи и сертификаты в примеры не входят;
пути к ним в конфигах соответствуют путям деплоймента. Публичные адреса DNS и
домен маскировки `max.ru` — настройки служб, а не реквизиты рабочего inventory.

Staged конфиги и unit также показаны: перед переключением они отделены от
активных файлов. Файлы подтверждённых digests — изменяемое состояние сервера,
поэтому в примеры не входят.

## Состав

[access/](access/) соответствует `access-01`, [upstream/](upstream/) —
`upstream-01`. Остальные узлы той же роли отличаются адресами, именем узла,
приоритетом VRRP и составом соседей ACME. Например, в HTTP-01 vhost второго
access адрес соседа будет `203.0.113.1:80` вместо `203.0.113.2:80`.

Кроме исторических `squid.conf`, `keepalived.conf` и `nftables.conf`, относительные
пути внутри каталогов ролей повторяют `/etc/`; пути `usr/…` повторяют `/usr/…`.
Точное соответствие приведено в манифесте.

| Группа файлов | Содержание и условия применения |
|---|---|
| `aiproxy/dnsproxy.yml`, `systemd/system/aiproxy-doh.service` | Локальный DoH-транспорт access, pinned binary и предел памяти |
| `nginx/stream.d/12-aiproxy-doh.conf`, `sni-map.d/aiproxy-doh.conf` | Публичный TLS/HTTP2 DoH access |
| `nginx/conf.d/aiproxy-dns-doh-acme.conf` | HTTP-01 отдельного DoH-имени через оба IP |
| `squid.conf` | Клиентская аутентификация и parent pool на access; анонимный транспорт на upstream; loopback manager 3129, keepalive, текущие таймауты и пределы памяти |
| `nginx/nginx.conf` | Самостоятельный пример базового файла с модулем stream, worker/FD-пределами и подключением `conf.d`/`stream.d` |
| `nginx/stream.d/00-sni-router.conf` | Общий публичный 443, SNI routing, PROXY protocol, fallback на Squid 3128 |
| `nginx/stream.d/10-aiproxy-capacity.conf` | Общая зона ограничения числа транзитных сессий |
| `nginx/stream.d/10-aiproxy-upstreams.conf` | Access: MTProxy pool и TLS relay 9443 |
| `nginx/stream.d/11-aiproxy-https-proxy.conf` | Access: клиентский HTTPS TLS-терминатор 4445 → Squid 3128 |
| `nginx/stream.d/10-mtproxy-tls.conf` | Upstream: TLS-терминатор 4443 → mtg 2083, доступ только от access |
| `nginx/stream.d/20-squid-tls-term.conf` | Upstream: TLS-терминатор 4444 → Squid 3128; исходный клиентский IP намеренно не восстанавливается |
| `nginx/stream.d/sni-map.d/` | Карты HTTPS-прокси, MTProxy и Squid transit для своей роли |
| `nginx/conf.d/aiproxy-https-acme.conf` | Access: HTTP-01 на 80, локальный токен и одношаговая пересылка соседу, защита от циклов |
| `letsencrypt/renewal-hooks/deploy/10-aiproxy-nginx` | Проверка и graceful reload nginx после продления сертификата |
| `unbound/unbound.conf`, `resolv.conf`, `systemd/resolved.conf.d/no-stub.conf` | Локальный DNS; access → upstream; upstream → публичные DNS по обычному DNS, ACL клиентов, DNSSEC и ограниченные кеши |
| `mtproxy/mtg.toml`, `mtproxy/users.txt` | Upstream: параметры mtg, предел сессий и демонстрационный административный реестр; реестр не создаёт отдельных секретов пользователей |
| `crowdsec/` | Источники журналов, whitelist узлов и локальное ограничение SQLite; штатного обнаружения перебора Squid по 407 нет |
| `systemd/system/` | Общий `aiproxy.slice`, индивидуальные ограничения служб, mtg, healthcheck и таймер, интеграция общих портов |
| `resources.json` | Расчёт памяти: 412 МиБ на access с VRRP, 400 МиБ на upstream; минимумы служб выше RAM/3, предел 1 ГБ и резерв ОС соблюдены |
| `usr/local/sbin/` | Проверка Squid с cooldown, применение контракта общих портов и синхронизация CrowdSec Hub по сроку/дрейфу с подтверждением применения |
| `keepalived.conf`, `keepalived/check_and_restart_squid.sh` | Необязательный VRRP; его проверка использует тот же healthcheck, что и таймер |
| `nftables.conf`, `shared-host/matrix-ports.nft` | Вариант upstream с nftables; файл Matrix изначально содержит `return`, соседний проект дополняет его сам |
| `iptables/`, `systemd/system/aiproxy-firewall.service` | Альтернативный upstream backend iptables/ip6tables; не применяется одновременно с вариантом nftables |
| `shared-host/aiproxy-firewall-backend` | Выбор механизма: в примере access — UFW, upstream — nftables; при выборе iptables маркер меняется на `iptables` |
| `sysctl.conf`, `security/limits.d/99-proxy.conf` | Только параметры, которыми управляет проект; чужие настройки узла не копируются |
| `ssh/sshd_config` | Только управляемая директива `UseDNS no`; остальные настройки SSH остаются за владельцем узла |
| `logrotate.d/squid` | Access: единственный файл ротации журналов Squid |
| `apt/` | Репозиторий CrowdSec и правила автоматических обновлений безопасности без автоматической перезагрузки |

`nginx.conf` — собранный самостоятельный образец: деплоймент в реальности правит
управляемые директивы и include в пакетном файле, сохраняя настройки соседей.
`sysctl.conf` также показывает только управляемые проектом записи.
`crowdsec/config.yaml.local` показан для чистой установки SQLite без чужих
переопределений; на существующем узле роль сохраняет остальные настройки.

Полные пакетные конфиги CrowdSec/bouncer, их API-ключи, данные ACME-аккаунтов,
создаваемые Certbot renewal-файлы и DNSSEC root key создаются соответствующими
утилитами и пакетами. Они зависят от узла и не подменяются выдуманными копиями.
Файлы Matrix и других соседей также принадлежат их проектам.
UFW настраивается задачами Ansible через модуль UFW, а не отдельным шаблоном
`user.rules`; поэтому примеры upstream firewall находятся в двух описанных
альтернативных форматах, а полный рабочий дамп UFW сюда не копируется.

## Обновление

В Linux/WSL с Ansible и PyYAML, из корня проекта:

```bash
python3 Servers/examples/render.py
python3 Servers/examples/render.py --check
```

Генерация выполняет только локальные `set_fact`, `template`, `copy` и `file`
во временном каталоге, затем сохраняет результат в этой директории.
Она не запускает основной playbook, не устанавливает пакеты и не подключается
к адресам примера. Расчёт ресурсов и тела inline-конфигов берутся из реальных
задач деплоймента. `--check` повторно генерирует файлы во временном каталоге
и проверяет их соответствие сохранённым образцам без изменения проекта.

Для рабочего развёртывания используйте [Ansible-инструкцию](../deploy/README.md),
а эти файлы — для изучения результата и проверки согласованности настроек.
