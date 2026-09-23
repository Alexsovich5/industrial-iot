# Industrial IoT Sensor Network

Industrial IoT sensor network for manufacturing floor monitoring using Raspberry Pi gateways, Arduino sensor nodes, MQTT messaging, and InfluxDB time-series storage with Grafana dashboards.

Personal project, built to explore an MQTT sensor pipeline from Arduino to InfluxDB. It is not production software — see **Status** below for exactly what is and isn't implemented.

## Status

**Implemented**

- Arduino sensor-node sketch
- Raspberry Pi gateway publishing readings over MQTT into InfluxDB
- Mosquitto broker config and Compose stack

**Not implemented / known limitations**

- No separate data processor or broker module (the earlier README claimed these)
- No buffering or retry if InfluxDB is unreachable
- No tests; no calibration handling

## Built with

- **Python** — paho-mqtt, influxdb, pyserial

## Running it

```bash
pip install -r requirements.txt
python src/sensor_gateway.py
```

## Layout

```
arduino/
  sensor_node.ino
config/
  mosquitto.conf
docker-compose.yml
requirements.txt
src/
  sensor_gateway.py
```

