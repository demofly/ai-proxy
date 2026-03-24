<!-- [AIGD] -->
# DE-SC-001 — Секреты (Secrets)

## Описание

Секреты — конфиденциальные значения, используемые компонентами системы для аутентификации и шифрования: MTProxy secret (hex-строка для fake-TLS маскировки), Keepalived password (аутентификация VRRP-протокола). Определяются в inventory.yml и пропагируются через Ansible на целевые серверы.

## Атрибуты

| Атрибут | Тип | Описание | Обязательность |
|---|---|---|---|
| name | string | Идентификатор секрета (имя переменной inventory) | Обязательный |
| value | string | Значение секрета | Обязательный |
| type | enum {hex, string} | Формат значения | Обязательный |
| scope | enum {access, upstream, global} | Область применения | Обязательный |

## Реестр секретов

| Имя переменной | Тип | Scope | Назначение | Целевой файл | Компонент |
|---|---|---|---|---|---|
| `mtproxy_secret` | hex | global | Секрет MTProxy (fake-TLS шифрование) | `/etc/mtproxy/mtg.toml` | [C3-MT-001](../../C3/C3-MT-001.md) |
| `keepalived_auth_pass` | string | access | Пароль аутентификации VRRP | `/etc/keepalived/keepalived.conf` | [C3-KA-001](../../C3/C3-KA-001.md) |

## Хранилище

### Источник (SSOT) — inventory.yml

| Параметр | Значение |
|---|---|
| **Путь** | `Servers/deploy/inventory.yml` |
| **Формат** | YAML |
| **Переменные** | `mtproxy_secret`, `keepalived_auth_pass` |
| **Контроль** | Git (VCS) |

### Целевые файлы

#### mtg.toml (MTProxy secret)

| Параметр | Значение |
|---|---|
| **Путь** | `/etc/mtproxy/mtg.toml` |
| **Формат** | TOML: `secret = "<hex>"` |
| **Файловые права** | 640 (`root:mtproxy`) |
| **Генерация** | Ansible: Jinja2 template |
| **Хосты** | upstream-прокси |

#### keepalived.conf (VRRP password)

| Параметр | Значение |
|---|---|
| **Путь** | `/etc/keepalived/keepalived.conf` |
| **Формат** | Keepalived config: `auth_pass <password>` |
| **Файловые права** | 640 (`root:root`) |
| **Генерация** | Ansible: Jinja2 template |
| **Хосты** | access-прокси |

## Генерация секретов

### MTProxy secret

Генерируется утилитой mtg:
```bash
# AI-GENERATED — NOT REVIEWED: SECTION START
mtg generate-secret --hex example.gov.ru
# Результат: ee24d2982263cabb7499a6a9a77dc3c91f636c6f7564666c6172652e636f6d
# AI-GENERATED — NOT REVIEWED: SECTION END
```

Структура hex-строки: `ee` (fake-TLS prefix) + random bytes + encoded domain name.

### Keepalived password

Задаётся вручную DevOps-инженером. Требования: строка до 8 символов (ограничение VRRP протокола).

## Жизненный цикл

| Стадия | Действие | Актор | Инструмент |
|---|---|---|---|
| **Create** | Генерация секрета | DevOps-инженер | `mtg generate-secret` / ручное задание |
| **Store** | Запись в inventory + рендеринг | Git + Ansible | Jinja2 templates |
| **Use** | Шифрование MTProto / аутентификация VRRP | mtg / Keepalived | Чтение конфигурации |
| **Share** | MTProxy link пользователям | DevOps-инженер | Безопасный канал |
| **Rotate** | Генерация нового + re-deploy + уведомление | DevOps-инженер + Ansible | playbook re-run |
| **Archive** | Git history | VCS | Git |
| **Dispose** | Перезапись при ротации | Ansible | template module |

## Безопасность

| Параметр | Значение |
|---|---|
| **Уровень конфиденциальности** | Высокий |
| **Обоснование** | Компрометация MTProxy secret позволяет подключение к MTProxy; компрометация Keepalived password позволяет перехват VIP |
| **Ansible** | `no_log: true` для задач с секретами |
| **Файловые права** | 640 на целевых файлах |
| **Логирование** | Секреты не логируются в access.log и системные логи |
| **Передача** | MTProxy link передаётся по безопасному каналу |
| **VCS** | inventory.yml в Git — секреты в открытом виде (рекомендация: Ansible Vault для шифрования) |

**Угрозы:**

| Угроза | Вероятность | Влияние | Контрмера |
|---|---|---|---|
| Утечка inventory.yml | Средняя | Высокое | Ограничение доступа к репозиторию; рекомендация — Ansible Vault |
| Утечка через Ansible output | Средняя | Высокое | `no_log: true` |
| Перехват VRRP | Низкая | Высокое | Keepalived auth в закрытой сети |
| Компрометация MTProxy secret | Низкая | Среднее | Ротация + файловые права 640 |

## Связанные требования

- [C2-FR-006](../../C2/C2-FR-006.md) — MTProxy для Telegram (MTProxy secret)
- [C2-NF-001](../../C2/C2-NF-001.md) — Высокая доступность (Keepalived password)
- [C2-NF-002](../../C2/C2-NF-002.md) — Безопасность
- [C3-MT-001](../../C3/C3-MT-001.md) — MTProxy (mtg)
- [C3-KA-001](../../C3/C3-KA-001.md) — Keepalived VRRP
<!-- [/AIGD] -->
