# industrial-iot: Specification

Target period: August to December 2017. Every dependency is pinned to a release from on or before 2017-12-31.

## Problem

A factory floor needs continuous readings of temperature, humidity and vibration from several production zones. Each reading should end up in one time-series store that can be graphed, and operators should get an early warning when a machine drifts toward a failure threshold.

The system is a small pipeline:

- Arduino sensor nodes read the sensors and write CSV lines over a serial link.
- A gateway (a Raspberry Pi in the original concept) turns those lines into MQTT messages.
- A processor subscribes to MQTT, stores the readings in InfluxDB 1.3 and raises alerts.
- Grafana 4.x shows the data.

This repo rebuilds that pipeline as a working, tested solo project. It runs entirely in Docker, and simulators stand in for the hardware.

## In scope

1. **Arduino sensor-node sketch** (`arduino/sensor_node.ino`). It reads a DHT22 (temperature and humidity) and an ADXL345 over I2C (vibration magnitude in g). In `setup()` it writes the ADXL345 DATA_FORMAT register (0x31) to 0x0B (FULL_RES, ±16 g), so the range matches the validation limits below and the 4 mg/LSB scale stays valid. Every 5 s it writes `SENSOR_ID,TEMP,HUMIDITY,VIBRATION` to the serial port. It skips invalid DHT reads and blinks the status LED. The pure logic sits in `arduino/sensor_logic.h`, and host-side unit tests check it.
2. **Reading protocol and validation** (`src/readings.py`). This module parses the node's CSV lines and ignores `#` comment lines. It range-checks values against sensor limits and serialises them to the MQTT JSON payload.
3. **Node simulator** (`src/node_simulator.py`). A TCP server that sends exactly the sketch's line format. It uses seeded, deterministic profiles: `normal`, `overheat`, `humid`, `vibration-drift` and `dropout`. `dropout` skips whole intervals (no line at all), which is what the sketch does on a failed (NaN) DHT read. A separate, explicitly labelled `--noise RATE` option injects garbage and blank lines to model serial-line noise; the real sketch never emits those. Each TCP connection gets its own line iterator. It stands in for the Arduino and serial cable.
4. **Sensor gateway** (`src/sensor_gateway.py`). It reads lines from a pyserial URL: `/dev/ttyACM0` on real hardware, or `socket://host:port` for the simulator. It stamps each reading with UTC time, gateway ID and zone, then publishes it with QoS 1 to `sensors/<zone>/<sensor_id>/data`. If the serial link drops, it reconnects with backoff.
5. **Configuration** (`src/config.py`, `config/*.ini`). INI files are read with the stdlib `configparser`. Documented environment variables override them, which is how Compose sets them per service.
6. **Alert engine** (`src/alerts.py`). This covers the rule-based part of the README's "predictive maintenance alerts":
   - Threshold alerts for `temperature_max`, `humidity_max` and `vibration_max`.
   - An early-warning *trend* alert when the rolling mean of vibration over the last N readings passes `vibration_warn`.
   - Alerts are edge-triggered. A rule raises once when it first fires and clears once when it recovers, with no flood of repeats.
7. **InfluxDB storage** (`src/influx_store.py`):
   - Creates the database if missing.
   - Sets up two retention policies: `raw` (7 d, default) and `rollup` (52 w).
   - Adds a continuous query that downsamples to 1-minute means in `rollup.sensor_readings_1m`. This covers the README's "historical analytics".
   - Writes `sensor_readings` and `alerts` points.
8. **Data processor** (`src/data_processor.py`). It subscribes to `sensors/+/+/data`, validates payloads and writes them to InfluxDB. It runs the alert engine, publishes alert events with QoS 2 to `alerts/<zone>/<sensor_id>` and stores them in InfluxDB. It logs and counts bad payloads instead of crashing.
9. **Multi-zone Compose stack** (`docker-compose.yml`):
   - Mosquitto 1.4.12, InfluxDB 1.3.8 and Grafana 4.6.3. Grafana is built locally (`docker/grafana/Dockerfile`) from the official 4.6.3 `.deb` on `debian:stretch-20171210`, because every Grafana 4.x image on Docker Hub is a schema-1 manifest that current Docker cannot pull.
   - Two simulator and gateway pairs (`zone-a`, `zone-b`) and one processor.
   - This covers "real-time floor monitoring across production zones".
