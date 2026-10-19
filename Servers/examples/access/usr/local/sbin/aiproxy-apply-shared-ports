#!/usr/bin/env python3
"""Apply only the Matrix child chain; never flush a host ruleset."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path('/etc/shared-host')


def validate_contract(data):
    if not isinstance(data, dict) or set(data) - {'tcp', 'udp', 'udp_ranges'}:
        raise ValueError('Invalid shared port contract')
    result = {'tcp': [], 'udp': [], 'udp_ranges': []}
    for proto in ('tcp', 'udp'):
        for port in data.get(proto, []):
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError('Ports must be integers in 1..65535')
            result[proto].append(port)
        result[proto] = sorted(set(result[proto]))
    for span in data.get('udp_ranges', []):
        if not isinstance(span, dict) or set(span) != {'start', 'end'}:
            raise ValueError('Invalid UDP range')
        if any(type(span[n]) is not int for n in ('start', 'end')) or not 1 <= span['start'] <= span['end'] <= 65535:
            raise ValueError('Invalid UDP range boundaries')
        result['udp_ranges'].append(span)
    return result


def nft_rules(data):
    rules = []
    for proto in ('tcp', 'udp'):
        if data[proto]:
            rules.append(f"{proto} dport {{ {', '.join(map(str, data[proto]))} }} accept")
    rules += [f"udp dport {r['start']}-{r['end']} accept" for r in data['udp_ranges']]
    return rules + ['return']


def iptables_rules(data):
    rules = ['*filter', ':MATRIX-SERVICES - [0:0]']
    for proto in ('tcp', 'udp'):
        rules += [f'-A MATRIX-SERVICES -p {proto} --dport {port} -j ACCEPT' for port in data[proto]]
    rules += [f"-A MATRIX-SERVICES -p udp --dport {r['start']}:{r['end']} -j ACCEPT" for r in data['udp_ranges']]
    return '\n'.join(rules + ['-A MATRIX-SERVICES -j RETURN', 'COMMIT', ''])


def run(argv, text=None, required=True):
    p = subprocess.run(argv, input=text, text=True, capture_output=True, timeout=30)
    if required and p.returncode:
        raise RuntimeError(f"{argv[0]} failed: {p.stderr.strip()}")
    return p


def atomic_write(path, content):
    if path.exists() and path.read_text() == content:
        return False
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        name = tmp.name
    os.chmod(name, 0o644)
    os.replace(name, path)
    return True


def apply(data, backend):
    if backend == 'nftables':
        # This is the owner's actual INPUT chain: accept in an unrelated base
        # chain would still be rejected by the owner's policy drop.
        owner = run(['nft', '-j', 'list', 'chain', 'inet', 'filter', 'input'])
        child = run(['nft', 'list', 'chain', 'inet', 'filter', 'matrix_services'], required=False)
        before = child.stdout
        commands = [] if child.returncode == 0 else ['add chain inet filter matrix_services']
        commands += ['flush chain inet filter matrix_services']
        commands += ['add rule inet filter matrix_services ' + r for r in nft_rules(data)]
        entries = json.loads(owner.stdout)['nftables']
        has_jump = any(expr.get('jump', {}).get('target') == 'matrix_services'
                       for item in entries for expr in item.get('rule', {}).get('expr', []))
        if not has_jump:
            commands += ['insert rule inet filter input jump matrix_services comment "Matrix shared ports"']
        batch = '\n'.join(commands) + '\n'
        run(['nft', '--check', '-f', '-'], batch)
        run(['nft', '-f', '-'], batch)
        after = run(['nft', 'list', 'chain', 'inet', 'filter', 'matrix_services']).stdout
        persisted = atomic_write(ROOT / 'matrix-ports.nft', '\n'.join(nft_rules(data)) + '\n')
        return persisted or before != after or not has_jump
    if backend == 'iptables':
        before = run(['iptables', '-S', 'MATRIX-SERVICES'], required=False).stdout
        batch = iptables_rules(data)
        run(['iptables-restore', '--test', '--noflush'], batch)
        run(['iptables-restore', '--noflush'], batch)
        has_jump = run(['iptables', '-C', 'INPUT', '-j', 'MATRIX-SERVICES'], required=False).returncode == 0
        if not has_jump:
            run(['iptables', '-I', 'INPUT', '1', '-j', 'MATRIX-SERVICES'])
        after = run(['iptables', '-S', 'MATRIX-SERVICES']).stdout
        return before != after or not has_jump
    if backend == 'ufw':
        return False  # Matrix's UFW tasks own these rules and their persistence.
    raise ValueError(f'Unsupported active firewall backend: {backend}')


def main():
    contract = ROOT / 'matrix-ports.json'
    if not contract.exists():
        return
    data = validate_contract(json.loads(contract.read_text()))
    backend = (ROOT / 'aiproxy-firewall-backend').read_text().strip()
    if apply(data, backend):
        print('CHANGED')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        sys.exit(str(exc))
