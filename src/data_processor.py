#!/usr/bin/env python3
"""
Data processor: MQTT sensor topics to InfluxDB and alert topics.

Subscribes to ``sensors/+/+/data``, parses and range-checks each payload,
writes valid readings to InfluxDB through ``InfluxStore`` and runs them
through the ``AlertEngine``. Each alert event is published with QoS 2 to
``alerts/<zone>/<sensor_id>`` and written to the ``alerts`` measurement.

Bad payloads are logged and counted as rejected. InfluxDB write errors
and any other error while handling a message are logged and counted;
they never stop the MQTT loop.
"""

import argparse
import collections
import json
import logging
import time

import paho.mqtt.client as mqtt
import requests
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError

import alerts
import config
import influx_store
import readings

logger = logging.getLogger('data_processor')

DATA_TOPIC = 'sensors/+/+/data'
DATA_QOS = 1
ALERT_QOS = 2

SCHEMA_INITIAL_DELAY = 1.0
SCHEMA_MAX_DELAY = 30.0

WRITE_ERRORS = (InfluxDBClientError, InfluxDBServerError,
                requests.exceptions.RequestException, OSError)

ALERT_FIELDS = ('zone', 'sensor_id', 'gateway', 'kind', 'metric', 'state',
                'value', 'limit', 'message', 'timestamp')


def alert_topic(zone, sensor_id):
    return 'alerts/{}/{}'.format(zone, sensor_id)


def alert_payload(event):
    """Serialise an AlertEvent to the JSON body published on the alert topic."""
    return json.dumps(collections.OrderedDict(
        (field, getattr(event, field)) for field in ALERT_FIELDS))


def _topic_parts(topic):
    """Return (zone, sensor_id) from ``sensors/<zone>/<sensor_id>/data``, or None."""
    parts = topic.split('/')
    if len(parts) == 4 and parts[0] == 'sensors' and parts[3] == 'data':
        return parts[1], parts[2]
    return None


class DataProcessor(object):
    """Route data-topic messages into InfluxDB and alert events onto MQTT."""

    def __init__(self, cfg, mqtt_client, store, engine):
        mqtt_cfg = cfg.get('mqtt', {})
        self.mqtt_host = mqtt_cfg.get('host', 'localhost')
        self.mqtt_port = mqtt_cfg.get('port', 1883)
        self.mqtt_keepalive = mqtt_cfg.get('keepalive', 60)

        self.mqtt_client = mqtt_client
        self.store = store
        self.engine = engine
        self.stats = {'received': 0, 'stored': 0, 'rejected': 0,
                      'alerts': 0, 'write_errors': 0, 'errors': 0}

        mqtt_client.on_connect = self.on_connect
        mqtt_client.on_message = self.on_message

    # MQTT

    def connect(self):
        """Connect to the broker and start paho's network thread."""
        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port,
                                 keepalive=self.mqtt_keepalive)
        self.mqtt_client.loop_start()

    def stop(self):
        self.mqtt_client.disconnect()
        self.mqtt_client.loop_stop()

    def on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            logger.error('MQTT connection failed: rc=%d', rc)
            return
        logger.info('Connected to MQTT broker %s:%s', self.mqtt_host, self.mqtt_port)
        # Subscribing here re-subscribes after every reconnect.
        client.subscribe(DATA_TOPIC, qos=DATA_QOS)

    def on_message(self, client, userdata, msg):
        self.stats['received'] += 1
        # paho 1.3 does not catch exceptions raised in callbacks: one would
        # end loop_forever and stop the processor.
        try:
            self._handle(msg)
        except Exception:
            self.stats['errors'] += 1
            logger.exception('Unexpected error handling message on %s', msg.topic)

    def _handle(self, msg):
        data = self._parse(msg)
        if data is None:
            self.stats['rejected'] += 1
            return

        try:
            self.store.write_reading(data)
        except WRITE_ERRORS as exc:
            self.stats['write_errors'] += 1
            logger.error('InfluxDB write failed for %s/%s reading: %s',
                         data['zone'], data['sensor_id'], exc)
        else:
            self.stats['stored'] += 1

        for event in self.engine.evaluate(data):
            self._emit_alert(event)

    # Helpers

    def _parse(self, msg):
        try:
            text = msg.payload.decode('utf-8')
            data = readings.from_payload(text)
        except ValueError as exc:
            logger.warning('Rejected payload on %s: %s', msg.topic, exc)
            return None

        reading = readings.Reading(data['sensor_id'], data['temperature'],
                                   data['humidity'], data['vibration'])
        problems = readings.validate(reading)
        if problems:
            logger.warning('Rejected out-of-range reading on %s: %s',
                           msg.topic, '; '.join(problems))
            return None

        expected = _topic_parts(msg.topic)
        if expected != (data['zone'], data['sensor_id']):
            logger.warning('Topic %s does not match payload zone %s sensor %s; '
                           'using the payload', msg.topic, data['zone'], data['sensor_id'])
        return data

    def _emit_alert(self, event):
        logger.info('Alert %s %s/%s: %s', event.state, event.zone,
                    event.sensor_id, event.message)
        self.mqtt_client.publish(alert_topic(event.zone, event.sensor_id),
                                 alert_payload(event), qos=ALERT_QOS)
        self.stats['alerts'] += 1
        try:
            self.store.write_alert(event)
        except WRITE_ERRORS as exc:
            self.stats['write_errors'] += 1
            logger.error('InfluxDB write failed for %s/%s alert: %s',
                         event.zone, event.sensor_id, exc)


