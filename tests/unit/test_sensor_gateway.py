import datetime
import itertools
import json

import pytest
import serial

import readings
import sensor_gateway
from tests.fakes import FakeMqttClient

NOW = datetime.datetime(2017, 10, 2, 10, 17, 13, 123456)


def make_cfg(url='loop://'):
    return {
        'gateway': {'id': 'gw-a', 'zone': 'zone-a'},
        'serial': {'url': url, 'baud': 9600, 'timeout': 0.05},
        'mqtt': {'host': 'broker', 'port': 1883, 'keepalive': 60},
    }


class Recorder(object):
    def __init__(self):
        self.sleeps = []
        self.clients = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def mqtt_factory(self, client_id='', **kwargs):
        client = FakeMqttClient(client_id=client_id, **kwargs)
        self.clients.append(client)
        return client


def loop_port(lines):
    port = serial.serial_for_url('loop://', timeout=0.05)
    for line in lines:
        port.write((line + '\r\n').encode('ascii'))
    return port


def make_gateway(recorder, serial_factory, url='loop://'):
    return sensor_gateway.SensorGateway(
        make_cfg(url),
        mqtt_factory=recorder.mqtt_factory,
        serial_factory=serial_factory,
        clock=lambda: NOW,
        sleep=recorder.sleep)


def test_valid_line_publishes_qos1_on_zone_sensor_topic():
    rec = Recorder()
    gw = make_gateway(rec, lambda *a, **k: None)
    assert gw.process_line('SN-001,23.4,41.3,0.12') is True
    client = rec.clients[0]
    assert client.client_id == 'gw-a'
    assert len(client.published) == 1
    msg = client.published[0]
    assert msg.topic == 'sensors/zone-a/SN-001/data'
    assert msg.qos == 1
    data = readings.from_payload(msg.payload)
    assert data['gateway'] == 'gw-a'
    assert data['zone'] == 'zone-a'
    assert data['sensor_id'] == 'SN-001'
    assert data['temperature'] == 23.4
    assert data['vibration'] == 0.12
    assert data['timestamp'] == '2017-10-02T10:17:13.123456Z'


@pytest.mark.parametrize('line', [
    '# Sensor node initialized',
    '',
    '\x07%$garbage',
    'SN-001,nan,40,0.1',
    'SN-001,23.4,120.0,0.12',
    'SN-001,-50.0,40.0,0.12',
    'SN-001,23.4,40.0,30.0',
])
def test_comment_garbage_and_out_of_range_lines_are_not_published(line):
    rec = Recorder()
    gw = make_gateway(rec, lambda *a, **k: None)
    assert gw.process_line(line) is False
    assert rec.clients[0].published == []


def test_run_reads_serial_url_skips_junk_and_stops_after_max_readings():
    lines = ['# Sensor node initialized', 'garbage', 'SN-001,22.0,45.0,0.10',
             'SN-001,22.1,45.1,0.11', '', 'SN-001,99.0,45.0,0.10',
             'SN-001,22.2,45.2,0.12', 'SN-001,22.3,45.3,0.13']
    port = loop_port(lines)
    calls = []

    def factory(url, **kwargs):
        calls.append((url, kwargs))
        return port

    rec = Recorder()
    gw = make_gateway(rec, factory)
    assert gw.run(max_readings=3) == 3

    assert calls == [('loop://', {'baudrate': 9600, 'timeout': 0.05})]
    client = rec.clients[0]
    assert client.connected_to == ('broker', 1883, 60)
    assert client.loop_started and client.loop_stopped and client.disconnected
    temps = [json.loads(m.payload)['temperature'] for m in client.published]
    assert temps == [22.0, 22.1, 22.2]
    assert client.subscriptions == []
    # Arduino reset delay applies only to device paths, not to URLs.
    assert 2 not in rec.sleeps


def test_device_path_waits_for_arduino_reset():
    port = loop_port(['SN-001,22.0,45.0,0.10'])
    rec = Recorder()
    gw = make_gateway(rec, lambda url, **kwargs: port, url='/dev/ttyACM0')
    assert gw.run(max_readings=1) == 1
    assert rec.sleeps[0] == 2


class BrokenPort(object):
    def __init__(self):
        self.closed = False

    def readline(self):
        raise serial.SerialException('device reports readiness to read but returned no data')

    def close(self):
        self.closed = True


def test_serial_exception_on_read_triggers_reconnect_through_factory():
    broken = BrokenPort()
    good = loop_port(['SN-001,22.0,45.0,0.10', 'SN-001,22.1,45.1,0.11'])
    ports = [broken, good]
    calls = []

    def factory(url, **kwargs):
        calls.append(url)
        return ports.pop(0)

    rec = Recorder()
    gw = make_gateway(rec, factory)
    assert gw.run(max_readings=2) == 2
    assert calls == ['loop://', 'loop://']
    assert broken.closed
    assert len(rec.sleeps) == 1 and rec.sleeps[0] > 0
    assert len(rec.clients[0].published) == 2


def test_failed_reconnects_back_off_with_growing_delay():
    good = loop_port(['SN-001,22.0,45.0,0.10'])
    outcomes = [serial.SerialException('no such device')] * 4 + [good]

    def factory(url, **kwargs):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    rec = Recorder()
    gw = make_gateway(rec, factory)
    assert gw.run(max_readings=1) == 1
    assert len(rec.sleeps) == 4
    assert rec.sleeps == sorted(rec.sleeps)
    assert rec.sleeps[-1] > rec.sleeps[0]
    assert max(rec.sleeps) <= sensor_gateway.MAX_BACKOFF


def test_backoff_is_capped():
    delays = list(itertools.islice(sensor_gateway.backoff_delays(), 20))
    assert delays[0] == sensor_gateway.INITIAL_BACKOFF
    assert all(b >= a for a, b in zip(delays, delays[1:]))
    assert delays[-1] == sensor_gateway.MAX_BACKOFF


def test_cli_accepts_config_and_max_readings():
    args = sensor_gateway.parse_args(['--config', 'x.ini', '--max-readings', '4'])
    assert args.config == 'x.ini'
    assert args.max_readings == 4
    assert sensor_gateway.parse_args([]).max_readings is None
