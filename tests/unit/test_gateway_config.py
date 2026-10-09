import os

import config
import sensor_gateway


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATEWAY_INI = os.path.join(REPO, 'config', 'gateway.ini')


def test_config_option_defaults_to_shipped_gateway_ini():
    args = sensor_gateway.parse_args([])
    assert args.config == 'config/gateway.ini'


def test_config_option_accepts_path():
    args = sensor_gateway.parse_args(['--config', '/etc/gw.ini'])
    assert args.config == '/etc/gw.ini'


def test_gateway_reads_settings_from_loaded_config():
    cfg = config.load(GATEWAY_INI, env={
        'GATEWAY_ID': 'gw-b', 'SERIAL_URL': 'socket://simulator-b:7000',
        'MQTT_HOST': 'mosquitto'})
    gateway = sensor_gateway.SensorGateway(cfg)
    assert gateway.gateway_id == 'gw-b'
    assert gateway.zone == 'zone-a'
    assert gateway.serial_url == 'socket://simulator-b:7000'
    assert gateway.baud_rate == 9600
    assert gateway.serial_timeout == 5
    assert gateway.mqtt_host == 'mosquitto'
    assert gateway.mqtt_port == 1883
    assert gateway.mqtt_keepalive == 60
