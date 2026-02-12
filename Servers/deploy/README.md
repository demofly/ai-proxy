# Ansible Deployment

Автоматизированное развертывание AI Proxy на базе Squid.

## Структура

```
deploy/
├── inventory.yml              # Инвентарь хостов
├── playbook.yml               # Основной playbook
├── passwd                     # Пример файла пользователей
├── templates/
│   ├── squid-access.conf.j2   # Шаблон Squid для access
│   ├── squid-upstream.conf.j2 # Шаблон Squid для upstream
│   ├── keepalived.conf.j2     # Шаблон Keepalived для access
│   └── nftables-upstream.conf.j2  # Шаблон nftables для upstream (Debian)
└── README.md
```

## Требования

### Управляющий хост
- Ansible >= 2.9
- Коллекции: `ansible.posix`, `community.general`

### Целевые серверы

| Дистрибутив | Примечание |
|-------------|------------|
| **Ubuntu 24.04 LTS** | Рекомендуется (Squid 6.13 из коробки) |
| Ubuntu 22.04 LTS | Требуется [Diladele PPA](https://docs.diladele.com/howtos/build_squid_on_ubuntu_22/repository.html) |
| Debian 13 (Trixie) | Squid 6.x в репозитории |

**Системные требования:**
- Python >= 3.8
- systemd
- SSH доступ с правами root

### Пререквизиты: версии пакетов

| Пакет | Минимум | Максимум | Назначение |
|-------|---------|----------|------------|
| Squid | 6.0 | 6.x | Прокси-сервер |
| Keepalived | 2.0 | 2.x | VRRP для access (опционально) |

**Фаерволы (upstream прокси):**

| ОС | Фаервол | Версия |
|----|---------|--------|
| Ubuntu | UFW | >= 0.36 |
| Debian | nftables | >= 1.0 |

Playbook автоматически определяет ОС и применяет соответствующий фаервол.

## Использование

1. Отредактируйте `inventory.yml`:
   - Укажите реальные IP/hostname серверов в группах `access_proxies` и `upstreams`
   - Настройте переменную `ai_api_domains`

2. Запустите playbook:
   ```bash
   ansible-playbook -i inventory.yml playbook.yml
   ```

3. Для отдельных групп:
   ```bash
   # Только access прокси
   ansible-playbook -i inventory.yml playbook.yml --limit access_proxies

   # Только upstream прокси
   ansible-playbook -i inventory.yml playbook.yml --limit upstreams
   ```

## Управление пользователями (access)

Отредактируйте файл `passwd` перед развёртыванием:

```bash
# Добавить пользователя
htpasswd -Bbn username password >> passwd

# Или через openssl
echo "username:$(openssl passwd -apr1 password)" >> passwd
```

## Переменные

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `squid_port` | Порт Squid | 443 |
| `enable_auth` | Включить аутентификацию | true (access) |
| `enable_logging` | Включить журналирование | true (access) |
| `enable_caching` | Включить кеширование | true (access) |
| `ai_api_domains` | Разрешенные AI API домены | см. inventory |
| `upstreams` | Upstream прокси для failover | см. inventory |
| `dns_servers` | DNS серверы | 9.9.9.9, 8.8.8.8, 1.1.1.1 |
| `enable_keepalived` | Включить Keepalived (access) | true |
| `keepalived_vip` | Виртуальный IP | 5.228.141.95 |
| `keepalived_interface` | Сетевой интерфейс | auto (default gw) |
| `keepalived_state` | MASTER или BACKUP | per-host |
| `keepalived_priority` | Приоритет (100/90) | per-host |

## Отказоустойчивость

### Виртуальный IP для access (Keepalived)

Access прокси используют VRRP для обеспечения единого виртуального IP:

```yaml
# Настройки в inventory.yml
enable_keepalived: true
keepalived_vip: 5.228.141.95        # Виртуальный IP для клиентов
# keepalived_interface: eth0        # Автоопределение через ansible_default_ipv4.interface
keepalived_vrid: 51
keepalived_auth_pass: AiPr0xy2024

# Для каждого хоста
access-01:
  keepalived_state: MASTER
  keepalived_priority: 100
access-02:
  keepalived_state: BACKUP
  keepalived_priority: 90
```

### Upstream прокси (Squid cache_peer)

Access прокси автоматически переключается между upstream серверами:

```yaml
upstreams:
  - host: 185.199.108.10
    port: 443
    name: upstream-01
  - host: 185.199.109.10
    port: 443
    name: upstream-02
```

Параметры failover:
- `userhash` — балансировка по хэшу пользователя (sticky sessions), fallback на `sourcehash`
- `connect-fail-limit=2` — после 2 неудач сервер помечается недоступным
- `connect-timeout=5` — таймаут подключения 5 секунд
- `dead_peer_timeout=15` — проверка недоступных серверов каждые 15 секунд
