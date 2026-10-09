"""Create the InfluxDB datasource and load the floor dashboard into Grafana 4.6.

Grafana 4.x has no file provisioning, so both are pushed through the HTTP
API. Running the script again is safe: an existing datasource (HTTP 409) is
left as it is and the dashboard is saved with ``overwrite``.

Log lines and errors show the Grafana URL through ``redact_url``, so
credentials or tokens embedded in it are never printed.
"""

import argparse
import json
import logging
import sys
import time
from urllib.parse import urlsplit

import requests

DEFAULT_DATASOURCE = 'industrial_iot'
DEFAULT_INFLUX_DB = 'industrial_iot'

log = logging.getLogger('grafana_import')


class GrafanaError(Exception):
    """Raised when Grafana rejects a request."""


def redact_url(url):
    """Return ``scheme://host[:port]`` with userinfo, path and query hidden."""
    parts = urlsplit(url)
    host = parts.hostname or ''
    if parts.port is not None:
        host = '{}:{}'.format(host, parts.port)
    if parts.username is not None or parts.password is not None:
        host = '<redacted>@' + host
    tail = '/<redacted>' if parts.path.strip('/') or parts.query or parts.fragment else ''
    return '{}://{}{}'.format(parts.scheme, host, tail)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--url', default='http://localhost:3000', help='Grafana base URL')
    parser.add_argument('--user', default='admin')
    parser.add_argument('--password', default='admin')
    parser.add_argument('--influx-url', default='http://influxdb:8086',
                        help='InfluxDB URL as seen from the Grafana server')
    parser.add_argument('--influx-db', default=DEFAULT_INFLUX_DB)
    parser.add_argument('--datasource-name', default=DEFAULT_DATASOURCE)
    parser.add_argument('--dashboard', default='grafana/dashboard.json')
    parser.add_argument('--wait', type=float, default=120.0,
                        help='seconds to wait for /api/health to answer')
    return parser


def wait_for_health(session, url, timeout, interval=2.0):
    """Poll /api/health until it returns 200 or the timeout passes."""
    deadline = time.time() + timeout
    last_error = None
    while True:
        try:
            response = session.get(url + '/api/health', timeout=5)
            if response.status_code == 200:
                return
            last_error = 'HTTP {}'.format(response.status_code)
        except requests.RequestException as exc:
            last_error = exc
        if time.time() >= deadline:
            raise GrafanaError('Grafana at {} not healthy after {}s: {}'.format(
                redact_url(url), timeout, last_error))
        log.info('waiting for Grafana: %s', last_error)
        time.sleep(interval)


def datasource_body(name, influx_url, database):
    return {
        'name': name,
        'type': 'influxdb',
        'access': 'proxy',
        'url': influx_url,
        'database': database,
        'isDefault': True,
    }


def create_datasource(session, url, body):
    """POST the datasource; return True if created, False if it already existed."""
    response = session.post(url + '/api/datasources', json=body, timeout=10)
    if response.status_code == 200:
        return True
    if response.status_code == 409:
        return False
    raise GrafanaError('datasource create failed: HTTP {} {}'.format(
        response.status_code, response.text))


def import_dashboard(session, url, dashboard):
    """POST the dashboard with overwrite and return Grafana's response body."""
    dashboard = dict(dashboard)
    dashboard['id'] = None
    payload = {'dashboard': dashboard, 'overwrite': True}
    response = session.post(url + '/api/dashboards/db', json=payload, timeout=10)
    if response.status_code != 200:
        raise GrafanaError('dashboard import failed: HTTP {} {}'.format(
            response.status_code, response.text))
    return response.json()


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
    url = args.url.rstrip('/')
    with open(args.dashboard) as handle:
        dashboard = json.load(handle)

    session = requests.Session()
    session.auth = (args.user, args.password)
    try:
        wait_for_health(session, url, args.wait)
        created = create_datasource(
            session, url, datasource_body(args.datasource_name, args.influx_url, args.influx_db))
        log.info('datasource %s %s', args.datasource_name,
                 'created' if created else 'already exists')
        result = import_dashboard(session, url, dashboard)
        log.info('dashboard saved: %s', result.get('slug'))
    except GrafanaError as exc:
        log.error('%s', exc)
        return 1
    finally:
        session.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
