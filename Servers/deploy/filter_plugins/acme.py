"""Find HTTP-01 responders for one shared access hostname without DNS recursion."""
import ipaddress


def https_proxy_acme_cluster(names, hostvars, current):
    def enabled(value):
        return str(value).lower() in ('true', 'yes', '1', 'on')

    result = {'nodes': [], 'peers': [], 'error': ''}
    try:
        hostname = str(hostvars[current].get('https_proxy_hostname', '')).lower()
        addresses = set()
        for name in names:
            config = hostvars[name]
            if (not enabled(config.get('https_proxy_enabled', False)) or
                    str(config.get('https_proxy_hostname', '')).lower() != hostname):
                continue
            if not enabled(config.get('https_proxy_acme_enabled', False)):
                raise ValueError('Все access с общим HTTPS-именем должны включать https_proxy_acme_enabled; смешанный режим с внешними сертификатами не поддерживается.')
            try:
                address = ipaddress.ip_address(str(config.get('https_proxy_acme_address', config.get('ansible_host', ''))))
                if getattr(address, 'scope_id', None):
                    raise ValueError('Scoped IPv6 is not a shared ACME endpoint')
            except ValueError:
                raise ValueError('Для ACME нужен IP соседнего access: задайте https_proxy_acme_address, если ansible_host не является IP.') from None
            if address in addresses:
                raise ValueError('Адреса участников ACME должны различаться; один IP не должен обозначать два access.')
            addresses.add(address)
            result['nodes'].append(name)
            if name != current:
                result['peers'].append({'name': name, 'address': str(address),
                                        'endpoint': '[' + str(address) + ']:80' if address.version == 6
                                        else str(address) + ':80'})
        if current not in result['nodes']:
            raise ValueError('Узел ACME должен входить в access_proxies и иметь включённые HTTPS и ACME.')
    except (ValueError, KeyError) as error:
        result['error'] = str(error) if isinstance(error, ValueError) else 'Не найден участник ACME в hostvars.'
    return result


class FilterModule:
    def filters(self):
        return {'https_proxy_acme_cluster': https_proxy_acme_cluster}
