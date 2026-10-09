#!/usr/bin/env python3
"""fetch_debs.py LOCK STATUS KEYRING OUTDIR

Downloads the packages pinned in LOCK, plus the dependencies the target
image does not already have, from the stretch archive snapshot into OUTDIR.
Each step is checked before the next one trusts its input:

  1. dists/stretch/Release.gpg is verified over Release with gpgv against
     KEYRING (the Debian archive keys, current and removed). The signing
     keys have expired since, so gpgv runs with its clock set to the
     snapshot date; an expired key is still checked, never skipped. The
     Release Codename must be stretch.
  2. main/binary-amd64/Packages.gz must match its SHA256 in Release.
  3. Each .deb must match its SHA256 in Packages.

STATUS is the target image's /var/lib/dpkg/status: packages installed
there satisfy dependencies and are not downloaded again. Nothing is
installed here. OUTDIR/ORDER lists the files dependencies-first. Every
download uses HTTPS, and any failed check exits non-zero.
"""

import gzip
import hashlib
import os
import re
import subprocess
import sys
import time
import urllib.request

BASE = 'https://snapshot.debian.org/archive/debian/20171231T000000Z'
DIST = 'stretch'
INDEX = 'main/binary-amd64/Packages.gz'
SNAPSHOT_CLOCK = '2017-12-31 12:00:00'


def die(message):
    sys.exit('fetch_debs: ' + message)


def fetch(url, retries=3):
    if not url.startswith('https://'):
        die('refusing non-HTTPS URL ' + url)
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
        except Exception as error:
            last = error
            time.sleep(5 * (attempt + 1))
    die('cannot download {}: {}'.format(url, last))


def check_sha256(data, expected, name):
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        die('{} has SHA256 {}, expected {}'.format(name, actual, expected))


def signature_ok(returncode, status):
    """True if gpgv exited 0 with a good, valid signature and no bad one."""
    if returncode != 0:
        return False
    if not re.search(r'^\[GNUPG:\] GOODSIG ', status, re.M):
        return False
    if not re.search(r'^\[GNUPG:\] VALIDSIG ', status, re.M):
        return False
    bad = r'^\[GNUPG:\] (BADSIG|ERRSIG|REVKEYSIG|NO_PUBKEY|EXPSIG) '
    return re.search(bad, status, re.M) is None


