#!/usr/bin/env python3
"""
Sensor gateway: serial-to-MQTT bridge.

Reads ``SENSOR_ID,TEMP,HUMIDITY,VIBRATION`` lines from a sensor node over
any pyserial URL (``/dev/ttyACM0`` on hardware, ``socket://host:port`` for
the node simulator, ``loop://`` in tests), stamps each valid reading with
UTC time, gateway id and zone, and publishes it with QoS 1 to
``sensors/<zone>/<sensor_id>/data``. Storage and alerting are done by the
data processor. If the serial link fails, the gateway reconnects with
exponential backoff.

Serial reads are bounded: a line split by a read timeout is joined with
its remainder before parsing, and a line longer than ``MAX_LINE_BYTES``
is dropped whole.
"""

import argparse
import logging
import time
from datetime import datetime

import paho.mqtt.client as mqtt
import serial

import config
import readings

logger = logging.getLogger('sensor_gateway')

DATA_QOS = 1
ARDUINO_RESET_DELAY = 2
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 30.0
PUBLISH_FLUSH_TIMEOUT = 5.0
# Sketch lines are under 64 bytes; anything this long is not a reading.
MAX_LINE_BYTES = 256


def backoff_delays(initial=INITIAL_BACKOFF, maximum=MAX_BACKOFF):
    """Yield reconnect delays forever: initial, doubled each time, capped at maximum."""
    delay = initial
    while True:
        yield delay
        delay = min(delay * 2, maximum)


def data_topic(zone, sensor_id):
    return 'sensors/{}/{}/data'.format(zone, sensor_id)


