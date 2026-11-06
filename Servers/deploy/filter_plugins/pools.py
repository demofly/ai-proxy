# [AITS] 2026-11-06T15:09:32Z
# AI-GENERATED — NOT REVIEWED: SECTION START
"""Пулы пользователей: группа пользователей -> пул -> набор upstream (уровень access)."""
import re

GROUP_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')
# Имя пользователя попадает токеном в ACL Squid: пробелы и кавычки недопустимы.
USER_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._@+-]{0,127}')
POOL_NAME = re.compile(r'[a-z][a-z0-9_-]{0,31}')
POOL_KEYS = {'name', 'groups', 'upstreams'}
ALL = 'all'


def _error(message):
    # Импорт отложен: модуль проверяется и вне Ansible (юнит-тесты, примеры).
    from ansible.errors import AnsibleFilterError
    return AnsibleFilterError(message)


def _is_list(value):
    return isinstance(value, (list, tuple))


def _bad_name(what, value, pattern):
    """Ошибка имени: отдельно называет нестроковый тип (YAML мог прочитать имя как число или булево)."""
    if not isinstance(value, str):
        return _error(f'Недопустимое имя {what} {value!r}: получен тип {type(value).__name__}, нужна строка. '
                      f'YAML читает значения вроде 1001, 007, no как число либо булево — заключите имя в кавычки.')
    return _error(f'Недопустимое имя {what} {value!r}: разрешено {pattern.pattern}.')


def _check_user(group, user):
    """Проверяет одно имя пользователя группы."""
    # REQUIRED в proxy_auth — ключевое слово «любой пользователь», а не имя.
    if not isinstance(user, str) or not USER_NAME.fullmatch(user) or user == 'REQUIRED':
        raise _bad_name(f'пользователя в группе {group!r}', user, USER_NAME)


def _check_groups(user_groups):
    """Проверяет proxy_user_groups и возвращает его как {группа: [имена]}."""
    if not isinstance(user_groups, dict):
        raise _error('proxy_user_groups должен быть отображением «имя группы -> список пользователей».')
    for group, users in user_groups.items():
        if not isinstance(group, str) or not GROUP_NAME.fullmatch(group):
            raise _bad_name('группы в proxy_user_groups', group, GROUP_NAME)
        if group == ALL:
            raise _error("Имя группы «all» зарезервировано (означает всех пользователей файла паролей) "
                         'и не может быть ключом proxy_user_groups.')
        if not _is_list(users):
            raise _error(f'Группа {group!r} в proxy_user_groups должна быть списком имён пользователей.')
        for user in users:
            _check_user(group, user)
        if len(set(users)) != len(users):
            raise _error(f'В группе {group!r} имена пользователей повторяются.')
    return user_groups


def aiproxy_group_users(user_groups):
    """Отсортированное множество имён всех пользователей из всех групп."""
    groups = _check_groups(user_groups)
    return sorted({user for users in groups.values() for user in users})


def aiproxy_passwd_users(passwd_text):
    """Имена из htpasswd-текста: пустые строки и комментарии пропускаются."""
    names = []
    for line in str(passwd_text).splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        names.append(line.split(':', 1)[0])
    return names


def _pool_upstreams(pool, name, upstream_names):
    """Приводит поле upstreams пула к списку имён в порядке группы inventory."""
    value = pool['upstreams']
    if value == ALL:
        return list(upstream_names)
    if not _is_list(value):
        raise _error(f"Пул {name!r}: upstreams должен быть строкой 'all' либо списком имён из группы upstreams.")
    unknown = [item for item in value if not isinstance(item, str) or item not in upstream_names]
    if unknown:
        # Нестрочные элементы (число, булево) — чаще всего имя без кавычек в YAML.
        raise _error(f'Пул {name!r}: неизвестные upstream {unknown}; допустимы имена из группы upstreams: '
                     f'{list(upstream_names)}.')
    if len(set(value)) != len(value):
        raise _error(f'Пул {name!r}: в upstreams есть повторы.')
    return [item for item in upstream_names if item in value]


def _pool_users(pool, name, user_groups):
    """Возвращает (all_users, отсортированные имена) по списку групп пула."""
    groups = pool['groups']
    if not _is_list(groups):
        raise _error(f'Пул {name!r}: groups должен быть списком имён групп (допустим «all»).')
    for group in groups:
        if not isinstance(group, str):
            raise _error(f'Пул {name!r}: имя группы {group!r} имеет тип {type(group).__name__}, нужна строка '
                         f'(YAML читает 1001, no как число либо булево — заключите имя в кавычки).')
        if group != ALL and group not in user_groups:
            raise _error(f'Пул {name!r}: неизвестная группа {group!r}; допустимы ключи proxy_user_groups '
                         f"{sorted(user_groups)} и «all».")
    if len(set(groups)) != len(groups):
        raise _error(f'Пул {name!r}: в groups есть повторы.')
    users = {user for group in groups if group != ALL for user in user_groups[group]}
    return ALL in groups, sorted(users)


def aiproxy_pools(pools, user_groups, upstream_names):
    """Проверяет модель пулов и возвращает разрешённые пулы в исходном порядке."""
    user_groups = _check_groups(user_groups)
    upstream_names = list(upstream_names)
    if not _is_list(pools):
        raise _error('proxy_pools должен быть списком отображений {name, groups, upstreams}.')
    resolved, seen = [], set()
    for pool in pools:
        if not isinstance(pool, dict):
            raise _error(f'Элемент proxy_pools {pool!r} должен быть отображением {{name, groups, upstreams}}.')
        if set(pool) != POOL_KEYS:
            raise _error(f'Пул {pool.get("name", pool)!r}: ключи должны быть ровно {sorted(POOL_KEYS)}; '
                         f'лишние {sorted(set(pool) - POOL_KEYS)}, недостающие {sorted(POOL_KEYS - set(pool))}.')
        name = pool['name']
        if not isinstance(name, str) or not POOL_NAME.fullmatch(name):
            raise _bad_name('пула', name, POOL_NAME)
        if name in seen:
            raise _error(f'Имя пула {name!r} повторяется; имена пулов уникальны.')
        seen.add(name)
        all_users, users = _pool_users(pool, name, user_groups)
        resolved.append({'name': name, 'all_users': all_users, 'users': users,
                         'upstreams': _pool_upstreams(pool, name, upstream_names)})
    return resolved


class FilterModule:
    def filters(self):
        return {'aiproxy_pools': aiproxy_pools, 'aiproxy_passwd_users': aiproxy_passwd_users,
                'aiproxy_group_users': aiproxy_group_users}
# AI-GENERATED — NOT REVIEWED: SECTION END
