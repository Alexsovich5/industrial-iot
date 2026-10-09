import pytest

import alerts
from alerts import AlertEngine, AlertEvent


THRESHOLDS = {
    'temperature_max': 45.0,
    'humidity_max': 80.0,
    'vibration_max': 5.0,
}

PAYLOAD_FIELDS = ('zone', 'sensor_id', 'gateway', 'kind', 'metric', 'state',
                  'value', 'limit', 'message', 'timestamp')


def payload(temperature=22.0, humidity=40.0, vibration=0.1,
            zone='zone-a', sensor_id='SN-001', gateway='gw-a',
            timestamp='2017-10-02T10:17:13.123456Z'):
    return {
        'gateway': gateway,
        'zone': zone,
        'sensor_id': sensor_id,
        'temperature': temperature,
        'humidity': humidity,
        'vibration': vibration,
        'timestamp': timestamp,
    }


def engine(window=4, warn=2.0, thresholds=None):
    return AlertEngine(thresholds or dict(THRESHOLDS), trend_window=window,
                       vibration_warn=warn)


def test_alert_event_fields_match_alert_payload():
    assert AlertEvent._fields == PAYLOAD_FIELDS


def test_normal_reading_gives_no_events():
    assert engine().evaluate(payload()) == []


def test_temperature_raises_once_then_clears_once():
    eng = engine()

    first = eng.evaluate(payload(temperature=46.0))
    assert len(first) == 1
    event = first[0]
    assert event.kind == 'threshold'
    assert event.metric == 'temperature'
    assert event.state == 'raised'
    assert event.value == 46.0
    assert event.limit == 45.0
    assert event.zone == 'zone-a'
    assert event.sensor_id == 'SN-001'
    assert event.gateway == 'gw-a'
    assert event.timestamp == '2017-10-02T10:17:13.123456Z'

    assert eng.evaluate(payload(temperature=46.0)) == []

    cleared = eng.evaluate(payload(temperature=44.0))
    assert len(cleared) == 1
    assert cleared[0].kind == 'threshold'
    assert cleared[0].metric == 'temperature'
    assert cleared[0].state == 'cleared'
    assert cleared[0].value == 44.0
    assert cleared[0].limit == 45.0

    assert eng.evaluate(payload(temperature=44.0)) == []


def test_value_equal_to_limit_is_not_a_breach():
    assert engine().evaluate(payload(temperature=45.0)) == []


@pytest.mark.parametrize('metric,limit,high,low', [
    ('humidity', 80.0, 85.0, 70.0),
    ('vibration', 5.0, 5.5, 0.2),
])
def test_humidity_and_vibration_are_edge_triggered(metric, limit, high, low):
    # A large window keeps the vibration trend rule out of this test.
    eng = engine(window=100)

    raised = eng.evaluate(payload(**{metric: high}))
    assert [(e.kind, e.metric, e.state, e.value, e.limit) for e in raised] == [
        ('threshold', metric, 'raised', high, limit)]

    assert eng.evaluate(payload(**{metric: high})) == []

    cleared = eng.evaluate(payload(**{metric: low}))
    assert [(e.kind, e.metric, e.state, e.value, e.limit) for e in cleared] == [
        ('threshold', metric, 'cleared', low, limit)]


def test_two_metrics_breaching_together_give_two_events():
    events = engine(window=100).evaluate(payload(temperature=50.0, humidity=90.0))
    assert sorted(e.metric for e in events) == ['humidity', 'temperature']
    assert all(e.state == 'raised' for e in events)


def test_trend_waits_for_full_window_then_raises_above_warn():
    eng = engine(window=4, warn=2.0)

    # Mean of the first three values would already be above 2.0, but the
    # window is not full yet.
    for value in (3.0, 3.0, 3.0):
        assert eng.evaluate(payload(vibration=value)) == []


