"""InfluxStore schema setup and writes against real InfluxDB."""

import datetime
import uuid

import pytest
from influxdb import InfluxDBClient

import influx_store

PAYLOAD = {
    'gateway': 'gw-it',
    'zone': 'zone-a',
    'sensor_id': 'SN-001',
    'temperature': 23.4,
    'humidity': 41.2,
    'vibration': 0.12,
}


def recent_timestamp():
    # Points must fall inside the 7 day raw retention policy to be accepted.
    now = datetime.datetime.utcnow().replace(microsecond=123456)
    return now.isoformat() + 'Z'


@pytest.fixture
def store(influx_host):
    host, port = influx_host
    database = 'test_' + uuid.uuid4().hex
    client = InfluxDBClient(host=host, port=port, timeout=10)
    yield influx_store.InfluxStore(client, database)
    client.drop_database(database)


def test_ensure_schema_creates_retention_policies(store):
    store.ensure_schema()
    store.ensure_schema()
    rps = {rp['name']: rp for rp in store.client.get_list_retention_policies(store.database)}
    assert rps['raw']['default'] is True
    assert rps['raw']['duration'] == '168h0m0s'
    assert rps['rollup']['default'] is False
    assert rps['rollup']['duration'] == '8736h0m0s'


def test_ensure_schema_creates_continuous_query(store):
    store.ensure_schema()
    store.ensure_schema()
    result = store.client.query('SHOW CONTINUOUS QUERIES')
    cqs = list(result.get_points(measurement=store.database))
    assert [cq['name'] for cq in cqs] == ['cq_readings_1m']
    query = cqs[0]['query'].replace('"', '')
    assert 'INTO {}.rollup.sensor_readings_1m'.format(store.database) in query
    assert 'FROM {}.raw.sensor_readings'.format(store.database) in query


def test_written_reading_can_be_queried_back(store):
    store.ensure_schema()
    payload = dict(PAYLOAD, timestamp=recent_timestamp())
    store.write_reading(payload)
    result = store.client.query('SELECT * FROM sensor_readings', database=store.database)
    rows = list(result.get_points())
    assert len(rows) == 1
    row = rows[0]
    assert row['time'] == payload['timestamp']
    assert (row['gateway'], row['zone'], row['sensor']) == ('gw-it', 'zone-a', 'SN-001')
    assert (row['temperature'], row['humidity'], row['vibration']) == (23.4, 41.2, 0.12)