10. **Broker and database config** (`config/mosquitto.conf`, `config/influxdb.conf`), mounted into the period images.
11. **Grafana dashboard** (`grafana/dashboard.json`, schemaVersion 14, InfluxDB datasource). It has panels for temperature, humidity and vibration per zone and sensor, the 1-minute rollup, and an alerts table. `scripts/grafana_import.py` loads the datasource and dashboard through the Grafana 4.6 HTTP API, because file provisioning only arrived in Grafana 5.0. The datasource is named `industrial_iot` (the `--datasource-name` default), and every panel in `dashboard.json` references that exact name.
12. **Test harness**. `make test` runs flake8, pytest unit tests, the host-compiled Arduino sketch tests and integration tests against the real Mosquitto, InfluxDB and Grafana containers. All of it runs inside the `python:3.5.4-jessie` image.

## Out of scope

The left column lists each item from the original README.

| Item | Reason |
|---|---|
| Physical Raspberry Pi 3 deployment (Raspbian image, systemd unit, GPIO) | No hardware. The gateway is plain Python 3.5, the version Raspbian Stretch shipped (3.5.3), so it would run on a Pi unchanged. It is only exercised in an x86 container here. |
| Flashing or compiling the sketch for real AVR boards (Uno/Mega) | This needs the Arduino IDE 1.8.5 / avr-gcc board toolchain and a board. The sketch is compiled and tested on the host with fake `Arduino.h`/`Wire.h`/`DHT.h` headers instead. Uno and Mega use the same pins in this sketch, and neither is tested on hardware. |
| Separate `src/mqtt_broker.py` module listed in the original structure | Mosquitto is the broker. A Python broker would duplicate it, and nothing in the concept needs one. |
| Energy-saving / environmental optimisation outcome claimed by the original README | This is a business outcome claim, not a feature. There is no HVAC or actuator control in the concept, and the outcome cannot be measured here. |
| ML or statistical failure prediction beyond the rolling-mean trend rule | This is beyond a realistic solo core. The early-warning rule covers "warning before degradation" honestly, without claiming prediction accuracy. |
| Grafana alerting and notification channels (email/Slack) | Alerts are delivered on MQTT topics and stored in InfluxDB. External notifiers would need real accounts. |
| MQTT TLS and username/password auth, InfluxDB auth | This is a local demo stack. It is listed as a known limitation. |
| Durable store-and-forward buffering on the gateway | Only paho's in-memory queue is used. A persistent spool is extra machinery the README does not describe. |
| `gateways/<id>/commands` topic (subscribed in the old code, never handled) | The README does not describe it and there is no handler. It is removed rather than invented. |
| Status, timeline, role, organisation and "Complete" claims in the original README | These are fabricated. They are not carried into code or docs. |

## Architecture

```
 zone-a                                   zone-b
 +---------------------+                  +---------------------+
 | node_simulator      |  TCP :7000       | node_simulator      |
 | (stands in for      |  CSV lines       | (profile: vib-drift)|
 |  Arduino + DHT22 +  |                  +----------+----------+
 |  ADXL345)           |                             |
 +----------+----------+                             |
            | socket://simulator-a:7000              | socket://simulator-b:7000
            v                                        v
 +---------------------+                  +---------------------+
 | sensor_gateway      |                  | sensor_gateway      |
 | gw-a / zone-a       |                  | gw-b / zone-b       |
 +----------+----------+                  +----------+----------+
            |  MQTT QoS1 sensors/<zone>/<sensor>/data |
            +--------------------+--------------------+
                                 v
                    +------------------------+
                    | Mosquitto 1.4.12 :1883 |
                    +-----------+------------+
                                | subscribe sensors/+/+/data
                                v
                    +------------------------+    alerts/<zone>/<sensor> (QoS2)
                    | data_processor         |---------------> Mosquitto
                    |  readings.validate     |
                    |  alerts.AlertEngine    |
                    |  influx_store          |
                    +-----------+------------+
                                | HTTP line protocol
                                v
                    +------------------------+   CQ 1m mean   +---------------------------+
                    | InfluxDB 1.3.8 :8086   |--------------->| rollup.sensor_readings_1m |
                    | db industrial_iot      |                +---------------------------+
                    | raw.sensor_readings    |
                    | raw.alerts             |
                    +-----------+------------+
                                | InfluxQL
                                v
                    +------------------------+
                    | Grafana 4.6.3 :3000    |  dashboard imported by
                    | "Industrial IoT Floor" |  scripts/grafana_import.py
                    +------------------------+
```

