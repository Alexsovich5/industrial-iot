"""Gateway fed by an in-process node simulator, publishing to real Mosquitto."""

import queue
import threading
import time
import uuid

import paho.mqtt.client as mqtt

import node_simulator
import readings
import sensor_gateway


def start_subscriber(host, port, topic):
    received = queue.Queue()
    subscribed = threading.Event()
    client = mqtt.Client(client_id='it-sub-' + uuid.uuid4().hex[:8])

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(topic, qos=1)

    def on_subscribe(client, userdata, mid, granted_qos):
        subscribed.set()

    def on_message(client, userdata, msg):
        received.put((msg.topic, msg.qos, msg.payload.decode('utf-8')))

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    client.connect(host, port, keepalive=30)
    client.loop_start()
    assert subscribed.wait(10), 'subscription to {} not acknowledged'.format(topic)
    return client, received


def test_gateway_publishes_simulated_readings_to_mosquitto(mqtt_host):
    host, port = mqtt_host
    zone = 'zone-it-' + uuid.uuid4().hex[:8]
    subscriber, received = start_subscriber(host, port, 'sensors/#')

    server = node_simulator.serve(
        '127.0.0.1', 0, lambda: node_simulator.generate('normal', 'SN-001', 5), 0.05)
    cfg = {
        'gateway': {'id': 'gw-it', 'zone': zone},
        'serial': {'url': 'socket://127.0.0.1:{}'.format(server.server_address[1]),
                   'baud': 9600, 'timeout': 1},
        'mqtt': {'host': host, 'port': port, 'keepalive': 30},
    }
    gateway = sensor_gateway.SensorGateway(cfg)
    result = {}
    worker = threading.Thread(target=lambda: result.update(count=gateway.run(max_readings=5)))
    worker.daemon = True
    worker.start()

    payloads = []
    try:
        deadline = time.time() + 10
        while len(payloads) < 3 and time.time() < deadline:
            try:
                topic, qos, text = received.get(timeout=0.5)
            except queue.Empty:
                continue
            data = readings.from_payload(text)
            if data['zone'] != zone:
                continue
            assert topic == 'sensors/{}/SN-001/data'.format(zone)
            assert qos == 1
            assert data['gateway'] == 'gw-it'
            assert data['timestamp'].endswith('Z')
            reading = readings.Reading(data['sensor_id'], data['temperature'],
                                       data['humidity'], data['vibration'])
            assert readings.validate(reading) == []
            payloads.append(data)
        worker.join(10)
    finally:
        subscriber.loop_stop()
        subscriber.disconnect()
        server.shutdown()
        server.server_close()

    assert len(payloads) >= 3
    assert result.get('count') == 5
