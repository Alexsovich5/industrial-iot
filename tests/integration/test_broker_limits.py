"""The Mosquitto config drops messages above the configured size limit."""

import queue
import threading
import time
import uuid

import paho.mqtt.client as mqtt


def connect(host, port, prefix):
    client = mqtt.Client(client_id='{}-{}'.format(prefix, uuid.uuid4().hex[:8]))
    connected = threading.Event()
    client.on_connect = lambda c, u, f, rc: rc == 0 and connected.set()
    client.connect(host, port, keepalive=30)
    client.loop_start()
    assert connected.wait(10), 'broker did not accept the connection'
    return client


def test_broker_drops_oversized_messages(mqtt_host):
    host, port = mqtt_host
    topic = 'it-limits/{}'.format(uuid.uuid4().hex[:8])
    received = queue.Queue()
    subscribed = threading.Event()

    subscriber = connect(host, port, 'it-limit-sub')
    subscriber.on_message = lambda c, u, msg: received.put(len(msg.payload))
    subscriber.on_subscribe = lambda c, u, mid, granted: subscribed.set()
    subscriber.subscribe(topic, qos=0)
    assert subscribed.wait(10)

    publisher = connect(host, port, 'it-limit-pub')
    try:
        publisher.publish(topic, b'x' * 65536, qos=0)
        publisher.publish(topic, b'y' * 100, qos=0)
        sizes = []
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                sizes.append(received.get(timeout=0.5))
            except queue.Empty:
                if sizes:
                    break
    finally:
        for client in (publisher, subscriber):
            client.loop_stop()
            client.disconnect()

    assert sizes == [100]