On real hardware, the simulator box is replaced by the Arduino sketch on USB serial, and the gateway uses `SERIAL_URL=/dev/ttyACM0`. Nothing else changes.

## Data model and interfaces

### Serial line protocol (sketch to gateway, 9600 baud)

```
# Sensor node initialized                 <- comment, ignored
SN-001,23.4,41.2,0.12                     <- sensor_id,temp_C(1dp),humidity_%(1dp),vibration_g(2dp)
```

- `sensor_id` must match `^[A-Za-z0-9_-]{1,32}$`.
- Valid ranges come from the sensor datasheets: temperature −40..80 °C (DHT22), humidity 0..100 % and vibration 0..28 g. The sketch sets the ADXL345 to ±16 g per axis, so the magnitude `sqrt(x² + y² + (z − 1)²)` can reach about 27.7 g at most.
- `readings.parse_line(line) -> Reading | None`. `Reading` is a namedtuple with fields `sensor_id, temperature, humidity, vibration`.
- `readings.validate(reading) -> list[str]` returns the problems it found. An empty list means the reading is valid.

### MQTT topics and payloads

| Topic | QoS | Publisher | Payload (JSON) |
|---|---|---|---|
| `sensors/<zone>/<sensor_id>/data` | 1 | gateway | `{"gateway":"gw-a","zone":"zone-a","sensor_id":"SN-001","temperature":23.4,"humidity":41.2,"vibration":0.12,"timestamp":"2017-10-02T10:17:13.123456Z"}` |
| `alerts/<zone>/<sensor_id>` | 2 | processor | `{"zone":"zone-a","sensor_id":"SN-001","gateway":"gw-a","kind":"threshold"\|"trend","metric":"temperature"\|"humidity"\|"vibration","state":"raised"\|"cleared","value":47.1,"limit":45.0,"message":"temperature 47.1 above 45.0","timestamp":"..."}` |

`readings.to_payload(reading, gateway, zone, now) -> str` and `readings.from_payload(str) -> dict` validate the required keys and types, and raise `ValueError` if they are wrong.

### InfluxDB schema (database `industrial_iot`)

| Measurement | RP | Tags | Fields |
|---|---|---|---|
| `sensor_readings` | `raw` (7d, default) | `gateway`, `zone`, `sensor` | `temperature` float, `humidity` float, `vibration` float |
| `alerts` | `raw` | `zone`, `sensor`, `metric`, `kind`, `state` | `value` float, `limit` float, `message` string |
| `sensor_readings_1m` | `rollup` (52w) | `gateway`, `zone`, `sensor` | `temperature`, `humidity` (mean), `vibration` (mean), `vibration_max` (max) |

Continuous query. The text is a template, and `{db}` is filled with the configured database name (`industrial_iot` in production, `test_<uuid>` in integration tests):

```sql
CREATE CONTINUOUS QUERY cq_readings_1m ON "{db}" BEGIN
  SELECT mean(temperature) AS temperature, mean(humidity) AS humidity,
         mean(vibration) AS vibration, max(vibration) AS vibration_max
  INTO "{db}"."rollup".sensor_readings_1m
  FROM "{db}"."raw".sensor_readings GROUP BY time(1m), *
END
```

