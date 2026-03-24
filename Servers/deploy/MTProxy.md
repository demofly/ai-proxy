# MTProxy Configuration Reference — tgproxy.example.com

## Server Information

| Параметр | Значение |
|---|---|
| **Публичный домен** | tgproxy.example.com |
| **Fake-TLS домен** | git.example.com |
| **Порт подключения** | 443 (HTTPS) |
| **Тип маршрутизации** | nginx stream SNI-based (ssl_preread) |
| **Transit encryption** | TLS 1.3 (access→upstream, self-signed cert) |
| **Версия mtg** | 2.1.8 |

## Access Node IPs (Load Balancing)

| Хост | IP адрес | Статус |
|---|---|---|
| access01.example.com | 203.0.113.1 | Primary |
| access02.example.com | 203.0.113.2 | Secondary (failover) |

## MTProxy Secret

```
bb22cc33dd44ee55ff66001122334455066769742e6578616d706c652e636f6d
```

> ⚠️ **ВАЖНО:** Храните секрет в безопасности. Не публикуйте в открытом виде.

## Client Configuration

### Option 1: Через доменное имя (рекомендуется)

**Telegram MTProxy Link:**
```
tg://proxy?server=tgproxy.example.com&port=443&secret=bb22cc33dd44ee55ff66001122334455066769742e6578616d706c652e636f6d
```

1. Откройте ссылку в Telegram
2. Нажмите "Использовать прокси"
3. Готово!

### Option 2: Через IP адрес (fallback)

Если доменное имя не резолвится, используйте один из IP адресов:

**Access-01:**
```
tg://proxy?server=203.0.113.1&port=443&secret=bb22cc33dd44ee55ff66001122334455066769742e6578616d706c652e636f6d
```

**Access-02 (failover):**
```
tg://proxy?server=203.0.113.2&port=443&secret=bb22cc33dd44ee55ff66001122334455066769742e6578616d706c652e636f6d
```

## Troubleshooting

| Проблема | Решение |
|---|---|
| "Не удаётся подключиться" | Проверьте: 1) интернет соединение, 2) доменное имя резолвится (nslookup tgproxy.example.com), 3) секрет скопирован корректно |
| "Прокси недоступен" | Попробуйте второй access node (203.0.113.2) или альтернативный IP |
| "Медленное соединение" | Может быть нагрузка на upstream node. Попробуйте переподключиться (система автоматически переключит на другой upstream) |
| "Секрет неверный" | Убедитесь, что скопировали весь секрет целиком без пробелов |

## Advanced Options

### Manual Telegram Proxy Menu

Если ссылка не открывается:

1. Откройте Telegram → **Settings** → **Privacy and Security**
2. Выберите **Connection Type** → **Use Custom Proxy**
3. Выберите **MTProxy**
4. Заполните:
   - **Server**: `tgproxy.example.com` (или IP)
   - **Port**: `443`
   - **Secret**: `bb22cc33dd44ee55ff66001122334455066769742e6578616d706c652e636f6d`
5. Сохраните

## Security

- ✅ **DPI-resistant**: Трафик маскируется под TLS к git.example.com
- ✅ **Encrypted**: Весь трафик зашифрован (MTProxy protocol + TLS 1.3 access→upstream transit)
- ✅ **No logging**: Логирование отключено для приватности
- ✅ **Firewall**: Доступ к MTProxy на upstream только от access-нод (UFW/nftables)
- ✅ **PROXY protocol**: Реальный IP клиента пробрасывается через всю цепочку
- ✅ **CrowdSec IPS**: Автоматическая блокировка abuse-трафика, whitelist инфраструктуры

## Support

Для вопросов/проблем:
- Проверьте логи на upstream node: `journalctl -u mtg -f`
- Проверьте SNI маршрутизацию на access node: `cat /etc/nginx/stream.d/sni-map.d/aiproxy.conf`
- Проверьте SNI маршрутизацию на upstream node: `cat /etc/nginx/stream.d/sni-map.d/mtproxy.conf`
- Проверьте nginx stream конфиг: `nginx -T 2>&1 | grep -A5 'stream'`
