<!-- [AIGD] -->
# DE-LG-001 — Записи журнала доступа (Log Records)

## Описание

Записи журнала доступа — структурированные записи в файле access.log, генерируемые Squid daemon'ом на access-прокси при каждом HTTP-запросе. Используются для аудита обращений, анализа угроз (CrowdSec acquisition) и диагностики.

## Атрибуты

| Атрибут | Тип | Описание | Обязательность |
|---|---|---|---|
| timestamp | datetime (Unix timestamp.ms) | Метка времени запроса | Обязательный |
| duration | integer (мс) | Время обработки запроса | Обязательный |
| client_ip | IPv4 address | IP-адрес клиента | Обязательный |
| squid_status | string | Squid result code (TCP_TUNNEL, TCP_MISS и т.д.) | Обязательный |
| http_status | integer (3 цифры) | HTTP-код статуса ответа | Обязательный |
| bytes | integer | Размер ответа в байтах | Обязательный |
| method | string | HTTP-метод (CONNECT, GET, POST) | Обязательный |
| url | string | Запрошенный URL или хост:порт | Обязательный |
| username | string | Имя аутентифицированного пользователя или «-» | Необязательный |
| hierarchy | string | Код иерархии Squid / IP сервера | Обязательный |
| content_type | string | MIME-тип ответа или «-» | Необязательный |

## Хранилище

| Параметр | Значение |
|---|---|
| **Путь** | `/var/log/squid/access.log` |
| **Формат** | Squid custom logformat `aiproxy` |
| **Кодировка** | UTF-8 |
| **Файловые права** | 640 (`proxy:proxy`) |
| **Генерация** | Squid daemon (автоматически при каждом запросе) |
| **Ротация** | logrotate (ежедневно или по размеру) |
| **Компонент** | [C3-SA-001](../../C3/C3-SA-001.md) — Squid Access Proxy |

**Формат logformat:**
```
# AI-GENERATED — NOT REVIEWED: SECTION START
access_log daemon:/var/log/squid/access.log squid
# AI-GENERATED — NOT REVIEWED: SECTION END
```

**Пример записи:**
```
1708700400.123  12345 192.168.1.1 TCP_TUNNEL/200 1234 CONNECT api.openai.com:443 john HIER_DIRECT/104.18.7.192 -
```

**Разбор полей:**

| Позиция | Значение примера | Директива | Атрибут |
|---|---|---|---|
| 1 | `1708700400.123` | `%ts.%03tu` | timestamp |
| 2 | `12345` | `%6tr` | duration (мс) |
| 3 | `192.168.1.1` | `%>a` | client_ip |
| 4 | `TCP_TUNNEL/200` | `%Ss/%03>Hs` | squid_status/http_status |
| 5 | `1234` | `%<st` | bytes |
| 6 | `CONNECT` | `%rm` | method |
| 7 | `api.openai.com:443` | `%ru` | url |
| 8 | `john` | `%un` | username |
| 9 | `HIER_DIRECT/104.18.7.192` | `%Sh/%<a` | hierarchy |
| 10 | `-` | `%mt` | content_type |

## Жизненный цикл

| Стадия | Действие | Актор | Инструмент |
|---|---|---|---|
| **Create** | Запись при каждом HTTP-запросе | Squid daemon | access_log directive |
| **Store** | Хранение на файловой системе | Файловая система | — |
| **Use** | Анализ на угрозы | CrowdSec (acquisition, tail mode) | Parsers + scenarios |
| **Use** | Аудит обращений | DevOps-инженер | Ручной анализ / скрипты |
| **Archive** | Ротация | logrotate | Cron job: ежедневно |
| **Dispose** | Удаление по TTL | logrotate | `rotate N`, `maxage` |

## Безопасность

| Параметр | Значение |
|---|---|
| **Уровень конфиденциальности** | Средний |
| **Обоснование** | Содержит IP-адреса клиентов и имена пользователей |
| **Файловые права** | 640 (`proxy:proxy`) — не доступен другим пользователям |
| **Хранение** | Только на access tier; не передаётся за пределы хоста |
| **Ротация** | logrotate с TTL для ограничения накопления ПДн |
| **Содержимое URL** | Только хост:порт (CONNECT), тело запросов не логируется |

## Связанные требования

- [C2-FR-005](../../C2/C2-FR-005.md) — Журналирование и аудит
- [C2-NF-002](../../C2/C2-NF-002.md) — Безопасность (CrowdSec анализ)
- [C2-NF-005](../../C2/C2-NF-005.md) — Наблюдаемость
- [C3-SA-001](../../C3/C3-SA-001.md) — Squid Access Proxy (генератор)
- [C3-CS-001](../../C3/C3-CS-001.md) — CrowdSec IPS (потребитель)
<!-- [/AIGD] -->