influxdb-python 4.1.1 has no continuous-query helper (one was added in a later 5.x release). `ensure_schema()` therefore issues the statement with `client.query(...)`. It first runs `SHOW CONTINUOUS QUERIES` and skips the create if `cq_readings_1m` already exists for that database.

`influx_store.InfluxStore(client, database)` provides:

- `ensure_schema()`, which is idempotent.
- `reading_point(payload) -> dict`
- `alert_point(event) -> dict`
- `write_reading(payload)`
- `write_alert(event)`

### Alert engine

`alerts.AlertEngine(thresholds: dict, trend_window: int, vibration_warn: float)` provides `evaluate(payload) -> list[AlertEvent]`. The engine keeps per-sensor state keyed by `(zone, sensor_id)`:

- A deque of the last `trend_window` vibration values.
- The set of active alerts.

A rule emits `raised` on its first breach and `cleared` on its first reading back below the limit. `AlertEvent` is a namedtuple whose fields match the alert payload above.

### Configuration

`config/gateway.ini`:

```ini
[gateway]
id = gw-a
zone = zone-a
[serial]
url = /dev/ttyACM0        ; or socket://simulator-a:7000
baud = 9600
timeout = 5
[mqtt]
host = localhost
port = 1883
keepalive = 60
```

`config/processor.ini`:

```ini
[mqtt]
host = localhost
port = 1883
client_id = processor
[influxdb]
host = localhost
port = 8086
database = industrial_iot
[thresholds]
temperature_max = 45.0
humidity_max = 80.0
vibration_max = 5.0
[trend]
vibration_warn = 2.0
window = 12
```

Environment overrides are applied by `config.load(path, section_map)`:

- `GATEWAY_ID`, `GATEWAY_ZONE`, `SERIAL_URL`
- `MQTT_HOST`, `MQTT_PORT`
- `INFLUXDB_HOST`, `INFLUXDB_PORT`, `INFLUXDB_DATABASE`

### Command-line interfaces

```
python src/sensor_gateway.py  --config config/gateway.ini [--max-readings N]
python src/data_processor.py  --config config/processor.ini
python src/node_simulator.py  --port 7000 --sensor-id SN-001 --interval 5.0 --seed 1 \
                              --profile normal|overheat|humid|vibration-drift|dropout \
                              [--noise 0.0]
python scripts/grafana_import.py --url http://grafana:3000 --user admin --password admin \
                              --influx-url http://influxdb:8086 --influx-db industrial_iot \
                              --datasource-name industrial_iot --dashboard grafana/dashboard.json
```

### Make targets

The first four targets run on the host and start Docker. The last target runs inside the container.

- `make build`: builds the app image.
- `make test`: runs `$(COMPOSE) run --rm tests make check`, with `COMPOSE ?= docker compose` (override with `COMPOSE=docker-compose`).
- `make up` / `make down`: start and stop the stack.
- `make smoke`: prints the latest reading per sensor from InfluxDB.
- `make check`: runs lint, unit, arduino and integration tests. It runs only inside the container.

## Stack and pinned versions

All PyPI pins below were checked with `tools/check_period.py` (0 problems, 19 packages).

