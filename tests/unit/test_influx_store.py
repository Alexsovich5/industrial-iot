"""InfluxStore point building and schema setup against FakeInfluxClient."""

import alerts
import influx_store
from tests.fakes import FakeInfluxClient

PAYLOAD = {
    'gateway': 'gw-a',
    'zone': 'zone-a',
    'sensor_id': 'SN-001',
    'temperature': 23,
    'humidity': 41.2,
    'vibration': 0.12,
    'timestamp': '2017-10-02T10:17:13.123456Z',
}

EVENT = alerts.AlertEvent(
    zone='zone-a', sensor_id='SN-001', gateway='gw-a', kind='threshold',
    metric='temperature', state='raised', value=46.0, limit=45.0,
    message='temperature 46.0 above 45.0', timestamp='2017-10-02T10:17:18.000001Z')


def make_store(database='industrial_iot'):
    client = FakeInfluxClient()
    return client, influx_store.InfluxStore(client, database)


def test_reading_point_has_measurement_tags_float_fields_and_time():
    _, store = make_store()
    point = store.reading_point(PAYLOAD)
    assert point['measurement'] == 'sensor_readings'
    assert point['tags'] == {'gateway': 'gw-a', 'zone': 'zone-a', 'sensor': 'SN-001'}
    assert point['fields'] == {'temperature': 23.0, 'humidity': 41.2, 'vibration': 0.12}
    for value in point['fields'].values():
        assert isinstance(value, float)
    assert point['time'] == '2017-10-02T10:17:13.123456Z'


def test_alert_point_tags_and_fields():
    _, store = make_store()
    point = store.alert_point(EVENT)
    assert point['measurement'] == 'alerts'
    assert point['tags'] == {'zone': 'zone-a', 'sensor': 'SN-001', 'metric': 'temperature',
                             'kind': 'threshold', 'state': 'raised'}
    assert point['fields'] == {'value': 46.0, 'limit': 45.0,
                               'message': 'temperature 46.0 above 45.0'}
    assert point['time'] == '2017-10-02T10:17:18.000001Z'


def test_write_reading_uses_microsecond_precision_and_database():
    client, store = make_store('plant')
    store.write_reading(PAYLOAD)
    assert len(client.points) == 1
    assert client.points[0][1] == store.reading_point(PAYLOAD)
    assert client.writes[0]['time_precision'] == 'u'
    assert client.writes[0]['database'] == 'plant'


def test_write_alert_writes_alert_point():
    client, store = make_store('plant')
    store.write_alert(EVENT)
    assert client.points[0][1]['measurement'] == 'alerts'
    assert client.writes[0]['time_precision'] == 'u'
    assert client.writes[0]['database'] == 'plant'


def test_ensure_schema_creates_database_policies_and_cq():
    client, store = make_store()
    store.ensure_schema()
    assert client.databases == ['industrial_iot']
    rps = {rp['name']: rp for rp in client.retention_policies}
    assert rps['raw']['duration'] == '7d'
    assert rps['raw']['default'] is True
    assert rps['raw']['database'] == 'industrial_iot'
    assert rps['rollup']['duration'] == '52w'
    assert rps['rollup']['default'] is False
    assert [cq[1] for cq in client.continuous_queries] == ['cq_readings_1m']


def test_ensure_schema_twice_creates_everything_once():
    client, store = make_store()
    store.ensure_schema()
    store.ensure_schema()
    kinds = [call[0] for call in client.calls]
    assert kinds.count('create_database') == 1
    assert kinds.count('create_retention_policy') == 2
    assert kinds.count('create_continuous_query') == 1


def test_ensure_schema_skips_existing_database():
    client, store = make_store()
    client.databases.append('industrial_iot')
    store.ensure_schema()
    assert ('create_database', 'industrial_iot') not in client.calls


def test_cq_statement_is_filled_with_configured_database():
    client, store = make_store('test_x')
    store.ensure_schema()
    statement = [call[1] for call in client.calls if call[0] == 'create_continuous_query'][0]
    assert 'ON "test_x"' in statement
    assert 'INTO "test_x"."rollup"' in statement
    assert 'FROM "test_x"."raw"' in statement
    assert 'industrial_iot' not in statement
    assert 'GROUP BY time(1m), *' in statement
    assert 'max(vibration) AS vibration_max' in statement


def test_cq_for_another_database_does_not_count_as_existing():
    client, store = make_store('test_x')
    other = influx_store.InfluxStore(client, 'test_y')
    other.ensure_schema()
    store.ensure_schema()
    assert sorted(cq[0] for cq in client.continuous_queries) == ['test_x', 'test_y']
