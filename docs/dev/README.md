<!-- [AITS] 2026-11-06T17:47:05Z -->
<!-- [AIGD] -->
# Документация разработчика

Здесь собраны сценарии на Python, которыми разработчик проверяет и порождает
артефакты проекта: тесты, нативные проверки на настоящих демонах, генераторы
примеров и барьер документации. Для развёртывания и эксплуатации они не нужны,
поэтому в руководства администратора и пользователя, в
[Ansible-инструкцию](../../Servers/deploy/README.md) и в описания клиентов не входят.

Все команды, если не сказано иное, выполняются в Linux или WSL.

## Регрессионные тесты развёртывания

Из каталога `Servers/deploy`:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Из корня репозитория тот же набор, в том числе проверки helper
`aiproxy-apply-shared-ports` для общего firewall с Matrix:

```sh
python -m unittest discover -s Servers/deploy/tests -p 'test_*.py'
```

## Нативные проверки

### Участок access → upstream с TLS

Запускается отдельно в Linux со Squid, собранным с OpenSSL:

```sh
AIPROXY_TEST_SQUID=/usr/sbin/squid python3 -m unittest discover -s tests -p test_tls_peer_native.py -v
```

Проверка использует временные конфигурацию, PID и журналы, случайные loopback-порты
и локальный TLS 1.3 peer. Проверяются SNI, передача байтов CONNECT и отказ при
чужом CA/неверном имени сертификата. Нужны права запуска Squid и пользователь
`nobody` с группой `nogroup`. Это проверка одного участка, не нагрузочный тест
и не проверка всей цепочки nginx или доступа к Facebook в рабочей сети.

### HTTPS-вход для клиентов и ACME

Проверка настоящего nginx на случайных loopback-портах:

```sh
AIPROXY_TEST_NGINX=/usr/sbin/nginx \
AIPROXY_TEST_NGINX_STREAM=/usr/lib/nginx/modules/ngx_stream_module.so \
python3 -m unittest discover -s tests -p test_https_proxy.py -v

AIPROXY_TEST_NGINX=/usr/sbin/nginx \
python3 -m unittest discover -s tests -p test_acme_cluster.py -v
```

Проверяются общий SNI router, HTTPS CONNECT, ALPN, передача блоков данных,
сохранение адреса access-клиента, прежний HTTP-вход и отказ при неверном имени
сертификата. Это локальный функциональный тест, а не замер производительности.
Отдельный HTTP-01 тест запускает два nginx с разными webroot: проверяет оба токена
через оба адреса, отсутствие циклов, удаление токенов и сохранение чужого HTTP-сайта.

### DNS и DoH

- `tests/test_dns_doh.py` — Unbound, nginx и dnsproxy. Unbound отклоняет TLS 1.2
  и принимает TLS 1.3.
- `tests/test_acme_cluster.py` — два имени и два IP.
- `tests/check_doh_budget.py` — 2000 запросов с параллелизмом 32 под реальным
  `MemoryMax=32M` в тестовой VM.
- `tests/check_doh_idle.py` наблюдает реальное соединение более пяти минут,
  проверяет сохранение до таймаута и новое соединение после него.

### MTProxy

Локальные проверки без рабочих серверов, из корня репозитория:

```sh
python3 Servers/deploy/tests/check_mtproxy_cluster.py
python3 -m unittest discover -s Servers/deploy/tests -p 'test_mtproxy_cluster.py'
```

### Пулы пользователей

Из каталога `Servers/deploy`, без root:

```sh
python3 tests/check_proxy_pools_native.py --cache ~/.cache/ai-proxy-validation
```

Кеш готовит `tests/prepare_native_validation.py`. Проверка поднимает настоящий Squid
с двумя локальными родителями на 127.0.0.1 и синтетическими паролями. Сценарии:

- контроль без `cache_peer_access`: пользователи пула расходятся по обоим родителям;
- GET и CONNECT: пользователь ходит только через upstream своего пула, член двух
  групп — через объединение;
- пул без upstream и пользователь вне пулов получают 403, запрос без учётных данных — 407;
- при `allow_direct_fallback: true` CONNECT по-прежнему идёт через родителей пула.

### Сквозная проверка стека

`tests/prepare_native_validation.py`, затем `tests/native_proxy_validation.py`
от root внутри `unshare -n` с `--cache` на подготовленный кеш. Отдельно —
`tests/check_resource_plan.py` и `tests/check_systemd_budget.py` (root).
Сквозная проверка сейчас не проходит: в ней не стартует Unbound
(разрыв GAP-160 в [реестре разрывов](../AA/Ideas.md)).

## Расчёт памяти служб

Жёсткие минимумы служб и распределение остатка бюджета памяти заданы в
фильтре `Servers/deploy/filter_plugins/resources.py`. Порядок расчёта для
администратора описан в разделе «Бюджет памяти узла» Ansible-инструкции.

## Примеры конечных конфигураций

В Linux/WSL с Ansible и PyYAML, из корня проекта:

```sh
python3 Servers/examples/render.py
python3 Servers/examples/render.py --check
```

Генерация выполняет только локальные `set_fact`, `template`, `copy` и `file`
во временном каталоге, затем сохраняет результат в `Servers/examples`.
Она не запускает основной playbook, не устанавливает пакеты и не подключается
к адресам примера. Расчёт ресурсов и тела inline-конфигов берутся из реальных
задач деплоймента. `--check` повторно генерирует файлы во временном каталоге
и проверяет их соответствие сохранённым образцам без изменения проекта.

## Каталог правил FoxyProxy

Добавляйте подтверждённые хосты с `basis: "rkn"`, ссылкой на снимок и
`registry_entries`. Для `domains` требуется запись `*.имя` в реестре, для `hosts` —
точная запись. Блокировка отдельной страницы чужого арендатора не разрешает включить
всю платформу Notion, Replit, Lovable или общий облачный домен.
Изменение исключений `basis: "user"` — отдельное явное решение владельца.

```powershell
python Clients/FoxyProxy/rules.py
python Clients/FoxyProxy/rules.py --check
python -m unittest discover -s Clients/FoxyProxy -p test_rules.py -v
python Clients/FoxyProxy/verify_registry.py C:/Private/dump.csv.gz
```

Последняя команда сверяет SHA256, дату и каждое добавление с зафиксированным снимком.
Проверки маршрутизации не доказывают доступность сайтов или качество проигрывания видео.

## Барьер документации

Из корня репозитория:

```sh
python Servers/audit/check_docs.py
python Servers/audit/gen_lifecycle.py --check
```

`check_docs.py` сверяет корпус `docs/AA` и печатает итог тремя числами: выполнено,
пропущено с причиной, открыто. Среди проверок — отсутствие значений рабочего
`inventory.yml` в отслеживаемых файлах, безличные имена узлов рабочего инвентори
(`access-NN`, `upstream-NN`) и отсутствие ссылок на сценарии Python в документации
пользователя и администратора. `gen_lifecycle.py` порождает реестр жизненного цикла
и панель зрелости, а с `--check` только сверяет их с корпусом.
<!-- [/AIGD] -->
