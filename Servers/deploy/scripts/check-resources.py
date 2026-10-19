#!/usr/bin/env python3
"""Read configured and live caps for all project services in one local probe."""
import json
from pathlib import Path
import subprocess
import sys


def verify(units, slice_name='aiproxy.slice', cgroup_root=Path('/sys/fs/cgroup')):
    command = ['systemctl', 'show', *[unit['name'] for unit in units], slice_name,
                             '--property=Id', '--property=ControlGroup', '--property=MemoryMax',
                             '--property=Slice', '--property=NeedDaemonReload', '--property=ActiveState']

    def snapshot():
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        observed = {}
        for block in result.stdout.strip().split('\n\n'):
            props = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            if props.get('Id'):
                observed[props['Id']] = props
        return observed

    observed = snapshot()
    # Recover an interrupted deployment that wrote units but never reloaded
    # systemd: changed=false alone is not proof the manager has read the files.
    reloaded = any(props.get('NeedDaemonReload') == 'yes' for props in observed.values())
    if reloaded:
        subprocess.run(['systemctl', 'daemon-reload'], check=True, capture_output=True, text=True)
        observed = snapshot()
    for unit in units:
        props = observed.get(unit['name'], {})
        cap = int(unit['memory_mb']) * 1048576
        if props.get('MemoryMax') != str(cap) or props.get('Slice') != slice_name:
            raise ValueError('Настроенные пределы или slice не совпадают с планом: ' + unit['name'])
        group = props.get('ControlGroup', '')
        if group:
            try:
                live = (cgroup_root / group.lstrip('/') / 'memory.max').read_text().strip()
            except FileNotFoundError:
                # A timer's oneshot may finish and remove its cgroup after show.
                # Only a confirmed inactive unit can skip the live check; its
                # configured cap and slice still have to match the plan.
                fresh = snapshot().get(unit['name'], {})
                if (fresh.get('ActiveState') in ('inactive', 'failed') and
                        fresh.get('MemoryMax') == str(cap) and fresh.get('Slice') == slice_name):
                    continue
                raise
            if live != str(cap):
                raise ValueError('Действующий предел cgroup не совпадает с планом: ' + unit['name'])
    return {'verified': len(units), 'reloaded': reloaded}


if __name__ == '__main__':
    print(json.dumps(verify(json.loads(sys.argv[1]), sys.argv[2])))
