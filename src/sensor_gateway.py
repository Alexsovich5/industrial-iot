#!/usr/bin/env python3
"""
Raspberry Pi Sensor Gateway

Collects data from Arduino sensor nodes via serial,
publishes to MQTT broker, and stores in InfluxDB.
"""

import argparse
import json
import time
import serial
import logging
import paho.mqtt.client as mqtt
import config
import readings
from influxdb import InfluxDBClient
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('sensor_gateway')


class SensorGateway:
    """Raspberry Pi gateway for Arduino sensor network."""

    def __init__(self, cfg):
        gateway = cfg.get('gateway', {})
        serial_cfg = cfg.get('serial', {})
        mqtt_cfg = cfg.get('mqtt', {})
        influx_cfg = cfg.get('influxdb', {})

        self.gateway_id = gateway.get('id', 'gw-001')
        self.zone = gateway.get('zone', 'production-floor')

        # Serial connection to Arduino
        self.serial_port = serial_cfg.get('url', '/dev/ttyACM0')
        self.baud_rate = serial_cfg.get('baud', 9600)
        self.serial_timeout = serial_cfg.get('timeout', 5)
        self.serial_conn = None

        # MQTT client
        self.mqtt_client = mqtt.Client(client_id=self.gateway_id)
        self.mqtt_host = mqtt_cfg.get('host', 'localhost')
        self.mqtt_port = mqtt_cfg.get('port', 1883)
        self.mqtt_keepalive = mqtt_cfg.get('keepalive', 60)

        # InfluxDB client
        self.influx = InfluxDBClient(
            host=influx_cfg.get('host', 'localhost'),
            port=influx_cfg.get('port', 8086),
            database=influx_cfg.get('database', 'industrial_iot')
        )

        # Alert thresholds
        self.thresholds = cfg.get('thresholds', {
            'temperature_max': 45.0,
            'humidity_max': 80.0,
            'vibration_max': 5.0
        })

    def start(self):
        """Start the sensor gateway."""
        logger.info("Starting sensor gateway: %s (zone: %s)",
                    self.gateway_id, self.zone)

        self._connect_serial()
        self._connect_mqtt()
        self._ensure_database()
        self._run()

    def _connect_serial(self):
        """Connect to Arduino via serial."""
        try:
            self.serial_conn = serial.Serial(
                self.serial_port, self.baud_rate, timeout=self.serial_timeout
            )
            time.sleep(2)  # Arduino reset delay
            logger.info("Serial connected: %s", self.serial_port)
        except serial.SerialException as e:
            logger.error("Serial connection failed: %s", e)
            raise

    def _connect_mqtt(self):
        """Connect to MQTT broker."""
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port,
                                 keepalive=self.mqtt_keepalive)
        self.mqtt_client.loop_start()

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe("gateways/{}/commands".format(self.gateway_id))
        else:
            logger.error("MQTT connection failed: rc=%d", rc)

    def _ensure_database(self):
        """Ensure InfluxDB database exists."""
        databases = self.influx.get_list_database()
        if not any(db['name'] == 'industrial_iot' for db in databases):
            self.influx.create_database('industrial_iot')
            logger.info("Created InfluxDB database: industrial_iot")

    def _run(self):
        """Main data collection loop."""
        while True:
            try:
                line = self.serial_conn.readline().decode('utf-8')
                parsed = readings.parse_line(line)
                if parsed is None:
                    continue

                reading = dict(parsed._asdict())
                reading['timestamp'] = datetime.utcnow().isoformat() + 'Z'
                self._publish_mqtt(reading)
                self._store_influxdb(reading)
                self._check_thresholds(reading)

            except Exception as e:
                logger.error("Processing error: %s", e)
                time.sleep(1)

    def _publish_mqtt(self, reading):
        """Publish sensor reading to MQTT."""
        topic = "sensors/{}/{}/data".format(self.zone, reading['sensor_id'])
        payload = json.dumps(reading)
        self.mqtt_client.publish(topic, payload, qos=1)

    def _store_influxdb(self, reading):
        """Store reading in InfluxDB."""
        point = {
            "measurement": "sensor_readings",
            "tags": {
                "gateway": self.gateway_id,
                "zone": self.zone,
                "sensor": reading['sensor_id']
            },
            "fields": {
                "temperature": reading['temperature'],
                "humidity": reading['humidity'],
                "vibration": reading['vibration']
            }
        }
        self.influx.write_points([point])

    def _check_thresholds(self, reading):
        """Check readings against alert thresholds."""
        alerts = []
        if reading['temperature'] > self.thresholds['temperature_max']:
            alerts.append("High temperature: {}C".format(reading['temperature']))
        if reading['humidity'] > self.thresholds['humidity_max']:
            alerts.append("High humidity: {}%".format(reading['humidity']))
        if reading['vibration'] > self.thresholds['vibration_max']:
            alerts.append("High vibration: {}g".format(reading['vibration']))

        for alert_msg in alerts:
            alert = {
                'gateway': self.gateway_id,
                'sensor': reading['sensor_id'],
                'zone': self.zone,
                'message': alert_msg,
                'timestamp': reading['timestamp']
            }
            topic = "alerts/{}/{}".format(self.zone, reading['sensor_id'])
            self.mqtt_client.publish(topic, json.dumps(alert), qos=2)
            logger.warning("ALERT: %s", alert_msg)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Read sensor-node lines from serial and publish them.')
    parser.add_argument('--config', default='config/gateway.ini',
                        help='path to the gateway INI file')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    gateway = SensorGateway(config.load(args.config))
    gateway.start()


if __name__ == '__main__':
    main()
