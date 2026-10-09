"""End-to-end pipeline: simulator -> gateway -> broker -> processor -> InfluxDB.

Every component runs in-process against the real Mosquitto and InfluxDB
services. The simulator serves the ``overheat`` profile over TCP, the
gateway reads it through a pyserial ``socket://`` URL, and the processor
writes into a throwaway ``test_<uuid>`` database.
"""

import threading
import time
import uuid

import pytest
from influxdb import InfluxDBClient

import influx_store
import node_simulator
import sensor_gateway
from tests.integration.test_processor import start_processor

ZONE = 'zone-e2e'
SENSOR_ID = 'SN-E2E'
INTERVAL = 0.05
# The overheat profile crosses 45 C after about 26 readings.
GATEWAY_READINGS = 40
MIN_READINGS = 10
TIMEOUT = 30


@pytest.fixture
def store(influx_host):
    host, port = influx_host
    database = 'test_' + uuid.uuid4().hex
    client = InfluxDBClient(host=host, port=port, timeout=10)
    store = influx_store.InfluxStore(client, database)
    store.ensure_schema()
    yield store
    client.drop_database(database)


@pytest.fixture
def simulator():
    server = node_simulator.serve(
        '127.0.0.1', 0,
        lambda: node_simulator.generate('overheat', SENSOR_ID, 7),
        INTERVAL)
    yield server
    server.shutdown()
    server.server_close()


def query(store, text):
    return list(store.client.query(text, database=store.database).get_points())


def test_reading_travels_from_simulator_to_influxdb(mqtt_host, store, simulator):
    host, port = mqtt_host
    processor = start_processor(host, port, store)
    cfg = {
        'gateway': {'id': 'gw-e2e-' + uuid.uuid4().hex[:8], 'zone': ZONE},
        'serial': {'url': 'socket://127.0.0.1:{}'.format(simulator.server_address[1]),
                   'baud': 9600, 'timeout': 2},
        'mqtt': {'host': host, 'port': port, 'keepalive': 30},
    }
    gateway = sensor_gateway.SensorGateway(cfg)
    result = {}

    def run_gateway():
        result['published'] = gateway.run(max_readings=GATEWAY_READINGS)

    thread = threading.Thread(target=run_gateway, name='gateway-e2e')
    thread.daemon = True
    thread.start()

    try:
        reading_rows = []
        alert_rows = []
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            reading_rows = query(store, "SELECT * FROM sensor_readings WHERE zone = '{}'"
                                 .format(ZONE))
            alert_rows = query(store, "SELECT * FROM alerts WHERE zone = '{}' "
                                      "AND metric = 'temperature' AND state = 'raised'"
                               .format(ZONE))
            if len(reading_rows) >= MIN_READINGS and alert_rows:
                break
            time.sleep(0.25)

        assert len(reading_rows) >= MIN_READINGS
        assert {row['sensor'] for row in reading_rows} == {SENSOR_ID}
        assert {row['gateway'] for row in reading_rows} == {cfg['gateway']['id']}
        assert len(alert_rows) == 1
        assert alert_rows[0]['sensor'] == SENSOR_ID
        assert alert_rows[0]['value'] > 45.0
        assert alert_rows[0]['limit'] == 45.0

        thread.join(TIMEOUT)
        assert not thread.is_alive()
        assert result['published'] == GATEWAY_READINGS
        assert simulator.errors == []
    finally:
        processor.stop()