| Component | Version | Released | Why it was the popular choice then |
|---|---|---|---|
| Python | 3.5.4 | 2017-08-08 | Raspbian Stretch (Aug 2017), the standard Pi OS, shipped Python 3.5, so Pi gateway code of the time targeted 3.5 (no f-strings). |
| paho-mqtt | 1.3.0 | 2017-06-20 | The Eclipse reference Python MQTT client, and the de facto choice for Python MQTT in 2017. Already pinned in the repo. |
| influxdb (influxdb-python) | 4.1.1 | 2017-06-06 | The official InfluxData Python client for InfluxDB 1.x. Already pinned in the repo. |
| pyserial | 3.4 | 2017-07-23 | The standard Python serial library. Its `serial_for_url` also supports `socket://`, which the simulator uses. Already pinned. |
| requests | 2.18.4 | 2017-08-15 | Pulled in by influxdb. Also used by the Grafana import script. |
| urllib3 / chardet / idna / certifi | 1.22 / 3.0.4 / 2.6 / 2017.11.5 | 2017-07-20 / 2017-06-08 / 2017-08-08 / 2017-11-05 | Transitive dependencies of requests, pinned so pip cannot pull modern releases that dropped Python 3.5. |
| python-dateutil / pytz / six | 2.6.1 / 2017.3 / 1.11.0 | 2017-07-10 / 2017-10-30 / 2017-09-17 | Transitive dependencies of influxdb. |
| pytest | 3.3.1 | 2017-12-06 | The dominant Python test runner by 2017. |
| py / pluggy / attrs | 1.5.2 / 0.6.0 / 17.3.0 | 2017-11-15 / 2017-11-24 / 2017-11-08 | pytest 3.3 dependencies. |
| flake8 (+ pyflakes 1.6.0, pycodestyle 2.3.1, mccabe 0.6.1) | 3.5.0 | 2017-10-23 | The standard Python linter of the period. |
| Mosquitto | 1.4.12 | 2017-05-28 (upstream ChangeLog) | The most widely used open-source MQTT broker. 1.4.12 is the newest 1.4.x tag still on Docker Hub. |
| InfluxDB | 1.3.8 | 2017-12-04 (upstream CHANGELOG) | The leading time-series DB for TICK/Grafana stacks in 2017. This is the last 1.3.x patch in the period. |
| Grafana | 4.6.3 | 2017-12-14 (Grafana 4.6.3 release notes; the official `grafana_4.6.3_amd64.deb` on `s3-us-west-2.amazonaws.com/grafana-releases/release/` has `Last-Modified: Thu, 14 Dec 2017`) | The default dashboard tool for InfluxDB at the time. 4.6.x was the last 4.x line before 5.0 (Mar 2018). Installed from the `.deb` (sha256 `d022fceb939e7570d74b437932bee876e306b0e21ecdd830752c61b4e89dab31`, from the official `.deb.sha256` file) because the Hub image is schema-1. |
| Debian packages for the Grafana image | `adduser`, `libfontconfig1`, `ca-certificates`, `curl` from stretch | snapshot.debian.org `20171231T000000Z` | The `.deb` declares `Depends: adduser, libfontconfig`; in stretch `libfontconfig` is a virtual package provided by `libfontconfig1`. apt points at the dated snapshot (with `Acquire::Check-Valid-Until=false`) so no post-2017 package can be installed. |
| Arduino IDE (for real boards only) | 1.8.5 | 2017-10-02 (git tag in arduino/Arduino) | The standard Arduino toolchain in 2017. arduino-cli did not exist until 2018. |
| Arduino AVR Boards core (for real boards; imitated by the fake headers) | 1.6.20 | bundled with IDE 1.8.5, so released on or before 2017-10-02 (`hardware/arduino/avr/platform.txt` at tag `1.8.5` says `version=1.6.20`) | The core the IDE of the period shipped. The host stub for `Print::printFloat` ports this core's algorithm. |
| Adafruit DHT sensor library (for real boards only) | 1.3.0 | 2016-10-26 (git tag) | The most used DHT22 library. It requires Adafruit Unified Sensor. |
| Adafruit Unified Sensor (for real boards only) | 1.0.2 | 2015-07-08 (git tag in adafruit/Adafruit_Sensor) | Required by DHT sensor library 1.3.0. 1.0.2 was the newest tag in the period; the next one, 1.0.3, is from 2019-03-11. |
| g++ (host-side sketch tests) | 4.9.2 | ships in `python:3.5.4-jessie` (Debian jessie buildpack-deps) | Already present in the image, so no `apt-get` is needed. The jessie apt mirrors are archived. |
| docker-compose file format | 2.4 | host tooling, not a period runtime dependency | Keeps the 2.x format of the existing file. 2.4 is the first 2.x format with the per-service `platform` key, which the Mosquitto and Grafana services need on ARM hosts. The host may run Compose v2 (`docker compose`), and the Makefile variable `COMPOSE` selects it. |