class SensorGateway(object):
    """Bridge one serial-attached sensor node to the MQTT broker."""

    def __init__(self, cfg, mqtt_factory=mqtt.Client,
                 serial_factory=serial.serial_for_url,
                 clock=datetime.utcnow, sleep=time.sleep):
        gateway = cfg.get('gateway', {})
        serial_cfg = cfg.get('serial', {})
        mqtt_cfg = cfg.get('mqtt', {})

        self.gateway_id = gateway.get('id', 'gw-001')
        self.zone = gateway.get('zone', 'production-floor')
        for label, value in (('gateway id', self.gateway_id), ('zone', self.zone)):
            if not readings.valid_name(value):
                raise ValueError('{} {!r} must be 1-64 characters from '
                                 'A-Z a-z 0-9 _ . -'.format(label, value))

        self.serial_url = serial_cfg.get('url', '/dev/ttyACM0')
        self.baud_rate = serial_cfg.get('baud', 9600)
        self.serial_timeout = serial_cfg.get('timeout', 5)
        self.serial_factory = serial_factory
        self.serial_conn = None

        self.mqtt_host = mqtt_cfg.get('host', 'localhost')
        self.mqtt_port = mqtt_cfg.get('port', 1883)
        self.mqtt_keepalive = mqtt_cfg.get('keepalive', 60)
        self.mqtt_client = mqtt_factory(client_id=self.gateway_id)
        self.mqtt_client.on_connect = self._on_mqtt_connect

        self.clock = clock
        self.sleep = sleep
        self._pending = []
        self._read_backoff = None
        self._partial = bytearray()
        self._discarding = False

    # Serial

    def _open_serial(self):
        """Open the serial URL, retrying with backoff until it succeeds."""
        delays = backoff_delays()
        while True:
            try:
                conn = self.serial_factory(self.serial_url, baudrate=self.baud_rate,
                                           timeout=self.serial_timeout)
            except (serial.SerialException, OSError) as exc:
                delay = next(delays)
                logger.warning('Serial open %s failed (%s); retrying in %.1fs',
                               self.serial_url, exc, delay)
                self.sleep(delay)
                continue
            if self.serial_url.startswith('/dev/'):
                # Opening the USB port resets the Arduino; give it time to boot.
                self.sleep(ARDUINO_RESET_DELAY)
            logger.info('Serial connected: %s', self.serial_url)
            return conn

    def _close_serial(self):
        if self.serial_conn is not None:
            try:
                self.serial_conn.close()
            except Exception:
                logger.debug('ignoring error while closing serial port', exc_info=True)
            self.serial_conn = None

    def _reconnect_serial(self, error):
        if self._read_backoff is None:
            self._read_backoff = backoff_delays()
        delay = next(self._read_backoff)
        logger.warning('Serial error on %s (%s); reconnecting in %.1fs',
                       self.serial_url, error, delay)
        self._close_serial()
        self.sleep(delay)
        self.serial_conn = self._open_serial()
        self._partial = bytearray()
        self._discarding = False

    def _read_line(self):
        """Read once from serial and return a complete line, or None.

        A chunk without a trailing newline (read timeout) is kept until the
        rest of the line arrives. The buffer never grows past
        ``MAX_LINE_BYTES``: an overlong line is dropped up to its newline.
        """
        chunk = self.serial_conn.readline(MAX_LINE_BYTES - len(self._partial))
        if not chunk:
            return None
        if self._discarding:
            if chunk.endswith(b'\n'):
                self._discarding = False
            return None
        self._partial.extend(chunk)
        if self._partial.endswith(b'\n'):
            line = bytes(self._partial)
            self._partial = bytearray()
            return line
        if len(self._partial) >= MAX_LINE_BYTES:
            logger.warning('Dropping serial line longer than %d bytes on %s',
                           MAX_LINE_BYTES, self.serial_url)
            self._partial = bytearray()
            self._discarding = True
        return None

    # MQTT

    def _connect_mqtt(self):
        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port,
                                 keepalive=self.mqtt_keepalive)
        self.mqtt_client.loop_start()

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info('Connected to MQTT broker %s:%s', self.mqtt_host, self.mqtt_port)
        else:
            logger.error('MQTT connection failed: rc=%d', rc)

    def _flush_and_disconnect(self):
        """Give QoS 1 messages still in flight a short time to be acknowledged."""
        deadline = time.time() + PUBLISH_FLUSH_TIMEOUT
        for info in self._pending:
            while not info.is_published() and time.time() < deadline:
                time.sleep(0.05)
        self._pending = []
        self.mqtt_client.disconnect()
        self.mqtt_client.loop_stop()

    # Readings

    def process_line(self, line):
        """Publish one serial line if it is a valid reading; return True if published."""
        reading = readings.parse_line(line)
        if reading is None:
            if line.strip() and not line.strip().startswith('#'):
                logger.debug('Ignoring unparseable line: %r', line)
            return False
        problems = readings.validate(reading)
        if problems:
            logger.warning('Dropping out-of-range reading from %s: %s',
                           reading.sensor_id, '; '.join(problems))
            return False
        payload = readings.to_payload(reading, self.gateway_id, self.zone, self.clock())
        info = self.mqtt_client.publish(data_topic(self.zone, reading.sensor_id),
                                        payload, qos=DATA_QOS)
        self._pending = [i for i in self._pending if not i.is_published()]
        self._pending.append(info)
        return True

    def run(self, max_readings=None):
        """Bridge serial to MQTT until ``max_readings`` are published (or forever).

        Returns the number of readings published.
        """
        logger.info('Starting sensor gateway %s (zone %s) on %s',
                    self.gateway_id, self.zone, self.serial_url)
        self._connect_mqtt()
        published = 0
        try:
            self.serial_conn = self._open_serial()
            while max_readings is None or published < max_readings:
                try:
                    raw = self._read_line()
                except (serial.SerialException, OSError) as exc:
                    self._reconnect_serial(exc)
                    continue
                if raw is None:
                    continue
                self._read_backoff = None
                if self.process_line(raw.decode('utf-8', 'replace')):
                    published += 1
        finally:
            self._close_serial()
            self._flush_and_disconnect()
        return published


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Read sensor-node lines from serial and publish them to MQTT.')
    parser.add_argument('--config', default='config/gateway.ini',
                        help='path to the gateway INI file')
    parser.add_argument('--max-readings', type=int, default=None,
                        help='stop after publishing this many readings')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(name)s %(levelname)s %(message)s')
    gateway = SensorGateway(config.load(args.config))
    gateway.run(max_readings=args.max_readings)


if __name__ == '__main__':
    main()
