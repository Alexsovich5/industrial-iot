"""Check the rendered Compose config for host ports open beyond loopback.

Reads the JSON written by ``docker compose config --format json`` (a file
path, or ``-`` for stdin) and fails if any service publishes a port on an
address other than 127.0.0.1, without a fixed host port, outside the
project's host-port range, or uses the host network.
"""

import argparse
import json
import sys

LOOPBACK = '127.0.0.1'
PORT_RANGE = (20500, 20599)


def _published_ok(published):
    text = str(published if published is not None else '')
    if not text.isdigit():
        return False
    return PORT_RANGE[0] <= int(text) <= PORT_RANGE[1]


def port_problems(config):
    """Return one message per unsafe published port or host-network service."""
    problems = []
    for name in sorted(config.get('services', {})):
        service = config['services'][name] or {}
        if service.get('network_mode') == 'host':
            problems.append('{}: network_mode host bypasses port publishing'.format(name))
        for entry in service.get('ports') or []:
            host_ip = entry.get('host_ip')
            published = entry.get('published')
            label = '{}: {}:{}->{}'.format(name, host_ip or '*', published or '?',
                                           entry.get('target'))
            if host_ip != LOOPBACK:
                problems.append('{} is not bound to {}'.format(label, LOOPBACK))
            elif not _published_ok(published):
                problems.append('{} is not a fixed host port in {}-{}'.format(
                    label, PORT_RANGE[0], PORT_RANGE[1]))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('config', help="rendered compose JSON, or '-' for stdin")
    args = parser.parse_args(argv)
    if args.config == '-':
        config = json.load(sys.stdin)
    else:
        with open(args.config) as handle:
            config = json.load(handle)

    if not config.get('services'):
        sys.stderr.write('check_ports: no services in the rendered config\n')
        return 1
    problems = port_problems(config)
    for problem in problems:
        sys.stderr.write('check_ports: {}\n'.format(problem))
    if problems:
        return 1
    count = sum(len(s.get('ports') or []) for s in config['services'].values() if s)
    print('check_ports: {} published port(s), all on {}'.format(count, LOOPBACK))
    return 0


if __name__ == '__main__':
    sys.exit(main())
