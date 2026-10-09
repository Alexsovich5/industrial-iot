"""Fixtures for tests that talk to the real Mosquitto and InfluxDB services.

Host names and ports come from the environment (Compose sets
``MQTT_HOST=mosquitto`` and ``INFLUXDB_HOST=influxdb`` for the tests
service) and default to localhost.
"""

import os
import socket
import time

import pytest


def wait_for_port(host, port, timeout=60):
    """Block until a TCP connection to host:port succeeds, or fail the test."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=2)
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
        else:
            sock.close()
            return
    pytest.fail('{}:{} not reachable after {}s: {}'.format(host, port, timeout, last_error))


@pytest.fixture(scope='session')
def mqtt_host():
    host = os.environ.get('MQTT_HOST', 'localhost')
    port = int(os.environ.get('MQTT_PORT', '1883'))
    wait_for_port(host, port)
    return host, port


@pytest.fixture(scope='session')
def influx_host():
    host = os.environ.get('INFLUXDB_HOST', 'localhost')
    port = int(os.environ.get('INFLUXDB_PORT', '8086'))
    wait_for_port(host, port)
    return host, port