## Docker images (verified tags)

Each tag was checked two ways. The Docker Hub `/v2/repositories/<repo>/tags/<tag>` API gave HTTP 200 and the push date. A `GET` on `registry-1.docker.io/v2/<repo>/manifests/<tag>` with the schema-2 and OCI `Accept` headers (manifest list v2, manifest v2, OCI index, OCI manifest) gave the manifest media type and digest. Any tag served as `application/vnd.docker.distribution.manifest.v1+prettyjws` (schema 1) is rejected, because current Docker cannot pull it. Images are referenced as `<repo>:<tag>@<list digest>` in the Dockerfiles and compose file.

| Image | Tag | Hub | Pushed | Manifest type | List digest | amd64 digest | Architectures | Notes |
|---|---|---|---|---|---|---|---|---|
| `library/python` | `3.5.4-jessie` | 200 | 2017-12-16 | manifest list v2 | `sha256:925b54caeb148843b2f6b5ff8ddd8f5600d4cc07995db78e3adca46e15a67d03` | `sha256:1239787959618a989cea117bc4f4925c4cb1e924f494ca5a9a26c86b06ce807c` | amd64, 386, arm/v5, arm/v7, arm64, ppc64le, s390x | Explicit about the Debian jessie base that the g++ 4.9.2 claim depends on, and pushed in period. The bare `3.5.4` tag was re-pushed 2018-01-08 and has the same amd64 image; the floating `3.5` now resolves to 3.5.10 (2020). A buildpack image with gcc, g++ and make. |
| `library/influxdb` | `1.3.8` | 200 | 2017-12-15 | manifest list v2 | `sha256:8c3157245ee6863203cf2f410d026b8e3683b502f9bd967728337ece4c730cc0` | `sha256:f6d904821a28793e7c4dd0a39bcc19886e0629f86345bec02be3a52270760ec1` | amd64, arm/v7, arm64 | Replaces the floating `1.3`. |
| `library/eclipse-mosquitto` | `1.4.12` | 200 | 2018-01-09 | manifest list v2 | `sha256:bb177e7bd81746fc59b919ccb84b6ffffbe1ec1f7f933fa68c3aca4b4be364b6` | `sha256:309567a2781ad30367d0224ea2d877047b1a9f0f1332094b0d375b16da1e5b98` | amd64 only | **`eclipse-mosquitto:1.4` (used by the current compose file) returns 404, and so does `1.4.14`.** `1.4.12` is the nearest existing tag. The tag is a 2018-01-09 rebuild of the 2017 Mosquitto 1.4.12 release, so it is pinned by digest. |
| `library/debian` | `stretch-20171210` | 200 | 2017-12-13 | manifest list v2 | `sha256:0a5fcee6f52d5170f557ee2447d7a10a5bdcf715dd7f0250be0b678c556a501b` | `sha256:02741df16aee1b81c4aaff4c48d75cc2c308bade918b22679df570c170feef7c` | amd64, 386, arm/v5, arm/v7, arm64, ppc64le, s390x | Base of the local Grafana image (`docker/grafana/Dockerfile`), plus the Grafana 4.6.3 `.deb` and the snapshot packages in the pin table. A dated stretch 9.3 tag from the period; the floating `stretch-slim` was re-pushed in 2022, and no dated `-slim` tag from 2017 exists. |
| `grafana/grafana` | `4.6.3` | 200 | 2017-12-14 | **v1+prettyjws (schema 1): rejected** | n/a | n/a | amd64 | Not used. Every Grafana 4.x and 5.0.x tag is schema 1; the first schema-2 tag is 5.1.0 (2018). Replaced by the local build above. |

Only `eclipse-mosquitto:1.4.12` and the Grafana `.deb` are amd64-only. `python:3.5.4-jessie`, `influxdb:1.3.8` and `debian:stretch-20171210` are multi-arch and run natively on ARM hosts. The compose file therefore sets `platform: linux/amd64` only on the `mosquitto` and `grafana` services, which run under emulation on ARM hosts. Nothing sets `DOCKER_DEFAULT_PLATFORM` globally.

