# Industrial IoT Sensor Network

A small sensor pipeline for monitoring temperature, humidity and vibration across production zones on a factory floor. An Arduino sketch reads a DHT22 and an ADXL345 and writes CSV lines over serial; a gateway turns each line into an MQTT message; a processor subscribes to those messages, stores the readings in InfluxDB, raises edge-triggered threshold and vibration-trend alerts, and publishes them back to MQTT; Grafana graphs the readings, a 1-minute rollup and the alerts. Everything runs in Docker, with a TCP node simulator standing in for the Arduino hardware.

Personal project built on the 2017-era stack (Python 3.5, paho-mqtt 1.3, InfluxDB 1.3, Mosquitto 1.4, Grafana 4.6, Arduino)

## Status

**Implemented**

- Arduino sensor-node sketch: DHT22 and ADXL345 (±16 g full resolution) read every 5 s, CSV output, invalid DHT reads skipped, status LED — `arduino/sensor_node.ino`, `arduino/sensor_logic.h`; tested by `tests/arduino/test_sensor_node.cpp`.
- Reading protocol: CSV line parsing with comment lines ignored, range validation and the MQTT JSON payload — `src/readings.py`; tested by `tests/unit/test_readings.py`.
- Node simulator: TCP server emitting the sketch's line format with seeded `normal`, `overheat`, `humid`, `vibration-drift` and `dropout` profiles plus an optional `--noise` rate — `src/node_simulator.py`; tested by `tests/unit/test_node_simulator.py`.
- Sensor gateway: reads a pyserial URL, stamps readings with UTC time, gateway and zone, publishes QoS 1 to `sensors/<zone>/<sensor_id>/data` and reconnects with backoff — `src/sensor_gateway.py`; tested by `tests/unit/test_sensor_gateway.py` and `tests/integration/test_gateway_mqtt.py`.
- Configuration: INI files with environment-variable overrides — `src/config.py`, `config/gateway.ini`, `config/processor.ini`; tested by `tests/unit/test_config.py` and `tests/unit/test_gateway_config.py`.
- Alert engine: edge-triggered threshold alerts for temperature, humidity and vibration, and a rolling-mean vibration trend warning — `src/alerts.py`; tested by `tests/unit/test_alerts.py`.
- InfluxDB storage: database creation, `raw` (7 d, default) and `rollup` (52 w) retention policies, a 1-minute downsampling continuous query, reading and alert points — `src/influx_store.py`; tested by `tests/unit/test_influx_store.py` and `tests/integration/test_influx_store.py`.
- Data processor: subscribes to sensor topics, validates and stores readings, runs the alert engine, publishes alerts with QoS 2 and stores them, counts bad payloads — `src/data_processor.py`; tested by `tests/unit/test_data_processor.py` and `tests/integration/test_processor.py`.
- Multi-zone Compose stack: Mosquitto 1.4.12, InfluxDB 1.3.8, Grafana 4.6.3, two simulator and gateway pairs (`zone-a`, `zone-b`) and one processor — `docker-compose.yml`; tested end to end by `tests/integration/test_pipeline.py`.
- Broker and database config mounted into the images — `config/mosquitto.conf`, `config/influxdb.conf`; exercised by the integration tests above.
- Grafana dashboard with per-zone temperature, humidity and vibration graphs, the 1-minute rollup and an alerts table, loaded through the Grafana HTTP API — `grafana/dashboard.json`, `scripts/grafana_import.py`; tested by `tests/unit/test_dashboard.py` and `tests/integration/test_grafana_import.py`.
- Test harness: lint, unit, host-compiled sketch and container integration tests inside the `python:3.5.4-jessie` image — `Dockerfile`, `Makefile`; tested by `tests/unit/test_environment.py`.

**Not implemented / known limitations**

