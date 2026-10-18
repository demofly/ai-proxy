# MTProxy: единый секрет и fake-TLS SNI max.ru

Готовый фрагмент для `all.vars` рабочего `inventory.yml`:

```yaml
mtproxy_enabled: true
mtproxy_fake_tls_domain: "max.ru"
mtproxy_hostname: ""
mtproxy_secret: ""
```

`max.ru` — имя маскировки, а не адрес вашего прокси. В Telegram укажите IP или
собственный DNS-адрес access-узла, порт 443 и общий секрет из его upstream.

Пустой `mtproxy_secret` означает разовый fallback:

1. Общий существующий секрет из `/etc/mtproxy/mtg.toml` сохраняется; при отсутствии
   TOML читается legacy `mtg.env`.
2. Новые upstream получают то же значение. Балансировщик использует только узлы
   с включённым MTProxy.
3. Только если секрета нет ни на одном узле, создаётся один общий fake-TLS secret.
   Энтропия сохраняется на управляющей машине в `Servers/deploy/secrets/` с
   закрытыми правами; каталог исключён из Git. Повторный прогон секрет не меняет.
4. Если существующие значения различаются, deployment останавливается до изменения
   служб. Оператор выбирает общий секрет; автоматической ротации нет.

Домен входит в секрет после `ee` и 16 байт ключа. Для `max.ru` суффикс равен
`6d61782e7275`. Если старый секрет кодирует другой домен, сменить только SNI нельзя.
Для явной ротации создайте новый общий секрет локально:

```bash
python3 -c "import secrets; print('ee' + secrets.token_hex(16) + '6d61782e7275')"
```

Вставьте результат в `mtproxy_secret` рабочего inventory, примените deployment
и обновите ссылки пользователей. Секрет должен совпадать на всех включённых
upstream; несовпадение или частичная ротация отвергаются preflight.

Формат ссылки (замените адрес и секрет действующими значениями):

```text
tg://proxy?server=YOUR_ACCESS_HOST&port=443&secret=YOUR_SHARED_SECRET
```

`mtproxy_hostname`, если задан, используется для адреса в выдаваемой ссылке и как
дополнительное имя маршрутизации. Межузловое реле всегда использует общий
`mtproxy_fake_tls_domain`; дополнительные имена не меняют домен внутри секрета.

На upstream оба приватных TLS-терминатора проверяют адрес access-узла по входному
PROXY-заголовку. Исходный адрес клиента на upstream не восстанавливается.

Проверка состояния:

```bash
ssh root@<upstream-host> 'systemctl status mtg nginx'
ssh root@<upstream-host> 'journalctl -u mtg -n 50'
ssh root@<access-host> 'nginx -t'
```

Локальные проверки без рабочих серверов:

```bash
python3 Servers/deploy/tests/check_mtproxy_cluster.py
python3 -m unittest discover -s Servers/deploy/tests -p 'test_mtproxy_cluster.py'
```