def verify_release(release, signature, keyring, workdir):
    rel_path = os.path.join(workdir, 'Release')
    sig_path = os.path.join(workdir, 'Release.gpg')
    with open(rel_path, 'wb') as handle:
        handle.write(release)
    with open(sig_path, 'wb') as handle:
        handle.write(signature)
    result = subprocess.run(
        ['faketime', SNAPSHOT_CLOCK, 'gpgv', '--status-fd', '1',
         '--keyring', keyring, sig_path, rel_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if not signature_ok(result.returncode, result.stdout):
        die('Release signature check failed:\n' + result.stdout + result.stderr)
    if not re.search(r'^Codename: {}$'.format(DIST), release.decode('utf-8'), re.M):
        die('Release is not for ' + DIST)
    print('fetch_debs: Release signature verified')


def release_sha256(release, name):
    in_sha256 = False
    for line in release.decode('utf-8').splitlines():
        if line.startswith('SHA256:'):
            in_sha256 = True
        elif line and not line.startswith(' '):
            in_sha256 = False
        elif in_sha256:
            fields = line.split()
            if len(fields) == 3 and fields[2] == name:
                return fields[0]
    die('no SHA256 for {} in Release'.format(name))


def parse_stanzas(text):
    for block in re.split(r'\n\n+', text.strip()):
        fields = {}
        key = None
        for line in block.split('\n'):
            if line[:1] in (' ', '\t'):
                if key:
                    fields[key] += '\n' + line
            else:
                key, _, value = line.partition(':')
                fields[key] = value.strip()
        if 'Package' in fields:
            yield fields


DEP = re.compile(r'^\s*([^\s(:]+)(?::\w+)?\s*(?:\(\s*(<<|<=|=|>=|>>|<|>)\s*([^)\s]+)\s*\))?')


def parse_depends(field):
    groups = []
    for group in field.split(','):
        alternatives = []
        for alternative in group.split('|'):
            match = DEP.match(alternative)
            if match:
                op = {'<': '<=', '>': '>='}.get(match.group(2), match.group(2))
                alternatives.append((match.group(1), op, match.group(3)))
        if alternatives:
            groups.append(alternatives)
    return groups


def installed_packages(status_path):
    """Map package (and provided virtual package) names to installed versions."""
    with open(status_path, encoding='utf-8') as handle:
        text = handle.read()
    installed = {}
    for fields in parse_stanzas(text):
        if fields.get('Status', '').split()[-1:] != ['installed']:
            continue
        installed[fields['Package']] = fields['Version']
        for group in parse_depends(fields.get('Provides', '')):
            installed.setdefault(group[0][0], fields['Version'])
    return installed


def version_ok(candidate, op, wanted):
    if not op:
        return True
    return subprocess.call(['dpkg', '--compare-versions', candidate, op, wanted]) == 0


def newest(candidates):
    best = candidates[0]
    for other in candidates[1:]:
        if version_ok(other['Version'], 'gt', best['Version']):
            best = other
    return best


def read_lock(path):
    wanted = []
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith('#'):
                name, _, version = line.partition('=')
                wanted.append((name, version))
    if not wanted:
        die('empty lock file')
    return wanted


def resolve(wanted, available, providers, installed):
    selected = {}

    def find(name, op, version):
        if name in installed and version_ok(installed[name], op, version):
            return 'installed'
        if name in selected and version_ok(selected[name]['Version'], op, version):
            return 'selected'
        candidates = [f for f in available.get(name, [])
                      if version_ok(f['Version'], op, version)]
        if candidates:
            return newest(candidates)
        if not op and providers.get(name):
            for fields in providers[name]:
                if fields['Package'] in installed or fields['Package'] in selected:
                    return 'installed'
            return providers[name][0]
        return None

    queue = []
    for name, version in wanted:
        if installed.get(name) == version:
            continue
        match = [f for f in available.get(name, []) if f['Version'] == version]
        if not match:
            die('{}={} is not in the snapshot'.format(name, version))
        selected[name] = match[0]
        queue.append(match[0])

    while queue:
        fields = queue.pop(0)
        depends = ', '.join(x for x in (fields.get('Pre-Depends'), fields.get('Depends')) if x)
        for group in parse_depends(depends):
            choice = None
            for name, op, version in group:
                choice = find(name, op, version)
                if choice is not None:
                    break
            if choice is None:
                die('{}: cannot satisfy {}'.format(fields['Package'], group))
            if isinstance(choice, dict):
                selected[choice['Package']] = choice
                queue.append(choice)
    return selected


def install_order(selected):
    order = []
    visited = set()

    def visit(name):
        if name in visited:
            return
        visited.add(name)
        fields = selected[name]
        depends = ', '.join(x for x in (fields.get('Pre-Depends'), fields.get('Depends')) if x)
        for group in parse_depends(depends):
            for dep, _, _ in group:
                if dep in selected:
                    visit(dep)
                    break
        order.append(name)

    for name in sorted(selected):
        visit(name)
    return order


def deb_name(fields):
    return os.path.basename(fields['Filename']).replace('%3a', '_')


def main(argv):
    if len(argv) != 5:
        sys.exit('usage: fetch_debs.py LOCK STATUS KEYRING OUTDIR')
    lock, status, keyring, out = argv[1:]
    os.makedirs(out, exist_ok=True)

    release = fetch('{}/dists/{}/Release'.format(BASE, DIST))
    signature = fetch('{}/dists/{}/Release.gpg'.format(BASE, DIST))
    verify_release(release, signature, keyring, out)
    os.remove(os.path.join(out, 'Release'))
    os.remove(os.path.join(out, 'Release.gpg'))

    packages_gz = fetch('{}/dists/{}/{}'.format(BASE, DIST, INDEX))
    check_sha256(packages_gz, release_sha256(release, INDEX), INDEX)
    print('fetch_debs: {} checked against Release'.format(INDEX))

    available = {}
    providers = {}
    for fields in parse_stanzas(gzip.decompress(packages_gz).decode('utf-8', 'replace')):
        available.setdefault(fields['Package'], []).append(fields)
        for group in parse_depends(fields.get('Provides', '')):
            providers.setdefault(group[0][0], []).append(fields)

    selected = resolve(read_lock(lock), available, providers, installed_packages(status))
    for name in sorted(selected):
        fields = selected[name]
        data = fetch('{}/{}'.format(BASE, fields['Filename']))
        check_sha256(data, fields['SHA256'], '{} {}'.format(name, fields['Version']))
        with open(os.path.join(out, deb_name(fields)), 'wb') as handle:
            handle.write(data)
        print('fetch_debs: {}={} verified'.format(name, fields['Version']))
    with open(os.path.join(out, 'ORDER'), 'w') as handle:
        for name in install_order(selected):
            handle.write(deb_name(selected[name]) + '\n')
    print('fetch_debs: {} packages verified'.format(len(selected)))


if __name__ == '__main__':
    main(sys.argv)
