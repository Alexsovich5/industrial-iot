"""DataProcessor routing, alerting and error handling with in-memory fakes."""

import json
import logging

import pytest
from influxdb import line_protocol
from influxdb.exceptions import InfluxDBServerError

import alerts
import data_processor
import influx_store
from tests.fakes import FakeInfluxClient, FakeMqttClient

CFG = {
    'mqtt': {'host': 'broker', 'port': 1883, 'client_id': 'processor'},
    'influxdb': {'host': 'influx', 'port': 8086, 'database': 'industrial_iot'},
    'thresholds': {'temperature_max': 45.0, 'humidity_max': 80.0, 'vibration_max': 5.0},
    'trend': {'vibration_warn': 2.0, 'window': 12},
}


def payload(**overrides):
    data = {
        'gateway': 'gw-a',
        'zone': 'zone-a',
        'sensor_id': 'SN-001',
        'temperature': 23.4,
        'humidity': 41.2,
        'vibration': 0.12,
        'timestamp': '2017-10-02T10:17:13.123456Z',
    }
    data.update(overrides)
    return json.dumps(data)


class FailingStore(influx_store.InfluxStore):
    """An InfluxStore whose first ``failures`` reading writes raise a server error."""

    def __init__(self, client, database, failures):
        super(FailingStore, self).__init__(client, database)
        self.failures = failures

    def write_reading(self, data):
        if self.failures > 0:
            self.failures -= 1
            raise InfluxDBServerError('500: timeout')
        super(FailingStore, self).write_reading(data)


def make_processor(store=None):
    mqtt_client = FakeMqttClient(client_id='processor')
    influx = FakeInfluxClient()
    if store is None:
        store = influx_store.InfluxStore(influx, 'industrial_iot')
    else:
        influx = store.client
    engine = alerts.AlertEngine(CFG['thresholds'], CFG['trend']['window'],
                                CFG['trend']['vibration_warn'])
    processor = data_processor.DataProcessor(CFG, mqtt_client, store, engine)
    return processor, mqtt_client, influx


def measurements(influx):
    return [point['measurement'] for _, point in influx.points]


def test_on_connect_subscribes_to_data_topics_with_qos1():
    processor, client, _ = make_processor()
    client.fire_connect(0)
    assert client.subscriptions == [('sensors/+/+/data', 1)]


def test_failed_connect_does_not_subscribe():
    processor, client, _ = make_processor()
    client.fire_connect(5)
    assert client.subscriptions == []


def test_valid_message_writes_one_reading_and_no_alert():
    processor, client, influx = make_processor()
    client.fire_message('sensors/zone-a/SN-001/data', payload(), qos=1)
    assert measurements(influx) == ['sensor_readings']
    _, point = influx.points[0]
    assert point['tags'] == {'gateway': 'gw-a', 'zone': 'zone-a', 'sensor': 'SN-001'}
    assert point['time'] == '2017-10-02T10:17:13.123456Z'
    assert client.published == []
    assert processor.stats == {'received': 1, 'stored': 1, 'rejected': 0,
                               'alerts': 0, 'write_errors': 0, 'errors': 0}


def test_overheat_publishes_qos2_alert_and_stores_alert_point():
    processor, client, influx = make_processor()
    client.fire_message('sensors/zone-a/SN-001/data', payload(temperature=50.0), qos=1)

    assert measurements(influx) == ['sensor_readings', 'alerts']
    _, alert_point = influx.points[1]
    assert alert_point['tags']['state'] == 'raised'
    assert alert_point['tags']['metric'] == 'temperature'

    assert len(client.published) == 1
    msg = client.published[0]
    assert msg.topic == 'alerts/zone-a/SN-001'
    assert msg.qos == 2
    body = json.loads(msg.payload)
    assert body == {
        'zone': 'zone-a', 'sensor_id': 'SN-001', 'gateway': 'gw-a',
        'kind': 'threshold', 'metric': 'temperature', 'state': 'raised',
        'value': 50.0, 'limit': 45.0, 'message': 'temperature 50.0 above 45.0',
        'timestamp': '2017-10-02T10:17:13.123456Z',
    }
    assert processor.stats['alerts'] == 1
    assert processor.stats['stored'] == 1


def test_alert_fires_once_while_breach_continues():
    processor, client, _ = make_processor()
    client.fire_message('sensors/zone-a/SN-001/data', payload(temperature=50.0))
    client.fire_message('sensors/zone-a/SN-001/data', payload(temperature=51.0))
    client.fire_message('sensors/zone-a/SN-001/data', payload(temperature=30.0))
    states = [json.loads(m.payload)['state'] for m in client.published]
    assert states == ['raised', 'cleared']


@pytest.mark.parametrize('body', [
    b'not json at all',
    b'\xff\xfe',
    b'[1, 2, 3]',
    payload().replace('"humidity"', '"humid"').encode('utf-8'),
    payload(temperature='hot').encode('utf-8'),
])
def test_malformed_payload_is_rejected_and_nothing_written(body):
    processor, client, influx = make_processor()
    client.fire_message('sensors/zone-a/SN-001/data', body)
    assert influx.points == []
    assert client.published == []
    assert processor.stats['received'] == 1
    assert processor.stats['rejected'] == 1
    assert processor.stats['stored'] == 0


class LineProtocolInfluxClient(FakeInfluxClient):
    """FakeInfluxClient that serialises each write with the real line-protocol
    encoder, so values the real client cannot encode raise as they would."""

    def write_points(self, points, time_precision=None, database=None,
                     retention_policy=None, **kwargs):
        line_protocol.make_lines({'points': points}, precision=time_precision)
        return super(LineProtocolInfluxClient, self).write_points(
            points, time_precision=time_precision, database=database,
            retention_policy=retention_policy, **kwargs)


