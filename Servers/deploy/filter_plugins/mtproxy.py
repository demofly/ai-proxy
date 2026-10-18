"""Cluster-wide MTProxy credentials; never silently rotate an existing secret."""
import base64
import re


def mtproxy_nodes(names, hostvars):
    return [name for name in names if str(hostvars[name].get('mtproxy_enabled', False)).lower()
            in ('true', 'yes', '1', 'on')]


def mtproxy_domain_hex(domain):
    return domain.encode('ascii').hex()


def mtproxy_cluster_plan(nodes, hostvars, reads):
    """Return a safe error message separately from sensitive resolved material."""
    try:
        domains = {hostvars[name].get('mtproxy_fake_tls_domain', 'max.ru') for name in nodes}
        if len(domains) != 1:
            raise ValueError('Все серверы MTProxy должны использовать один домен fake-TLS.')
        domain = domains.pop()
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', domain):
            raise ValueError('Задайте корректный ASCII-домен mtproxy_fake_tls_domain на всех серверах.')
        configured = {hostvars[name].get('mtproxy_secret', '') for name in nodes}
        if len(configured) != 1:
            raise ValueError('Задайте одинаковый mtproxy_secret на всех включённых upstream; частичная ротация небезопасна.')
        secret = configured.pop()
        if not secret:
            contents = {}
            for read in reads:
                if 'content' in read:
                    node, filename = read['item']['item']
                    contents.setdefault(node, {})[filename] = base64.b64decode(read['content']).decode()
            existing = set()
            for files in contents.values():
                if 'mtg.toml' in files:
                    matches = re.findall(r'^\s*secret\s*=\s*"([^"]+)"', files['mtg.toml'], re.M)
                else:
                    matches = re.findall(r'^MTG_SECRET=(.+)$', files.get('mtg.env', ''), re.M)
                if len(matches) != 1:
                    raise ValueError('В существующей конфигурации MTProxy нет однозначного секрета; проверьте её до деплоймента.')
                existing.add(matches[0].strip())
            if len(existing) > 1:
                raise ValueError('На upstream сохранены разные секреты MTProxy. Задайте общий mtproxy_secret в inventory; автоматическая ротация запрещена.')
            secret = next(iter(existing), '')
        if secret:
            if not re.fullmatch(r'ee[0-9a-fA-F]{32}(?:[0-9a-fA-F]{2})+', secret):
                raise ValueError('Секрет fake-TLS MTProxy должен содержать ee, 16 байт ключа и домен в hex-кодировке.')
            if bytes.fromhex(secret[34:]).decode('ascii').lower() != domain.lower():
                raise ValueError('В секрете MTProxy закодирован другой домен. Явно обновите домен и секрет одновременно.')
        return {'secret':secret, 'domain':domain, 'error':''}
    except ValueError as error:
        # All validation messages above are static and contain no secret values.
        # Unicode conversion failures must not echo a secret through exceptions.
        return {'secret':'', 'domain':'', 'error': str(error) if type(error) is ValueError
                else 'Недопустимая кодировка в конфигурации MTProxy.'}


class FilterModule:
    def filters(self):
        return {'mtproxy_nodes':mtproxy_nodes, 'mtproxy_cluster_plan':mtproxy_cluster_plan,
                'mtproxy_domain_hex':mtproxy_domain_hex}
