import datetime
import json

import pytest

import readings
from readings import Reading


NOW = datetime.datetime(2017, 10, 2, 10, 17, 13, 123456)


def test_parse_valid_sketch_line():
    reading = readings.parse_line('SN-001,23.4,41.2,0.12')
    assert reading == Reading('SN-001', 23.4, 41.2, 0.12)
    assert isinstance(reading.temperature, float)


def test_parse_comment_line_is_ignored():
    assert readings.parse_line('# Sensor node initialized') is None


def test_parse_blank_line_is_ignored():
    assert readings.parse_line('') is None
    assert readings.parse_line('   \r\n') is None


def test_parse_nan_field_is_rejected():
    assert readings.parse_line('SN-001,nan,40,0.1') is None


def test_parse_infinite_field_is_rejected():
    assert readings.parse_line('SN-001,inf,40,0.1') is None


def test_parse_three_fields_is_rejected():
    assert readings.parse_line('SN-001,23.4,41.2') is None


def test_parse_five_fields_is_rejected():
    assert readings.parse_line('SN-001,23.4,41.2,0.12,7') is None


def test_parse_non_numeric_field_is_rejected():
    assert readings.parse_line('SN-001,warm,41.2,0.12') is None


@pytest.mark.parametrize('sensor_id', ['', 'SN 001', 'SN/001', 'x' * 33, 'SN-00é'])
def test_parse_bad_sensor_id_is_rejected(sensor_id):
    assert readings.parse_line('{},23.4,41.2,0.12'.format(sensor_id)) is None


def test_parse_tolerates_extra_whitespace():
    reading = readings.parse_line('  SN_7 , 23.4 ,41.2,  0.12 \r\n')
    assert reading == Reading('SN_7', 23.4, 41.2, 0.12)


def test_validate_accepts_in_range_reading():
    assert readings.validate(Reading('SN-001', 23.4, 41.2, 0.12)) == []


def test_validate_accepts_range_limits():
    assert readings.validate(Reading('SN-001', -40.0, 0.0, 0.0)) == []
    assert readings.validate(Reading('SN-001', 80.0, 100.0, 28.0)) == []


def test_validate_reports_humidity_out_of_range():
    problems = readings.validate(Reading('SN-001', 23.4, 120.0, 0.12))
    assert len(problems) == 1
    assert 'humidity' in problems[0]


def test_validate_reports_temperature_out_of_range():
    problems = readings.validate(Reading('SN-001', -50.0, 41.2, 0.12))
    assert len(problems) == 1
    assert 'temperature' in problems[0]


def test_validate_reports_vibration_out_of_range():
    problems = readings.validate(Reading('SN-001', 23.4, 41.2, 30.0))
    assert len(problems) == 1
    assert 'vibration' in problems[0]


def test_validate_reports_every_problem():
    problems = readings.validate(Reading('SN-001', -50.0, 120.0, 30.0))
    assert len(problems) == 3


def test_payload_round_trip_keeps_keys_and_types():
    reading = Reading('SN-001', 23.4, 41.2, 0.12)
    text = readings.to_payload(reading, 'gw-a', 'zone-a', NOW)
    assert isinstance(text, str)

    data = readings.from_payload(text)
    assert set(data) == {'gateway', 'zone', 'sensor_id', 'temperature',
                         'humidity', 'vibration', 'timestamp'}
    assert data['gateway'] == 'gw-a'
    assert data['zone'] == 'zone-a'
    assert data['sensor_id'] == 'SN-001'
    assert data['temperature'] == 23.4
    assert data['humidity'] == 41.2
    assert data['vibration'] == 0.12
    for key in ('temperature', 'humidity', 'vibration'):
        assert isinstance(data[key], float)
    assert data['timestamp'] == '2017-10-02T10:17:13.123456Z'
    assert data['timestamp'].endswith('Z')


def test_payload_is_plain_json():
    text = readings.to_payload(Reading('SN-001', 23.4, 41.2, 0.12), 'gw-a', 'zone-a', NOW)
    assert json.loads(text)['sensor_id'] == 'SN-001'


