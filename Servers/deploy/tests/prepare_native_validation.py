"""Fetch/extract native test tools in a private cache; never install host packages.

Run under WSL Ubuntu 24.04: python3 prepare_native_validation.py
The network/cgroup fixture uses the extracted files, not production nodes.
"""
import json
import shutil
from pathlib import Path
import subprocess
import tarfile
import urllib.request
import yaml

ROOT = Path.home() / '.cache/ai-proxy-validation'
ROOT.mkdir(parents=True, exist_ok=True)


def fetch(url, path):
    if not path.exists():
        urllib.request.urlretrieve(url, path)


def release(repo, tag='latest'):
    url = f'https://api.github.com/repos/{repo}/releases/'
    url += 'latest' if tag == 'latest' else f'tags/{tag}'
    with urllib.request.urlopen(url) as response:
        return json.load(response)


if __name__ == '__main__':
    subprocess.run(['apt-get', 'download', 'squid-openssl', 'nginx',
                    'libnginx-mod-stream', 'unbound', 'squid-common', 'squid-langpack',
                    'libecap3', 'libnetfilter-conntrack3', 'libnfnetlink0',
                    'libnghttp2-14', 'libhiredis1.1.0'], cwd=ROOT, check=True)
    subprocess.run(['apt-get', 'download', 'libevent-2.1-7t64', 'libevent-pthreads-2.1-7t64',
                    'libfstrm0', 'libprotobuf-c1'], cwd=ROOT, check=True)
    for package in ROOT.glob('*.deb'):
        subprocess.run(['dpkg-deb', '-x', str(package), str(ROOT/'root')], check=True)
    for repo, tag, selected, directory in [
        ('9seconds/mtg', 'v2.2.8', 'linux-amd64.tar.gz', 'mtg'),
        ('crowdsecurity/crowdsec', 'v1.8.1', 'crowdsec-release.tgz', 'crowdsec'),
        ('crowdsecurity/cs-firewall-bouncer', 'v0.0.36', 'linux-amd64.tgz', 'bouncer'),
    ]:
        data = release(repo, tag)
        asset = next(a for a in data['assets'] if a['name'].endswith(selected))
        path = ROOT / asset['name']
        fetch(asset['browser_download_url'], path)
        destination = ROOT / directory
        destination.mkdir(exist_ok=True)
        with tarfile.open(path) as archive:
            # Do not overwrite binaries being used by a simultaneous native run.
            def missing_only(member, target):
                if (Path(target)/member.name).exists():
                    return None
                return tarfile.data_filter(member, target)
            archive.extractall(destination, filter=missing_only)
        print(repo, data['tag_name'], destination, flush=True)

    # An isolated CrowdSec configuration with the deployment's real collections.
    distribution = next((ROOT/'crowdsec').glob('crowdsec-v*'))
    config_dir = ROOT/'crowdsec-test'
    if not config_dir.exists():
        shutil.copytree(distribution/'config', config_dir)
    data_dir = config_dir/'data'
    data_dir.mkdir(exist_ok=True)
    (config_dir/'hub').mkdir(exist_ok=True)
    source = (distribution/'config/config.yaml').read_text()
    source = source.replace('/etc/crowdsec', str(config_dir))
    source = source.replace('/var/lib/crowdsec/data', str(data_dir))
    config = yaml.safe_load(source)
    config['common'].update(daemonize=False, log_media='stdout')
    config['api']['server'].pop('online_client', None)  # no test CAPI registration
    config['api']['server']['listen_uri'] = '127.0.0.1:18080'
    (config_dir/'config.yaml').write_text(yaml.safe_dump(config))
    (config_dir/'acquis.d').mkdir(exist_ok=True)
    (config_dir/'auth.log').touch()
    (config_dir/'acquis.yaml').write_text(yaml.safe_dump({
        'filenames': [str(config_dir/'auth.log')], 'labels': {'type': 'syslog'}}))
    cli = distribution/'cmd/crowdsec-cli/cscli'
    def cscli(*args):
        result = subprocess.run([str(cli), '-c', str(config_dir/'config.yaml'), *args],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(result.stdout[-4000:])
        return result.stdout
    cscli('hub', 'update')
    for collection in ['crowdsecurity/linux', 'crowdsecurity/nginx',
                       'crowdsecurity/http-cve', 'crowdsecurity/whitelist-good-actors']:
        cscli('collections', 'install', collection)
    cscli('machines', 'add', 'native-test', '--auto', '--force')
    bouncer_config = config_dir/'bouncer.yaml'
    if not bouncer_config.exists():
        key = cscli('bouncers', 'add', 'native-test', '-o', 'raw').strip()
        bouncer_config.write_text(yaml.safe_dump({
            'mode': 'nftables', 'api_url': 'http://127.0.0.1:18080/', 'api_key': key,
            'update_frequency': '10s', 'log_mode': 'stdout', 'log_level': 'info',
            'deny_action': 'DROP', 'disable_ipv6': True,
            'nftables': {'ipv4': {'enabled': True, 'table': 'aiproxytest', 'chain': 'aiproxytest',
                                  'set-only': False, 'priority': -10}}}))
        bouncer_config.chmod(0o600)
    print('CrowdSec collections and isolated credentials prepared', flush=True)