## Simulated and mocked integrations

| Real thing | Replaced by | Where |
|---|---|---|
| Arduino Uno + DHT22 + ADXL345 on USB serial | **node simulator**: a TCP server emitting the sketch's CSV format, with seeded fault profiles (`dropout` skips lines like a NaN DHT read; optional `--noise` injects labelled serial-noise garbage) | `src/node_simulator.py`, compose services `simulator-a`, `simulator-b` |
| USB serial link `/dev/ttyACM0` | **pyserial `socket://` URL** (and `loop://` in unit tests) | `SERIAL_URL` env var |
| Raspberry Pi 3 gateway hardware | **gateway container** on `python:3.5.4-jessie` (x86_64) | compose services `gateway-a`, `gateway-b` |
| Arduino core, Wire and DHT libraries (for the sketch tests) | **host-side fake headers** `tests/arduino/stubs/{Arduino.h,Wire.h,DHT.h}` with scripted sensor values, controllable `millis()`, captured `Serial` output and a recorded log of `Wire` register writes. `Serial.print(float, digits)` ports `Print::printFloat` from Arduino AVR Boards core 1.6.20 (bundled with IDE 1.8.5, 2017), so float formatting is Arduino's rounding, not libc `printf` | `tests/arduino/` |
| MQTT broker / InfluxDB client in unit tests | **FakeMqttClient** (records publish/subscribe calls) and **FakeInfluxClient** (records points and queries) | `tests/fakes.py` |

Mosquitto, InfluxDB and Grafana are the real period images, not mocks. The final README must say that the sensors, the Arduino hardware and the Raspberry Pi are simulated.

## Existing code inventory (`git ls-files`)

| File | Decision | Reason |
|---|---|---|
| `README.md` | refactor | Regenerate from `tools/readme_template.md` in the last task. The current honest wording is a good base, but its Status and Layout sections will be out of date. |
| `arduino/sensor_node.ino` | refactor | Keep the design (DHT22 + ADXL345, CSV output, LED feedback). Four fixes are needed. (1) `Wire.read() \| (Wire.read() << 8)` depends on unspecified evaluation order, so read LSB and MSB into separate variables. (2) It lacks the `readVibration` prototype needed outside the Arduino IDE. (3) Remove the unused `VIBRATION_PIN A0`. (4) Move the magnitude math into `sensor_logic.h` so it can be tested. (5) `setup()` never writes DATA_FORMAT (0x31), so the ADXL345 stays at its ±2 g default; write 0x0B (FULL_RES, ±16 g, still 4 mg/LSB) so the sketch can report the vibration levels the thresholds use. |
| `config/mosquitto.conf` | keep | A valid Mosquitto 1.4 config. The listener, persistence path and stdout logging match the image layout. |
| `docker-compose.yml` | refactor | Keep the three infrastructure services and move to format 2.4 (for per-service `platform`). The `eclipse-mosquitto:1.4` tag no longer exists, so move to `1.4.12` pinned by digest. Pin `influxdb:1.3.8` by digest. `grafana/grafana:4.6.0` is a schema-1 image that current Docker cannot pull, so build Grafana 4.6.3 from `docker/grafana/Dockerfile` instead. Add the simulator, gateway, processor and tests services. `INFLUXDB_DB` is kept, but the processor also creates the database itself. |
| `requirements.txt` | refactor | Keep the three existing pins, which are all period-valid (paho-mqtt 1.3.0, influxdb 4.1.1, pyserial 3.4). Add exact pins for all transitive dependencies so Python 3.5 installs are reproducible. Test tools go in the new `requirements-dev.txt`. |
| `src/sensor_gateway.py` | refactor | Keep the class structure, serial connect with the Arduino reset delay, CSV parsing and MQTT publish. It currently uses f-strings, which are a **SyntaxError on Python 3.5**, so change them to `.format()`. Move InfluxDB writes and threshold checks into the processor, and parsing into `readings.py`. Add dependency injection, `serial_for_url` and reconnect. Remove the unhandled `commands` subscription and the hard-coded `'industrial_iot'` database name. |