def test_trend_mean_equal_to_warn_does_not_raise_and_next_reading_does():
    eng = engine(window=4, warn=2.0)

    for value in (1.0, 1.0, 3.0, 3.0):
        assert eng.evaluate(payload(vibration=value)) == []

    # Window is now 1, 3, 3, 3: mean 2.5.
    events = eng.evaluate(payload(vibration=3.0))
    assert len(events) == 1
    event = events[0]
    assert event.kind == 'trend'
    assert event.metric == 'vibration'
    assert event.state == 'raised'
    assert event.value == pytest.approx(2.5)
    assert event.limit == 2.0

    # Still above the warning level: no repeat.
    assert eng.evaluate(payload(vibration=3.0)) == []


def test_trend_clears_when_mean_drops_back():
    eng = engine(window=4, warn=2.0)
    for value in (3.0, 3.0, 3.0, 3.0):
        eng.evaluate(payload(vibration=value))

    # 3, 3, 3, 0 -> 2.25, still raised.
    assert eng.evaluate(payload(vibration=0.0)) == []
    # 3, 3, 0, 0 -> 1.5, cleared.
    events = eng.evaluate(payload(vibration=0.0))
    assert [(e.kind, e.state) for e in events] == [('trend', 'cleared')]
    assert events[0].value == pytest.approx(1.5)


def test_trend_and_vibration_threshold_are_independent_rules():
    eng = engine(window=2, warn=2.0)
    assert eng.evaluate(payload(vibration=3.0)) == []
    events = eng.evaluate(payload(vibration=6.0))
    assert sorted((e.kind, e.state) for e in events) == [
        ('threshold', 'raised'), ('trend', 'raised')]


def test_two_sensors_in_same_zone_keep_separate_state():
    eng = engine()
    assert len(eng.evaluate(payload(sensor_id='SN-001', temperature=46.0))) == 1
    # SN-002 has not breached yet, so its first breach raises too.
    events = eng.evaluate(payload(sensor_id='SN-002', temperature=46.0))
    assert [(e.sensor_id, e.state) for e in events] == [('SN-002', 'raised')]
    # SN-002 recovering does not clear SN-001.
    events = eng.evaluate(payload(sensor_id='SN-002', temperature=40.0))
    assert [(e.sensor_id, e.state) for e in events] == [('SN-002', 'cleared')]
    assert eng.evaluate(payload(sensor_id='SN-001', temperature=46.0)) == []


def test_same_sensor_id_in_two_zones_keeps_separate_state():
    eng = engine()
    assert len(eng.evaluate(payload(zone='zone-a', temperature=46.0))) == 1
    events = eng.evaluate(payload(zone='zone-b', temperature=46.0))
    assert [(e.zone, e.state) for e in events] == [('zone-b', 'raised')]


def test_trend_windows_are_per_sensor():
    eng = engine(window=2, warn=2.0)
    eng.evaluate(payload(sensor_id='SN-001', vibration=3.0))
    # A different sensor's value must not fill SN-001's window.
    assert eng.evaluate(payload(sensor_id='SN-002', vibration=3.0)) == []
    events = eng.evaluate(payload(sensor_id='SN-001', vibration=3.0))
    assert [(e.sensor_id, e.kind) for e in events] == [('SN-001', 'trend')]


def test_raised_message_format():
    event = engine().evaluate(payload(temperature=46))[0]
    assert event.message == 'temperature 46.0 above 45.0'
    assert isinstance(event.value, float)


def test_cleared_and_trend_message_format():
    eng = engine(window=2, warn=2.0)
    eng.evaluate(payload(temperature=47.1))
    cleared = eng.evaluate(payload(temperature=44.0))[0]
    assert cleared.message == 'temperature 44.0 back below 45.0'

    eng.evaluate(payload(vibration=2.5))
    trend = eng.evaluate(payload(vibration=2.6))[0]
    assert trend.message == 'vibration rolling mean 2.55 above 2.0'


def test_engine_rejects_bad_settings():
    with pytest.raises(ValueError):
        AlertEngine(dict(THRESHOLDS), trend_window=0, vibration_warn=2.0)
    with pytest.raises(KeyError):
        AlertEngine({'temperature_max': 45.0}, trend_window=4, vibration_warn=2.0)


def test_module_lists_threshold_metrics():
    assert alerts.THRESHOLD_METRICS == ('temperature', 'humidity', 'vibration')
