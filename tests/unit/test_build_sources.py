"""Image builds fetch packages only over HTTPS with signature checks, and the
Compose stack publishes its unauthenticated services on loopback only."""

import hashlib
import importlib.util
import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FETCH_DEBS = os.path.join(ROOT, 'docker', 'apt', 'fetch_debs.py')

BYPASSES = (
    '--allow-unauthenticated',
    '--force-yes',
    'trusted=yes',
    'AllowUnauthenticated',
    'AllowInsecureRepositories',
    'AllowDowngradeToInsecureRepositories',
    '--no-check-gpg',
    '--no-check-certificate',
    '--insecure',
    'http://',
)


def tracked_files():
    output = subprocess.check_output(['git', 'ls-files'], cwd=ROOT)
    return output.decode('utf-8').splitlines()


def build_files():
    """Every Dockerfile and every file under docker/ (apt config, lock files,
    fetch scripts)."""
    paths = []
    for path in tracked_files():
        name = os.path.basename(path)
        if name.startswith('Dockerfile') or path.startswith('docker/'):
            paths.append(path)
    return paths


def test_build_file_list_covers_every_dockerfile():
    paths = build_files()
    assert 'Dockerfile' in paths
    assert 'docker/grafana/Dockerfile' in paths
    assert 'docker/apt/fetch_debs.py' in paths


@pytest.mark.parametrize('path', build_files())
def test_build_file_has_no_unauthenticated_or_plain_http_source(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as handle:
        text = handle.read()
    found = [needle for needle in BYPASSES if needle in text]
    assert found == [], '{} contains {}'.format(path, found)


def test_grafana_image_installs_only_verified_local_packages():
    with open(os.path.join(ROOT, 'docker', 'grafana', 'Dockerfile')) as handle:
        text = handle.read()
    final_stage = text.split('\nFROM ')[-1]
    assert final_stage.startswith('debian:stretch-20171210@sha256:')
    # The period image never talks to a package archive itself.
    assert 'apt-get' not in final_stage
    assert 'dpkg -i' in final_stage
    assert 'fetch_debs.py' in text
    assert 'sha256sum -c' in text


@pytest.fixture(scope='module')
def fetch_debs():
    spec = importlib.util.spec_from_file_location('fetch_debs', FETCH_DEBS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_refuses_plain_http(fetch_debs):
    with pytest.raises(SystemExit):
        fetch_debs.fetch('http://snapshot.debian.org/archive/debian/x')


def test_fetch_base_url_is_https_snapshot(fetch_debs):
    assert fetch_debs.BASE.startswith('https://snapshot.debian.org/archive/debian/2017')


RELEASE = b"""Origin: Debian
Codename: stretch
SHA256:
 aaaa 100 main/binary-i386/Packages.gz
 bbbb 200 main/binary-amd64/Packages.gz
SHA512:
 cccc 200 main/binary-amd64/Packages.gz
"""


def test_release_sha256_reads_the_sha256_section_only(fetch_debs):
    assert fetch_debs.release_sha256(RELEASE, 'main/binary-amd64/Packages.gz') == 'bbbb'
    with pytest.raises(SystemExit):
        fetch_debs.release_sha256(RELEASE, 'main/binary-arm64/Packages.gz')


def test_check_sha256_rejects_tampered_data(fetch_debs):
    data = b'package bytes'
    good = hashlib.sha256(data).hexdigest()
    fetch_debs.check_sha256(data, good, 'pkg.deb')
    with pytest.raises(SystemExit):
        fetch_debs.check_sha256(data + b'!', good, 'pkg.deb')


def test_signature_status_requires_goodsig_and_validsig(fetch_debs):
    good = ('[GNUPG:] GOODSIG 0123 Debian Archive\n'
            '[GNUPG:] VALIDSIG ABCD 2017-12-31\n')
    assert fetch_debs.signature_ok(0, good)
    assert not fetch_debs.signature_ok(1, good)
    assert not fetch_debs.signature_ok(0, '[GNUPG:] GOODSIG 0123 Debian Archive\n')
    assert not fetch_debs.signature_ok(0, good + '[GNUPG:] BADSIG 4567 Other\n')
    assert not fetch_debs.signature_ok(0, good + '[GNUPG:] NO_PUBKEY 4567\n')


def test_installed_packages_read_from_dpkg_status(fetch_debs, tmpdir):
    status = tmpdir.join('status')
    status.write('Package: adduser\nStatus: install ok installed\nVersion: 3.115\n\n'
                 'Package: gone\nStatus: deinstall ok config-files\nVersion: 1\n\n'
                 'Package: mawk\nStatus: install ok installed\nVersion: 1.3.3-17+b3\n'
                 'Provides: awk\n')
    installed = fetch_debs.installed_packages(str(status))
    assert installed['adduser'] == '3.115'
    assert 'gone' not in installed
    assert installed['awk'] == '1.3.3-17+b3'


def published_ports(text):
    ports = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != 'ports:':
            continue
        indent = len(line) - len(line.lstrip())
        for item in lines[index + 1:]:
            if not item.strip():
                continue
            if len(item) - len(item.lstrip()) <= indent or not item.strip().startswith('-'):
                break
            ports.append(item.strip()[1:].strip().strip('"\''))
    return ports


def test_compose_publishes_ports_on_loopback_only():
    with open(os.path.join(ROOT, 'docker-compose.yml')) as handle:
        ports = published_ports(handle.read())
    assert len(ports) == 3
    for port in ports:
        assert re.match(r'^127\.0\.0\.1:205\d\d:\d+$', port), port
