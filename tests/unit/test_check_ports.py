"""scripts/check_ports.py rejects any rendered Compose service that listens
on a non-loopback host address or outside the project's host-port range."""

import json

import pytest

from scripts import check_ports


def rendered(**services):
    return {'name': 'industrial-iot', 'services': services}


def port(published, target, host_ip=None):
    entry = {'mode': 'ingress', 'target': target, 'protocol': 'tcp'}
    if published is not None:
        entry['published'] = published
    if host_ip is not None:
        entry['host_ip'] = host_ip
    return entry


def test_loopback_ports_in_range_pass():
    config = rendered(
        mosquitto={'ports': [port('20583', 1883, '127.0.0.1')]},
        processor={},
    )
    assert check_ports.port_problems(config) == []


@pytest.mark.parametrize('entry', [
    port('20583', 1883),                 # "20583:1883": every interface
    port('20583', 1883, '0.0.0.0'),
    port('20583', 1883, '::'),
    port('20583', 1883, '192.168.1.10'),
    port(None, 1883, '127.0.0.1'),       # random host port
    port('', 1883, '127.0.0.1'),
    port('8086', 8086, '127.0.0.1'),     # outside 20500-20599
    port('20590-20600', 8086, '127.0.0.1'),
])
def test_unsafe_published_port_is_reported(entry):
    problems = check_ports.port_problems(rendered(influxdb={'ports': [entry]}))
    assert len(problems) == 1
    assert problems[0].startswith('influxdb:')


def test_host_network_mode_is_reported():
    problems = check_ports.port_problems(rendered(grafana={'network_mode': 'host'}))
    assert problems == ['grafana: network_mode host bypasses port publishing']


def test_main_exits_non_zero_and_names_the_service(tmpdir, capsys):
    path = tmpdir.join('compose.json')
    path.write(json.dumps(rendered(grafana={'ports': [port('20530', 3000)]})))
    assert check_ports.main([str(path)]) == 1
    assert 'grafana:' in capsys.readouterr().err


def test_main_accepts_a_safe_config(tmpdir, capsys):
    path = tmpdir.join('compose.json')
    path.write(json.dumps(rendered(grafana={'ports': [port('20530', 3000, '127.0.0.1')]})))
    assert check_ports.main([str(path)]) == 0
    assert '1 published port' in capsys.readouterr().out


def test_main_rejects_a_config_without_services(tmpdir):
    path = tmpdir.join('compose.json')
    path.write('{}')
    assert check_ports.main([str(path)]) == 1