## Test strategy

Everything runs through `make test`, which on the host runs `$(COMPOSE) run --rm tests make check` (`COMPOSE ?= docker compose`, overridable to `docker-compose`). The `tests` service is built from the project Dockerfile (`FROM python:3.5.4-jessie`) and depends on `mosquitto`, `influxdb` and `grafana` (the locally built Grafana image).

- **Lint**: `flake8 src scripts tests` and `python -m compileall -q src scripts`. compileall guards against 3.6-only syntax.
- **Python unit tests** (`tests/unit/`, no network):
  - `readings`: parsing edge cases, range validation and the payload round-trip.
  - `config`: INI and environment variable precedence.
  - `node_simulator`: deterministic output per seed, the line format matching `parse_line`, each fault profile, `--noise` injection, and two sequential clients each getting their own stream.
  - `sensor_gateway`: pyserial `loop://` input and FakeMqttClient topic and QoS, with comment and garbage lines skipped.
  - `alerts`: raise and clear edges, trend window maths, and per-sensor isolation.
  - `influx_store`: point shapes and idempotent `ensure_schema` against FakeInfluxClient.
  - `data_processor`: message routing, bad payload handling, and alerts published and stored.
  - `dashboard.json`: every panel query refers to an existing measurement and field.
- **Arduino host tests** (`tests/arduino/`). g++ 4.9 builds `arduino/sensor_node.ino` together with the fake headers and a small assert-based test runner. The tests cover:
  - vibration magnitude math;
  - the DATA_FORMAT (0x31 = 0x0B) write in `setup()`, checked through the `Wire` stub's write log;
  - CSV formatting precision, using the ported `Print::printFloat`;
  - NaN DHT reads producing no output;
  - timing gated by `READ_INTERVAL`.
- **Integration tests** (`tests/integration/`, need the containers; `wait_for_port` helpers poll readiness up to 60 s):
  - The gateway publishes to real Mosquitto 1.4.12.
  - `InfluxStore.ensure_schema` against real InfluxDB 1.3.8 creates the RPs and CQ, as shown by `SHOW RETENTION POLICIES` and `SHOW CONTINUOUS QUERIES`, and written points can be queried back.
  - The end-to-end pipeline runs in-process (simulator thread → gateway → Mosquitto → processor → InfluxDB). It asserts that readings land, and that an `overheat` profile produces a `raised` alert on `alerts/#` and in the `alerts` measurement.
  - `grafana_import.py` against the locally built Grafana 4.6.3 creates the `industrial_iot` datasource (`GET /api/datasources/name/industrial_iot`), and the dashboard is returned by `GET /api/dashboards/db/industrial-iot-floor`.
- **Not tested**: real AVR compilation, real sensors and serial timing, Raspberry Pi hardware, and the continuous query actually firing, which needs a ≥1 minute wall-clock wait. The CQ's existence and its SQL are tested instead.

## Known limitations that will remain

- The Arduino, the sensors, the serial cable and the Raspberry Pi are simulated. No hardware is exercised.
- There is no MQTT or InfluxDB authentication or TLS, and the Grafana admin credentials are the defaults. This is a local demo only.
- Readings are lost while the broker is unreachable, beyond paho's in-memory queue. The processor does not retry failed InfluxDB writes and only logs them.
- Alert state lives in processor memory, so it resets on restart.
- The trend rule is a fixed rolling-mean threshold, not a learned model. Vibration magnitude assumes the ADXL345 is mounted Z-up (1 g is subtracted from Z).
- Grafana dashboard provisioning is a one-shot import script, because Grafana 4.x has no file provisioning.
- Mosquitto 1.4.12 and the Grafana 4.6.3 `.deb` are amd64-only, so those two services run under emulation on ARM hosts. The Python and InfluxDB images run natively.
- Grafana is not the upstream Docker image; it is the official 4.6.3 `.deb` installed on a period Debian base, because the upstream 4.x images cannot be pulled any more.