def _payload(**overrides):
    data = {
        'gateway': 'gw-a', 'zone': 'zone-a', 'sensor_id': 'SN-001',
        'temperature': 23.4, 'humidity': 41.2, 'vibration': 0.12,
        'timestamp': '2017-10-02T10:17:13.123456Z',
    }
    data.update(overrides)
    return data


def test_from_payload_accepts_integer_numbers_as_float():
    data = readings.from_payload(json.dumps(_payload(humidity=40)))
    assert data['humidity'] == 40.0
    assert isinstance(data['humidity'], float)


@pytest.mark.parametrize('missing', ['gateway', 'zone', 'sensor_id', 'temperature',
                                     'humidity', 'vibration', 'timestamp'])
def test_from_payload_rejects_missing_key(missing):
    data = _payload()
    del data[missing]
    with pytest.raises(ValueError):
        readings.from_payload(json.dumps(data))


@pytest.mark.parametrize('field,value', [
    ('temperature', '23.4'),
    ('humidity', None),
    ('vibration', True),
    ('temperature', [1.0]),
])
def test_from_payload_rejects_non_numeric_field(field, value):
    with pytest.raises(ValueError):
        readings.from_payload(json.dumps(_payload(**{field: value})))


@pytest.mark.parametrize('field', ['gateway', 'zone', 'sensor_id', 'timestamp'])
def test_from_payload_rejects_non_string_field(field):
    with pytest.raises(ValueError):
        readings.from_payload(json.dumps(_payload(**{field: 5})))


def test_from_payload_rejects_invalid_json():
    with pytest.raises(ValueError):
        readings.from_payload('{not json')


def test_from_payload_rejects_non_object():
    with pytest.raises(ValueError):
        readings.from_payload('[1, 2, 3]')


@pytest.mark.parametrize('timestamp', [
    'garbage',
    '',
    '2017-10-02 10:17:13Z',
    '2017-10-02T10:17:13',
    '2017-10-02T10:17:13+04:00',
    '2017-13-02T10:17:13Z',
    '2017-10-02T10:17:13.123456Z\n',
])
def test_from_payload_rejects_timestamp_that_is_not_utc_iso8601(timestamp):
    with pytest.raises(ValueError):
        readings.from_payload(json.dumps(_payload(timestamp=timestamp)))


@pytest.mark.parametrize('timestamp', ['2017-10-02T10:17:13Z', '2017-10-02T10:17:13.5Z'])
def test_from_payload_accepts_utc_timestamps_with_and_without_fraction(timestamp):
    assert readings.from_payload(json.dumps(_payload(timestamp=timestamp)))['timestamp'] \
        == timestamp


@pytest.mark.parametrize('field', ['gateway', 'zone', 'sensor_id'])
@pytest.mark.parametrize('value', [
    '', 'zone a', 'zone/a', 'zone+', 'zone#', 'a\nalerts,zone=x value=1', 'a,b=c', 'zone-a\n',
    'x' * 65,
])
def test_from_payload_rejects_identifiers_outside_the_name_charset(field, value):
    with pytest.raises(ValueError):
        readings.from_payload(json.dumps(_payload(**{field: value})))


@pytest.mark.parametrize('value', ['zone-a', 'Hall_2', 'line.3'])
def test_from_payload_accepts_plain_zone_and_gateway_names(value):
    data = readings.from_payload(json.dumps(_payload(zone=value, gateway=value)))
    assert data['zone'] == value and data['gateway'] == value


def test_to_payload_round_trips_whole_second_timestamps():
    reading = readings.Reading('SN-001', 23.4, 41.2, 0.12)
    text = readings.to_payload(reading, 'gw-a', 'zone-a',
                               datetime.datetime(2017, 10, 2, 10, 17, 13))
    assert readings.from_payload(text)['timestamp'] == '2017-10-02T10:17:13Z'