@pytest.mark.parametrize('body', [
    payload(timestamp='garbage'),
    payload(timestamp='2017-10-02 10:17:13'),
    payload(zone='zone-a\nalerts,zone=x value=1'),
    payload(sensor_id='SN-001/+'),
    payload(gateway='gw a'),
])
def test_payload_the_store_cannot_encode_is_rejected_without_crashing(body):
    store = influx_store.InfluxStore(LineProtocolInfluxClient(), 'industrial_iot')
    processor, client, influx = make_processor(store)
    client.fire_message('sensors/zone-a/SN-001/data', body)
    assert processor.stats['rejected'] == 1
    assert processor.stats['stored'] == 0
    assert influx.points == []
    assert client.published == []

    client.fire_message('sensors/zone-a/SN-001/data', payload())
    assert processor.stats['stored'] == 1


class ExplodingStore(influx_store.InfluxStore):
    """An InfluxStore whose first reading write raises an unexpected error."""

    def __init__(self, client, database):
        super(ExplodingStore, self).__init__(client, database)
        self.exploded = False

    def write_reading(self, data):
        if not self.exploded:
            self.exploded = True
            raise RuntimeError('unexpected')
        super(ExplodingStore, self).write_reading(data)


def test_unexpected_error_is_logged_counted_and_does_not_stop_the_loop(caplog):
    store = ExplodingStore(FakeInfluxClient(), 'industrial_iot')
    processor, client, influx = make_processor(store)
    with caplog.at_level(logging.ERROR, logger='data_processor'):
        client.fire_message('sensors/zone-a/SN-001/data', payload())
    assert 'Unexpected error' in caplog.text
    assert 'RuntimeError' in caplog.text
    assert processor.stats['errors'] == 1

    client.fire_message('sensors/zone-a/SN-001/data', payload())
    assert processor.stats['stored'] == 1


def test_out_of_range_payload_is_rejected():
    processor, client, influx = make_processor()
    client.fire_message('sensors/zone-a/SN-001/data', payload(humidity=140.0))
    assert influx.points == []
    assert client.published == []
    assert processor.stats['rejected'] == 1


def test_store_error_is_logged_counted_and_next_message_processed(caplog):
    influx = FakeInfluxClient()
    store = FailingStore(influx, 'industrial_iot', failures=1)
    processor, client, _ = make_processor(store)

    with caplog.at_level(logging.ERROR, logger='data_processor'):
        client.fire_message('sensors/zone-a/SN-001/data', payload())
    assert 'InfluxDB write failed' in caplog.text
    assert processor.stats['received'] == 1
    assert processor.stats['write_errors'] == 1
    assert processor.stats['stored'] == 0
    assert influx.points == []

    client.fire_message('sensors/zone-a/SN-001/data', payload())
    assert processor.stats['received'] == 2
    assert processor.stats['stored'] == 1
    assert measurements(influx) == ['sensor_readings']


def test_store_error_still_publishes_alert():
    influx = FakeInfluxClient()
    store = FailingStore(influx, 'industrial_iot', failures=1)
    processor, client, _ = make_processor(store)
    client.fire_message('sensors/zone-a/SN-001/data', payload(temperature=50.0))
    assert [m.topic for m in client.published] == ['alerts/zone-a/SN-001']
    assert measurements(influx) == ['alerts']


def test_payload_fields_win_over_topic_and_mismatch_is_logged(caplog):
    processor, client, influx = make_processor()
    with caplog.at_level(logging.WARNING, logger='data_processor'):
        client.fire_message('sensors/zone-x/SN-999/data',
                            payload(zone='zone-b', sensor_id='SN-002', temperature=50.0))
    assert 'does not match' in caplog.text
    _, point = influx.points[0]
    assert point['tags']['zone'] == 'zone-b'
    assert point['tags']['sensor'] == 'SN-002'
    assert [m.topic for m in client.published] == ['alerts/zone-b/SN-002']


def test_matching_topic_logs_no_warning(caplog):
    processor, client, _ = make_processor()
    with caplog.at_level(logging.WARNING, logger='data_processor'):
        client.fire_message('sensors/zone-a/SN-001/data', payload())
    assert caplog.text == ''


class FlakySchemaStore(object):
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def ensure_schema(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError('connection refused')


def test_ensure_schema_retries_until_influxdb_is_up():
    store = FlakySchemaStore(failures=3)
    sleeps = []
    data_processor.ensure_schema_with_retry(store, sleep=sleeps.append)
    assert store.calls == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_ensure_schema_retry_gives_up_after_max_attempts():
    store = FlakySchemaStore(failures=10)
    with pytest.raises(ConnectionError):
        data_processor.ensure_schema_with_retry(store, sleep=lambda s: None, attempts=3)
    assert store.calls == 3


def test_build_wires_config_into_clients():
    created = {}

    def mqtt_factory(client_id='', **kwargs):
        created['mqtt'] = FakeMqttClient(client_id=client_id, **kwargs)
        return created['mqtt']

    def influx_factory(host, port, **kwargs):
        created['influx'] = FakeInfluxClient(host=host, port=port, **kwargs)
        return created['influx']

    processor = data_processor.build(CFG, mqtt_factory=mqtt_factory,
                                     influx_factory=influx_factory)
    assert created['mqtt'].client_id == 'processor'
    assert (created['influx'].host, created['influx'].port) == ('influx', 8086)
    assert processor.store.database == 'industrial_iot'
    assert processor.engine.trend_window == 12
    assert processor.engine.vibration_warn == 2.0
    assert processor.engine.limits['temperature'] == 45.0
