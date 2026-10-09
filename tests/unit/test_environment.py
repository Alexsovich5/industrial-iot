import sys

import influxdb
import paho.mqtt
import serial


def test_python_is_3_5():
    assert sys.version_info[:2] == (3, 5)


def test_paho_mqtt_version():
    assert paho.mqtt.__version__ == '1.3.0'


def test_pyserial_version():
    assert serial.VERSION == '3.4'


def test_influxdb_client_version():
    assert influxdb.__version__ == '4.1.1'
