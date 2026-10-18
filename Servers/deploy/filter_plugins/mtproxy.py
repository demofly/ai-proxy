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
            raise ValueError('MTProxy backends must use one fake-TLS domain.')
        domain = domains.pop()
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', domain):
            raise ValueError('Set a valid ASCII mtproxy_fake_tls_domain for all backends.')
        configured = {hostvars[name].get('mtproxy_secret', '') for name in nodes}
        if len(configured) != 1:
            raise ValueError('Set the same mtproxy_secret on every enabled upstream; partial rotation is unsafe.')
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
                    raise ValueError('Existing MTProxy configuration has no unique secret; inspect it before deployment.')
                existing.add(matches[0].strip())
            if len(existing) > 1:
                raise ValueError('Upstreams have different existing MTProxy secrets. Select one shared mtproxy_secret in inventory; automatic rotation is refused.')
            secret = next(iter(existing), '')
        if secret:
            if not re.fullmatch(r'ee[0-9a-fA-F]{32}(?:[0-9a-fA-F]{2})+', secret):
                raise ValueError('A fake-TLS MTProxy secret must have ee + 16 key bytes + encoded domain.')
            if bytes.fromhex(secret[34:]).decode('ascii').lower() != domain.lower():
                raise ValueError('MTProxy secret encodes a different domain. Update the domain and secret together explicitly.')
        return {'secret':secret, 'domain':domain, 'error':''}
    except ValueError as error:
        # All validation messages above are static and contain no secret values.
        # Unicode conversion failures must not echo a secret through exceptions.
        return {'secret':'', 'domain':'', 'error': str(error) if type(error) is ValueError
                else 'Invalid encoding in MTProxy configuration.'}


class FilterModule:
    def filters(self):
        return {'mtproxy_nodes':mtproxy_nodes, 'mtproxy_cluster_plan':mtproxy_cluster_plan,
                'mtproxy_domain_hex':mtproxy_domain_hex}
