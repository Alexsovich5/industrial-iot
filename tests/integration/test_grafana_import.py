"""grafana_import.py against the locally built Grafana 4.6.3."""

import os

import pytest
import requests

from scripts import grafana_import

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DASHBOARD_PATH = os.path.join(ROOT, 'grafana', 'dashboard.json')
AUTH = ('admin', 'admin')


@pytest.fixture(scope='module')
def grafana_url():
    return os.environ.get('GRAFANA_URL', 'http://localhost:3000')


@pytest.fixture(scope='module')
def imported(grafana_url, influx_host):
    host, port = influx_host
    argv = [
        '--url', grafana_url,
        '--user', AUTH[0],
        '--password', AUTH[1],
        '--influx-url', 'http://{}:{}'.format(host, port),
        '--dashboard', DASHBOARD_PATH,
        '--wait', '180',
    ]
    # A second run must succeed against the existing datasource and dashboard.
    assert grafana_import.main(argv) == 0
    assert grafana_import.main(argv) == 0
    return grafana_url


def test_dashboard_is_served(imported):
    response = requests.get(imported + '/api/dashboards/db/industrial-iot-floor',
                            auth=AUTH, timeout=10)
    assert response.status_code == 200
    body = response.json()
    assert body['dashboard']['title'] == 'Industrial IoT Floor'
    assert body['meta']['slug'] == 'industrial-iot-floor'


def test_datasource_exists(imported):
    response = requests.get(imported + '/api/datasources/name/industrial_iot',
                            auth=AUTH, timeout=10)
    assert response.status_code == 200
    body = response.json()
    assert body['type'] == 'influxdb'
    assert body['access'] == 'proxy'
    assert body['database'] == 'industrial_iot'


def test_only_one_datasource_with_that_name(imported):
    response = requests.get(imported + '/api/datasources', auth=AUTH, timeout=10)
    assert response.status_code == 200
    names = [ds['name'] for ds in response.json()]
    assert names.count('industrial_iot') == 1
