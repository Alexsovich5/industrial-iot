"""DataProcessor connected to real Mosquitto and InfluxDB with a throwaway database."""

import datetime
import json
import queue
import threading
import time
import uuid

import paho.mqtt.client as mqtt
import pytest
from influxdb import InfluxDBClient

import alerts
import data_processor
import influx_store
import readings
from tests.integration.test_gateway_mqtt import start_subscriber

THRESHOLDS = {'temperature_max': 45.0, 'humidity_max': 80.0, 'vibration_max': 5.0}


@pytest.fixture
def store(influx_host):
    host, port = influx_host
    database = 'test_' + uuid.uuid4().hex
    client = InfluxDBClient(host=host, port=port, timeout=10)
    store = influx_store.InfluxStore(client, database)
    store.ensure_schema()
    yield store
    client.drop_database(database)


def start_processor(host, port, store):
    client = mqtt.Client(client_id='it-proc-' + uuid.uuid4().hex[:8])
    subscribed = threading.Event()
    engine = alerts.AlertEngine(THRESHOLDS, 12, 2.0)
    cfg = {'mqtt': {'host': host, 'port': port, 'keepalive': 30}}
    processor = data_processor.DataProcessor(cfg, client, store, engine)
    client.on_subscribe = lambda c, userdata, mid, granted: subscribed.set()
    processor.connect()
    assert subscribed.wait(10), 'processor subscription not acknowledged'
    return processor


def wait_for_rows(store, query, count, timeout=10):
    deadline = time.time() + timeout
    rows = []
    while time.time() < deadline:
        rows = list(store.client.query(query, database=store.database).get_points())
        if len(rows) >= count:
            return rows
        time.sleep(0.25)
    return rows


def test_processor_stores_readings_and_publishes_alert(mqtt_host, store):
    host, port = mqtt_host
    zone = 'zone-it-' + uuid.uuid4().hex[:8]
    alert_sub, alert_queue = start_subscriber(host, port, 'alerts/#')
    processor = start_processor(host, port, store)
    publisher = mqtt.Client(client_id='it-pub-' + uuid.uuid4().hex[:8])
    publisher.connect(host, port, keepalive=30)
    publisher.loop_start()

    try:
        base = datetime.datetime.utcnow().replace(microsecond=0) - datetime.timedelta(minutes=1)
        temperatures = [22.0, 22.5, 23.0, 50.0]
        for i, temperature in enumerate(temperatures):
            reading = readings.Reading('SN-001', temperature, 40.0, 0.1)
            text = readings.to_payload(reading, 'gw-it', zone,
                                       base + datetime.timedelta(seconds=i))
            info = publisher.publish('sensors/{}/SN-001/data'.format(zone), text, qos=1)
            info.wait_for_publish()

        rows = wait_for_rows(store, 'SELECT * FROM sensor_readings', 4)
        assert len(rows) == 4
        assert sorted(row['temperature'] for row in rows) == temperatures
        assert {row['zone'] for row in rows} == {zone}

        alert_rows = wait_for_rows(store, 'SELECT * FROM alerts', 1)
        assert len(alert_rows) == 1
        assert alert_rows[0]['state'] == 'raised'
        assert alert_rows[0]['metric'] == 'temperature'
        assert alert_rows[0]['value'] == 50.0

        events = []
        deadline = time.time() + 10
        while not events and time.time() < deadline:
            try:
                topic, qos, text = alert_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            body = json.loads(text)
            if body['zone'] == zone:
                events.append((topic, qos, body))
        assert len(events) == 1
        topic, qos, body = events[0]
        assert topic == 'alerts/{}/SN-001'.format(zone)
        assert body['state'] == 'raised'
        assert body['message'] == 'temperature 50.0 above 45.0'
        deadline = time.time() + 5
        while processor.stats['alerts'] < 1 and time.time() < deadline:
            time.sleep(0.05)
        assert processor.stats['received'] == 4
        assert processor.stats['stored'] == 4
        assert processor.stats['alerts'] == 1
    finally:
        publisher.loop_stop()
        publisher.disconnect()
        alert_sub.loop_stop()
        alert_sub.disconnect()
        processor.stop()
