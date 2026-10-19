"""Literal DoH endpoints: never bootstrap the encrypted DNS path using DNS."""
import ipaddress
import base64
import re


DEFAULT_DOH_PATH = '/q'


def validate_doh_path(path):
    if (not isinstance(path, str) or len(path) > 255
            or not re.fullmatch(r"/(?:[A-Za-z0-9._~!$&'()*+,;=:@/-]|%[0-9A-Fa-f]{2})*", path)
            or any(segment in ('.', '..') for segment in path.split('/'))):
        raise ValueError('dns_doh_path должен быть абсолютным ASCII URI-путём до 255 байт без query, fragment и сегментов «.» или «..».')
    return path


def doh_endpoint(address, port=443, hostname='dns.transit.internal', path=DEFAULT_DOH_PATH):
    path = validate_doh_path(path)
    try:
        address = ipaddress.ip_address(str(address))
    except ValueError:
        raise ValueError('Для DoH нужен буквальный IP upstream без открытого DNS bootstrap.') from None
    if getattr(address, 'scope_id', None):
        raise ValueError('DoH требует IPv4 или IPv6 без scope ID.')
    port = int(port)
    if not 1 <= port <= 65535 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', hostname):
        raise ValueError('Некорректный порт или SNI DoH.')
    ip = f'[{address}]' if address.version == 6 else str(address)
    provider = hostname if port == 443 else f'{hostname}:{port}'

    def field(value):
        value = value.encode('ascii')
        if len(value) > 255:
            raise ValueError('Поле DNS stamp длиннее 255 байт.')
        return bytes([len(value)]) + value

    # DNS stamp DoH: protocol, properties, literal IP, no cert hashes, SNI, path.
    # StaticResolver in dnsproxy uses the stamp's IP, never bootstrap DNS.
    stamp = b'\x02' + bytes(8) + field(ip) + b'\0' + field(provider) + field(path)
    return {'url': f'https://{provider}{path}', 'resolve': f'{hostname}:{port}:{ip}',
            'stamp': 'sdns://' + base64.urlsafe_b64encode(stamp).rstrip(b'=').decode()}


def dns_doh_upstreams(names, hostvars):
    result = []
    for name in names:
        config = hostvars[name]
        router = str(config.get('nginx_on_443', config.get('behind_nginx', True))).lower() in ('true', 'yes', '1', 'on')
        port = config.get('proxy_port', 443) if router else config.get('dns_doh_backend_port', 8443)
        result.append(doh_endpoint(config['ansible_host'], port, config.get('dns_doh_sni', 'dns.transit.internal'),
                                   config.get('dns_doh_path', DEFAULT_DOH_PATH)))
    if not result:
        raise ValueError('Нужен хотя бы один DoH upstream.')
    return result


class FilterModule:
    def filters(self):
        return {'dns_doh_upstreams': dns_doh_upstreams, 'validate_doh_path': validate_doh_path}