def ensure_schema_with_retry(store, sleep=time.sleep, attempts=None,
                             initial=SCHEMA_INITIAL_DELAY, maximum=SCHEMA_MAX_DELAY):
    """Call ``store.ensure_schema()`` until it succeeds.

    Waits ``initial`` seconds after the first failure, doubling up to
    ``maximum``. With ``attempts`` set, the last error is re-raised after
    that many failed calls.
    """
    delay = initial
    attempt = 0
    while True:
        attempt += 1
        try:
            store.ensure_schema()
            return
        except WRITE_ERRORS as exc:
            if attempts is not None and attempt >= attempts:
                raise
            logger.warning('InfluxDB not ready (%s); retrying in %.1fs', exc, delay)
            sleep(delay)
            delay = min(delay * 2, maximum)


def build(cfg, mqtt_factory=mqtt.Client, influx_factory=InfluxDBClient):
    """Create a DataProcessor and its clients from a loaded configuration."""
    mqtt_cfg = cfg.get('mqtt', {})
    influx_cfg = cfg.get('influxdb', {})
    trend = cfg.get('trend', {})

    mqtt_client = mqtt_factory(client_id=mqtt_cfg.get('client_id', 'processor'))
    influx_client = influx_factory(influx_cfg.get('host', 'localhost'),
                                   influx_cfg.get('port', 8086), timeout=10)
    store = influx_store.InfluxStore(influx_client,
                                     influx_cfg.get('database', 'industrial_iot'))
    engine = alerts.AlertEngine(cfg.get('thresholds', {}), trend.get('window', 12),
                                trend.get('vibration_warn', 2.0))
    return DataProcessor(cfg, mqtt_client, store, engine)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Store MQTT sensor readings in InfluxDB and publish alerts.')
    parser.add_argument('--config', default='config/processor.ini',
                        help='path to the processor INI file')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(name)s %(levelname)s %(message)s')
    processor = build(config.load(args.config))
    ensure_schema_with_retry(processor.store)
    # connect_async defers the first connection to loop_forever, which keeps
    # retrying it while the broker is still starting.
    processor.mqtt_client.connect_async(processor.mqtt_host, processor.mqtt_port,
                                        keepalive=processor.mqtt_keepalive)
    processor.mqtt_client.loop_forever(retry_first_connection=True)


if __name__ == '__main__':
    main()