- Arduino sensor nodes, the serial link and the Raspberry Pi gateway are simulated (`src/node_simulator.py`, pyserial `socket://`, x86 gateway container); the sketch is tested on the host with fake Arduino/Wire/DHT headers and has not been flashed to a board in this repo.
- No physical Raspberry Pi deployment (Raspbian image, systemd unit, GPIO). The gateway is plain Python 3.5 but only runs in an x86 container here.
- The sketch is not compiled with avr-gcc or the Arduino IDE for Uno/Mega boards.
- No separate Python MQTT broker module; Mosquitto is the broker.
- No energy-saving or environmental optimisation; there is no HVAC or actuator control.
- No machine-learning or statistical failure prediction; the early warning is a fixed rolling-mean vibration threshold, not a learned model.
- No Grafana alerting or notification channels (email, Slack); alerts go to MQTT topics and InfluxDB only.
- No MQTT or InfluxDB authentication or TLS, and Grafana uses its default admin credentials. This is a local demo stack.
- No durable store-and-forward buffering on the gateway: readings are lost while the broker is unreachable beyond paho's in-memory queue, and the processor logs failed InfluxDB writes without retrying them.
- No gateway command topic; the old unhandled `commands` subscription was removed.
- Alert state lives in processor memory and resets on restart.
- Vibration magnitude assumes the ADXL345 is mounted Z-up (1 g is subtracted from Z).
- Grafana 4.x has no file provisioning, so the dashboard is loaded by a one-shot import script (`grafana-init` service).
- Mosquitto 1.4.12 and the Grafana 4.6.3 `.deb` are amd64-only, so those two services run under emulation on ARM hosts.
- Grafana is not the upstream Docker image: the official 4.6.3 `.deb` is installed on `debian:stretch-20171210` (`docker/grafana/Dockerfile`), because the upstream 4.x images can no longer be pulled.
- The continuous query firing is not tested (it needs a wall-clock minute); its existence and SQL are.

## Built with

- **Python 3.5.4** (`python:3.5.4-jessie` image) — paho-mqtt 1.3.0, influxdb 4.1.1, pyserial 3.4, requests 2.18.4, urllib3 1.22, chardet 3.0.4, idna 2.6, certifi 2017.11.5, python-dateutil 2.6.1, pytz 2017.3, six 1.11.0
- **Test tools** — pytest 3.3.1, py 1.5.2, pluggy 0.6.0, attrs 17.3.0, flake8 3.5.0, pyflakes 1.6.0, pycodestyle 2.3.1, mccabe 0.6.1
- **Arduino C++** — sketch for DHT22 and ADXL345 (Wire/I2C), host-compiled with g++ for tests
- **Services** — `eclipse-mosquitto:1.4.12`, `influxdb:1.3.8` (both pinned by digest), Grafana 4.6.3 built from the official `.deb` on `debian:stretch-20171210`

## Running it

Everything runs in Docker images from the project's era, so nothing needs installing locally beyond Docker.

```bash
make up                  # docker compose up -d --build: broker, InfluxDB, Grafana, two zones, processor
make smoke               # latest temperature and vibration per zone and sensor from InfluxDB
```

`make up` runs `$(COMPOSE) up -d --build` with `COMPOSE ?= docker compose` (use `make up COMPOSE=docker-compose` for the standalone binary). Host ports: Mosquitto 20583, InfluxDB 20586, Grafana 20530 (admin/admin, dashboard "Industrial IoT Floor"). `make down` stops the stack.

## Tests

```bash
make test                # runs the suite inside the period image
```

The suite covers unit tests, host-compiled tests of the Arduino sketch against fake headers, and integration tests against real Mosquitto, InfluxDB and Grafana containers; real hardware, serial timing and the continuous query actually executing are not covered.

## Layout

```
.dockerignore
.gitignore
Dockerfile
Makefile
README.md
arduino/
  sensor_logic.h
  sensor_node.ino
config/
  gateway.ini
  influxdb.conf
  mosquitto.conf
  processor.ini
conftest.py
docker-compose.yml
docker/
  grafana/
    Dockerfile
docs/
  IMPLEMENTATION_PLAN.md
  SPEC.md
grafana/
  dashboard.json
requirements-dev.txt
requirements.txt
scripts/
  __init__.py
  grafana_import.py
setup.cfg
src/
  alerts.py
  config.py
  data_processor.py
  influx_store.py
  node_simulator.py
  readings.py
  sensor_gateway.py
tests/
  __init__.py
  arduino/
    stubs/
      Arduino.h
      DHT.h
      Wire.h
    test_sensor_node.cpp
  fakes.py
  integration/
    __init__.py
    conftest.py
    test_gateway_mqtt.py
    test_grafana_import.py
    test_influx_store.py
    test_pipeline.py
    test_processor.py
  unit/
    __init__.py
    test_alerts.py
    test_config.py
    test_dashboard.py
    test_data_processor.py
    test_environment.py
    test_gateway_config.py
    test_influx_store.py
    test_node_simulator.py
    test_readings.py
    test_readme.py
    test_sensor_gateway.py
```
