#!/usr/bin/env python3
"""
Raspberry Pi Sensor Gateway

Collects data from Arduino sensor nodes via serial,
publishes to MQTT broker, and stores in InfluxDB.
"""

import json
import time
import serial
import logging
import paho.mqtt.client as mqtt
from influxdb import InfluxDBClient
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('sensor_gateway')


class SensorGateway:
    """Raspberry Pi gateway for Arduino sensor network."""

    def __init__(self, config):
        self.gateway_id = config.get('gateway_id', 'gw-001')
        self.zone = config.get('zone', 'production-floor')

        # Serial connection to Arduino
        self.serial_port = config.get('serial_port', '/dev/ttyACM0')
        self.baud_rate = config.get('baud_rate', 9600)
        self.serial_conn = None

        # MQTT client
        self.mqtt_client = mqtt.Client(client_id=self.gateway_id)
        self.mqtt_host = config.get('mqtt_host', 'localhost')
        self.mqtt_port = config.get('mqtt_port', 1883)

        # InfluxDB client
        self.influx = InfluxDBClient(
            host=config.get('influxdb_host', 'localhost'),
            port=config.get('influxdb_port', 8086),
            database=config.get('influxdb_database', 'industrial_iot')
        )

        # Alert thresholds
        self.thresholds = config.get('thresholds', {
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
                self.serial_port, self.baud_rate, timeout=5
            )
            time.sleep(2)  # Arduino reset delay
            logger.info("Serial connected: %s", self.serial_port)
        except serial.SerialException as e:
            logger.error("Serial connection failed: %s", e)
            raise

    def _connect_mqtt(self):
        """Connect to MQTT broker."""
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
        self.mqtt_client.loop_start()

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(f"gateways/{self.gateway_id}/commands")
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
                line = self.serial_conn.readline().decode('utf-8').strip()
                if not line:
                    continue

                reading = self._parse_reading(line)
                if reading:
                    self._publish_mqtt(reading)
                    self._store_influxdb(reading)
                    self._check_thresholds(reading)

            except Exception as e:
                logger.error("Processing error: %s", e)
                time.sleep(1)

    def _parse_reading(self, raw_line):
        """Parse Arduino sensor reading (CSV format)."""
        try:
            parts = raw_line.split(',')
            if len(parts) < 4:
                return None

            return {
                'sensor_id': parts[0].strip(),
                'temperature': float(parts[1]),
                'humidity': float(parts[2]),
                'vibration': float(parts[3]),
                'timestamp': datetime.utcnow().isoformat()
            }
        except (ValueError, IndexError) as e:
            logger.debug("Parse error: %s - %s", raw_line, e)
            return None

    def _publish_mqtt(self, reading):
        """Publish sensor reading to MQTT."""
        topic = f"sensors/{self.zone}/{reading['sensor_id']}/data"
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
            alerts.append(f"High temperature: {reading['temperature']}C")
        if reading['humidity'] > self.thresholds['humidity_max']:
            alerts.append(f"High humidity: {reading['humidity']}%")
        if reading['vibration'] > self.thresholds['vibration_max']:
            alerts.append(f"High vibration: {reading['vibration']}g")

        for alert_msg in alerts:
            alert = {
                'gateway': self.gateway_id,
                'sensor': reading['sensor_id'],
                'zone': self.zone,
                'message': alert_msg,
                'timestamp': reading['timestamp']
            }
            topic = f"alerts/{self.zone}/{reading['sensor_id']}"
            self.mqtt_client.publish(topic, json.dumps(alert), qos=2)
            logger.warning("ALERT: %s", alert_msg)


if __name__ == '__main__':
    config = {
        'gateway_id': 'gw-001',
        'zone': 'production-floor-A',
        'serial_port': '/dev/ttyACM0',
        'mqtt_host': 'localhost',
        'influxdb_host': 'localhost',
        'influxdb_database': 'industrial_iot'
    }
    gateway = SensorGateway(config)
    gateway.start()
