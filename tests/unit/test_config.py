import os

import pytest

import config


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATEWAY_INI = os.path.join(REPO, 'config', 'gateway.ini')
PROCESSOR_INI = os.path.join(REPO, 'config', 'processor.ini')

SAMPLE = """\
[gateway]
id = gw-a
zone = zone-a
[serial]
url = /dev/ttyACM0        ; or socket://simulator-a:7000
baud = 9600
timeout = 5
[mqtt]
host = localhost
port = 1883
[influxdb]
host = localhost
port = 8086
database = industrial_iot
[thresholds]
temperature_max = 45.0
humidity_max = 80
[custom]
note = kept as is
"""


@pytest.fixture
def ini(tmpdir):
    path = tmpdir.join('sample.ini')
    path.write(SAMPLE)
    return str(path)


def test_values_are_typed(ini):
    cfg = config.load(ini, env={})
    assert cfg['mqtt']['port'] == 1883
    assert isinstance(cfg['mqtt']['port'], int)
    assert cfg['serial']['baud'] == 9600
    assert cfg['thresholds']['temperature_max'] == 45.0
    assert isinstance(cfg['thresholds']['temperature_max'], float)
    assert cfg['mqtt']['host'] == 'localhost'
    assert cfg['gateway']['id'] == 'gw-a'


def test_thresholds_are_floats_even_when_written_as_integers(ini):
    cfg = config.load(ini, env={})
    assert cfg['thresholds']['humidity_max'] == 80.0
    assert isinstance(cfg['thresholds']['humidity_max'], float)


def test_inline_comment_is_stripped(ini):
    cfg = config.load(ini, env={})
    assert cfg['serial']['url'] == '/dev/ttyACM0'


def test_result_is_plain_nested_dict(ini):
    cfg = config.load(ini, env={})
    assert type(cfg) is dict
    assert all(type(section) is dict for section in cfg.values())


@pytest.mark.parametrize('var, section, key, value, expected', [
    ('GATEWAY_ID', 'gateway', 'id', 'gw-b', 'gw-b'),
    ('GATEWAY_ZONE', 'gateway', 'zone', 'zone-b', 'zone-b'),
    ('SERIAL_URL', 'serial', 'url', 'socket://simulator-b:7000', 'socket://simulator-b:7000'),
    ('MQTT_HOST', 'mqtt', 'host', 'mosquitto', 'mosquitto'),
    ('MQTT_PORT', 'mqtt', 'port', '11883', 11883),
    ('INFLUXDB_HOST', 'influxdb', 'host', 'influxdb', 'influxdb'),
    ('INFLUXDB_PORT', 'influxdb', 'port', '18086', 18086),
    ('INFLUXDB_DATABASE', 'influxdb', 'database', 'test_db', 'test_db'),
])
def test_env_var_overrides_ini_value(ini, var, section, key, value, expected):
    cfg = config.load(ini, env={var: value})
    assert cfg[section][key] == expected
    assert type(cfg[section][key]) is type(expected)


def test_env_override_does_not_add_absent_section(tmpdir):
    path = tmpdir.join('only_mqtt.ini')
    path.write('[mqtt]\nhost = localhost\nport = 1883\n')
    cfg = config.load(str(path), env={'INFLUXDB_HOST': 'influxdb', 'MQTT_HOST': 'broker'})
    assert cfg == {'mqtt': {'host': 'broker', 'port': 1883}}


def test_unrelated_env_vars_are_ignored(ini):
    cfg = config.load(ini, env={'HOME': '/root', 'PORT': '1'})
    assert cfg == config.load(ini, env={})


def test_invalid_port_override_is_rejected(ini):
    with pytest.raises(ValueError) as excinfo:
        config.load(ini, env={'MQTT_PORT': 'not-a-port'})
    assert 'MQTT_PORT' in str(excinfo.value)


def test_default_env_is_os_environ(ini, monkeypatch):
    monkeypatch.setenv('MQTT_HOST', 'from-process-env')
    assert config.load(ini)['mqtt']['host'] == 'from-process-env'


def test_missing_file_raises_with_path(tmpdir):
    missing = str(tmpdir.join('nope.ini'))
    with pytest.raises(FileNotFoundError) as excinfo:
        config.load(missing, env={})
    assert excinfo.value.filename == missing
    assert missing in str(excinfo.value)


def test_unknown_sections_are_preserved(ini):
    cfg = config.load(ini, env={})
    assert cfg['custom'] == {'note': 'kept as is'}


def test_shipped_gateway_ini_loads():
    cfg = config.load(GATEWAY_INI, env={})
    assert cfg['gateway'] == {'id': 'gw-a', 'zone': 'zone-a'}
    assert cfg['serial'] == {'url': '/dev/ttyACM0', 'baud': 9600, 'timeout': 5}
    assert cfg['mqtt'] == {'host': 'localhost', 'port': 1883, 'keepalive': 60}


def test_shipped_processor_ini_loads():
    cfg = config.load(PROCESSOR_INI, env={})
    assert cfg['mqtt'] == {'host': 'localhost', 'port': 1883, 'client_id': 'processor'}
    assert cfg['influxdb'] == {'host': 'localhost', 'port': 8086, 'database': 'industrial_iot'}
    assert cfg['thresholds'] == {
        'temperature_max': 45.0, 'humidity_max': 80.0, 'vibration_max': 5.0}
    assert cfg['trend'] == {'vibration_warn': 2.0, 'window': 12}
    assert isinstance(cfg['trend']['window'], int)
    assert isinstance(cfg['trend']['vibration_warn'], float)
