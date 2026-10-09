# industrial-iot: Implementation Plan

This plan implements [SPEC.md](SPEC.md) in dependency order. Each task is one commit, and `make test` must pass after every task.

## Conventions for every task

- **Host commands**:
  - `make test` builds the `tests` image and runs `$(COMPOSE) run --rm tests make check`.
  - The Makefile sets `COMPOSE ?= docker compose` (override it with `COMPOSE=docker-compose`). It does not export `DOCKER_DEFAULT_PLATFORM`; only the amd64-only `mosquitto` and `grafana` services carry `platform: linux/amd64` in the compose file.
- **In-container target**: `make check` runs lint, unit, arduino and integration (each is added by the task that introduces it). It is only ever run inside the `python:3.5.4-jessie` image.
- **Python style**:
  - Code must be valid Python 3.5: no f-strings, no variable annotations and no `async` generators.
  - Modules live flat in `src/` and import each other by module name. `PYTHONPATH=/app/src:/app` is set in the Dockerfile, and a root `conftest.py` does the same for pytest.
- **Pins**: any dependency change must be re-verified with `python3 /Users/alexsanders.ephrem/deployment/portfolio-rebuild/tools/check_period.py <repo>` before committing.
- **Commit messages**: imperative, with no dates, no tool attribution and no employer names.

---

## T1: Scaffold Docker image, Makefile and pytest harness

**Goal:** `make test` runs a real (trivial) suite inside `python:3.5.4-jessie` from the very first commit. Old broken image tags are fixed.

**Files:**
- Create `Dockerfile`:
  - `FROM python:3.5.4-jessie@sha256:925b54caeb148843b2f6b5ff8ddd8f5600d4cc07995db78e3adca46e15a67d03`
  - `WORKDIR /app`
  - `COPY requirements*.txt`
  - `pip install --no-deps -r requirements.txt -r requirements-dev.txt && pip check`
  - `COPY . .`
  - `ENV PYTHONPATH=/app/src:/app`
- Create `requirements-dev.txt` with `pytest==3.3.1`, `py==1.5.2`, `pluggy==0.6.0`, `attrs==17.3.0`, `flake8==3.5.0`, `pyflakes==1.6.0`, `pycodestyle==2.3.1` and `mccabe==0.6.1`.
- Modify `requirements.txt`. Keep the three existing pins and add `requests==2.18.4`, `urllib3==1.22`, `chardet==3.0.4`, `idna==2.6`, `certifi==2017.11.5`, `python-dateutil==2.6.1`, `pytz==2017.3` and `six==1.11.0`.
- Create `Makefile` with host targets `build test up down smoke` and in-container targets `check unit`.
- Create `setup.cfg` with `[tool:pytest] testpaths=tests` and a `[flake8]` section (`max-line-length=100`).
- Create `conftest.py` to put `src/` on `sys.path`.
- Create `tests/__init__.py`, `tests/unit/__init__.py` and `tests/unit/test_environment.py`.
- Create `docker/grafana/Dockerfile` (the Hub `grafana/grafana` 4.x images are schema-1 and cannot be pulled):
  - `FROM debian:stretch-20171210@sha256:0a5fcee6f52d5170f557ee2447d7a10a5bdcf715dd7f0250be0b678c556a501b`;
  - point `/etc/apt/sources.list` at `http://snapshot.debian.org/archive/debian/20171231T000000Z stretch main` and run apt with `-o Acquire::Check-Valid-Until=false`. The archive keys that signed this snapshot have since expired (`EXPKEYSIG`), so apt rejects the signature. `update` therefore also passes `-o Acquire::AllowInsecureRepositories=true` and `install` passes `--allow-unauthenticated`. apt still checks each package against the hashes in the downloaded `Release` file, and after the install the build fetches `Release.gpg` with `curl -fsSL` and verifies that `Release` file with `gpgv` against the keyrings in `/etc/apt/trusted.gpg.d/`; a bad signature fails the build;
  - `apt-get install -y --no-install-recommends adduser libfontconfig1 ca-certificates curl`;
  - download `https://s3-us-west-2.amazonaws.com/grafana-releases/release/grafana_4.6.3_amd64.deb`, check it with `echo "d022fceb939e7570d74b437932bee876e306b0e21ecdd830752c61b4e89dab31  grafana.deb" | sha256sum -c -`, then `dpkg -i grafana.deb` and delete it;
  - `EXPOSE 3000`, `USER grafana`, and run `grafana-server --homepath=/usr/share/grafana --config=/etc/grafana/grafana.ini cfg:default.paths.data=/var/lib/grafana cfg:default.paths.logs=/var/log/grafana`.
- Create `.dockerignore` and `.gitignore` (`__pycache__`, `.pytest_cache`, `*.o`, `build/`).
- Modify `docker-compose.yml`:
  - `version: '2.4'` (needed for the per-service `platform` key).
  - `eclipse-mosquitto:1.4` → `eclipse-mosquitto:1.4.12@sha256:bb177e7bd81746fc59b919ccb84b6ffffbe1ec1f7f933fa68c3aca4b4be364b6` with `platform: linux/amd64` (the old tag is 404 on Docker Hub; 1.4.12 is amd64-only).
  - `influxdb:1.3` → `influxdb:1.3.8@sha256:8c3157245ee6863203cf2f410d026b8e3683b502f9bd967728337ece4c730cc0`.
  - `grafana/grafana:4.6.0` → `build: docker/grafana` with `image: industrial-iot:grafana-4.6.3` and `platform: linux/amd64`.
  - Add a `tests` service (`build: .`, `image: industrial-iot:tests`, `volumes: [.:/app]`, `depends_on: [mosquitto, influxdb, grafana]`, `command: make check`).
  - Set the top-level `name: industrial-iot`, put the default network on subnet `172.45.0.0/24`, and publish host ports in the 20500–20599 range: Mosquitto `20583:1883`, InfluxDB `20586:8086`, Grafana `20530:3000`. This keeps the stack from clashing with other stacks on a shared Docker host. Services reach each other by service name on the internal ports, so nothing else changes.

**Tests to write first:** `tests/unit/test_environment.py` asserts:
- `sys.version_info[:2] == (3, 5)`;
- `paho.mqtt.__version__ == '1.3.0'`;
- `serial.VERSION == '3.4'`;
- `influxdb.__version__ == '4.1.1'`.

**Acceptance:** `make test` (the check target runs only `pytest tests/unit` in this task. Lint is deferred to T2 because the current `src/sensor_gateway.py` does not compile on 3.5).

**Commit message:**
```
Add Docker test harness and pin full Python 3.5 dependency set

Build a python:3.5.4-jessie image with exact transitive pins and run pytest
through make test. Point compose at image tags that can still be pulled
and build Grafana 4.6.3 from its official package.
```

---

## T2: Port gateway to Python 3.5 and extract reading protocol

**Goal:**
- Make `src/sensor_gateway.py` valid Python 3.5 by replacing its f-strings with `.format()`.
- Move CSV parsing, range validation and JSON payload creation into `src/readings.py`.
- Turn on lint.

**Files:**
- Create `src/readings.py` with:
  - `Reading` (a namedtuple);
  - `parse_line(line)`, which returns `None` for blank lines, `#` comments, wrong field counts, non-numeric fields and bad sensor IDs;
  - `validate(reading) -> list`;
  - `to_payload(reading, gateway, zone, now)`;
  - `from_payload(text)`, which raises `ValueError`.
- Modify `src/sensor_gateway.py`:
  - Use `readings.parse_line` and drop `_parse_reading`.
  - Replace all f-strings.
- Modify `Makefile` to add a `lint` target (`flake8 src tests` plus `python -m compileall -q src`) to `check`.
- Create `tests/unit/test_readings.py`.

**Tests to write first:** `test_readings.py` covers:
- a valid line from the sketch;
- a `# Sensor node initialized` line → None;
- `SN-001,nan,40,0.1` → None;
- 3 fields → None;
- extra whitespace;
- out-of-range values (humidity 120, temp −50, vibration 30) reported by `validate`;
- the `to_payload`/`from_payload` round trip, keeping key set and types, with the timestamp ending in `Z`;
- `from_payload` rejecting missing keys and non-numeric fields.

**Acceptance:** `make test`

**Commit message:**
```
Extract reading protocol module and make gateway Python 3.5 clean

Move CSV parsing, range checks and payload JSON into readings.py and
replace f-strings so the gateway runs on the Raspbian-era interpreter.
```

---

## T3: Add INI configuration with environment overrides

**Goal:** Replace the hard-coded `__main__` dict with INI config files plus env overrides.

**Files:**
- Create `src/config.py` with `load(path, env=os.environ) -> dict`. It returns a nested dict with typed ints and floats, and maps the `GATEWAY_ID`, `GATEWAY_ZONE`, `SERIAL_URL`, `MQTT_HOST`, `MQTT_PORT`, `INFLUXDB_HOST`, `INFLUXDB_PORT` and `INFLUXDB_DATABASE` overrides.
- Create `config/gateway.ini` and `config/processor.ini`, with the contents shown in SPEC.
- Modify `src/sensor_gateway.py` to add argparse `--config` and read its settings from `config.load`.
- Create `tests/unit/test_config.py`.

**Tests to write first:**
- The INI values load with the correct types (port is an int, thresholds are floats).
- An env var overrides the INI value.
- A missing file raises `FileNotFoundError` with the path.
- Unknown sections are preserved.
- Both shipped INI files load without error.

**Acceptance:** `make test`

**Commit message:**
```
Load gateway and processor settings from INI with env overrides

Replace the hard-coded config dict with configparser-based loading so
compose can set host names and zone ids per service.
```

---

## T4: Fix sensor-node sketch and add host-compiled sketch tests

**Goal:** Make the Arduino sketch correct and testable without a board.

**Files:**
- Create `arduino/sensor_logic.h`:
  - `inline float vibrationMagnitude(int16_t x, int16_t y, int16_t z)`, using 0.004 g/LSB with 1 g subtracted from Z;
  - `inline int16_t combineBytes(uint8_t lsb, uint8_t msb)`.
- Modify `arduino/sensor_node.ino`:
  - `#include "sensor_logic.h"`;
  - add the forward declaration `float readVibration();`;
  - in `setup()`, write the ADXL345 DATA_FORMAT register: `0x31 = 0x0B` (FULL_RES, ±16 g, 4 mg/LSB), so the device range covers the 0..28 g validation range and the 5.0 g `vibration_max`;
  - read the six bytes into locals before combining them (this removes the dependence on unspecified evaluation order);
  - remove the unused `VIBRATION_PIN`;
  - keep the output format byte-for-byte.
- Create the fake headers `tests/arduino/stubs/Arduino.h`, `tests/arduino/stubs/Wire.h` and `tests/arduino/stubs/DHT.h`:
  - `millis()` driven by the test;
  - `Serial` captures `print`/`println`. `print(float, digits)` is a port of `Print::printFloat` from Arduino AVR Boards core 1.6.20 (the core bundled with IDE 1.8.5, 2017), not a `printf` call, so the precision test checks Arduino's own rounding;
  - `Wire` returns a scripted byte queue and records every `beginTransmission`/`write` pair as a register write log;
  - `DHT` returns scripted temperature and humidity, including NAN.
- Create `tests/arduino/test_sensor_node.cpp`, a small assert-based runner that `#include`s the `.ino`.
- Modify `Makefile` to add an `arduino` target to `check`: `g++ -std=c++11 -Wall -Werror -Itests/arduino/stubs -Iarduino -x c++ tests/arduino/test_sensor_node.cpp -o build/test_sensor_node && build/test_sensor_node`.
- Modify `.gitignore` to add `build/`.

**Tests to write first:**
- `vibrationMagnitude(0,0,250)` ≈ 0.0.
- `(250,0,250)` ≈ 1.0.
- `combineBytes(0x18,0xFC)` == −1000.
- After `setup()`, Serial contains `# Sensor node initialized`.
- After `setup()`, the Wire write log contains register `0x31` with value `0x0B` (and `0x2D` = `0x08`, measurement mode).
- `loop()` before 5000 ms emits nothing.
- At 5000 ms with DHT 23.44/41.26 and scripted Wire bytes, it emits `SN-001,23.4,41.3,<v>` with 2 decimals, formatted by the ported `printFloat`.
- A NaN temperature emits no data line.

**Acceptance:** `make test`

**Commit message:**
```
Make ADXL345 register reads evaluation-order safe and test sketch on host

Read accelerometer bytes into locals before combining, set the sensor
to full-resolution 16 g range, add prototypes, factor vibration math
into sensor_logic.h and run it against fake Arduino, Wire and DHT
headers with g++.
```

---

## T5: Add node simulator emitting the sketch's serial format

**Goal:** Build a deterministic stand-in for the Arduino and serial link, reachable over TCP.

**Files:**
- Create `src/node_simulator.py`:
  - `generate(profile, sensor_id, seed)`, an infinite iterator with one item per reading interval: a CSV line using the sketch's precision (1/1/2 dp), or `None` for an interval with no output (only `dropout` yields `None`, and `serve` writes nothing for it);
  - the profiles `normal`, `overheat` (temperature ramps past 45 °C), `humid`, `vibration-drift` (a slow vibration rise that passes the 2.0 g warn level, then 5.0 g) and `dropout` (occasional skipped intervals with no line at all, which is what the sketch does on a NaN DHT read);
  - `with_noise(lines, rate, seed)`, an explicitly labelled serial-noise injector that inserts garbage and blank lines, used only when `--noise` is above 0 (default 0.0);
  - `serve(host, port, line_factory, interval)`, which uses stdlib `socketserver.ThreadingTCPServer`. `line_factory` is a zero-argument callable such as `lambda: generate(profile, sensor_id, seed)`, and each connection calls it to get its own iterator, so overlapping or repeated connections never share a generator. Each connection first emits the `# Sensor node initialized` banner;
  - an argparse CLI as described in SPEC.
- Create `tests/unit/test_node_simulator.py`.

**Tests to write first:**
- The same seed gives the same first 50 lines.
- Every non-comment line from `normal` passes `readings.parse_line` and `validate`.
- `overheat` exceeds 45.0 within 60 lines.
- `vibration-drift` passes 2.0 before 5.0.
- `dropout` over 200 intervals emits fewer than 200 data lines, and every line it does emit passes `parse_line`.
- `with_noise(..., rate=0.2)` yields at least one line where `parse_line` is None in 200 lines; `rate=0` yields the input unchanged.
- `serve` on port 0: a client reads the banner and then three lines, using a socket and a 0.01 s interval.
- Two sequential clients on the same `serve` instance each get the banner and then the same first three lines for the same seed (each has its own iterator), and no `ValueError: generator already executing` is raised.

**Acceptance:** `make test`

**Commit message:**
```
Add TCP node simulator that speaks the sensor sketch line format

Seeded profiles for normal, overheat, humid, vibration drift and
dropout, plus optional serial-noise injection, let the gateway run
without an Arduino attached.
```

---

## T6: Refactor gateway to serial URLs, MQTT-only publishing and reconnect

**Goal:**
- The gateway reads from any pyserial URL.
- It publishes readings with QoS 1 to `sensors/<zone>/<sensor_id>/data`.
- It no longer writes to InfluxDB or checks thresholds; the processor owns both.
- It reconnects serial with backoff.
- This task adds the first integration test, against real Mosquitto.

**Files:**
- Modify `src/sensor_gateway.py`:
  - Change the constructor to `SensorGateway(cfg, mqtt_factory=paho Client, serial_factory=serial.serial_for_url, clock=datetime.utcnow, sleep=time.sleep)`. `sleep` is injected so unit tests can check the reset delay and the reconnect backoff (1 s doubling to 30 s) without waiting. The serial URL attribute is `serial_url`.
  - Add `process_line(line)` and `run(max_readings=None)`.
  - Remove the InfluxDB client, `_ensure_database`, `_check_thresholds` and the `commands` subscription.
  - Keep the 2 s Arduino reset delay only for `/dev/` URLs.
- Create `tests/fakes.py` with `FakeMqttClient` (records `connect`, `publish(topic,payload,qos)`, `subscribe` and `loop_start`/`loop_stop`, and can fire `on_connect`/`on_message`) and `FakeInfluxClient`.
- Create `tests/unit/test_sensor_gateway.py`.
- Create `tests/integration/__init__.py`, `tests/integration/conftest.py` (with `wait_for_port(host, port, timeout=60)` and `mqtt_host`/`influx_host` fixtures read from env) and `tests/integration/test_gateway_mqtt.py`.
- Modify `docker-compose.yml` to set `MQTT_HOST=mosquitto` and `INFLUXDB_HOST=influxdb` in the `tests` environment.
- Modify `Makefile` so `check` runs `pytest tests/integration` after the unit tests.

**Tests to write first:**
- **Unit, with `loop://` serial and FakeMqttClient:**
  - A valid line → one publish on `sensors/zone-a/SN-001/data` with qos=1, and a payload with gateway and zone set.
  - A comment, garbage or out-of-range line → no publish.
  - A `SerialException` on read triggers a reconnect attempt through the factory.
  - `max_readings=3` stops after three publishes.
- **Integration:** a gateway fed by an in-process `node_simulator.serve` thread, publishing to `mosquitto:1883`. A paho subscriber on `sensors/#` receives ≥3 valid payloads within 10 s.

**Acceptance:** `make test`

**Commit message:**
```
Make gateway a serial-to-MQTT bridge with URL-based serial input

Accept socket:// and device URLs via serial_for_url, reconnect on
serial errors and leave storage and alerting to the processor.
```

---

## T7: Add edge-triggered threshold and vibration trend alert engine

**Goal:** Build pure alert logic with no I/O: threshold rules plus the rolling-mean vibration early warning.

**Files:**
- Create `src/alerts.py` with:
  - `AlertEvent` (a namedtuple);
  - `AlertEngine(thresholds, trend_window, vibration_warn)`;
  - `evaluate(payload) -> list`.
- Create `tests/unit/test_alerts.py`.

**Tests to write first:**
- A temperature of 46 with a max of 45 → one `raised` threshold event. A second 46 → no event. Then 44 → one `cleared` event.
- Humidity and vibration behave the same way.
- Trend: with window 4 and warn 2.0, readings of 1,1,3,3 give a mean of 2.0, which does not raise. A following 3 gives a mean of 2.5 and raises `kind=trend`, `metric=vibration`. The trend does not raise before the window is full.
- Two sensors in the same zone and the same sensor ID in two zones keep separate state.
- The event message is formatted as `temperature 46.0 above 45.0`.

**Acceptance:** `make test`

**Commit message:**
```
Add alert engine with threshold and rolling vibration trend rules

Alerts fire once on breach and once on recovery per sensor and metric,
giving an early warning before vibration reaches its hard limit.
```

---

## T8: Add InfluxDB store with retention policies and 1m rollup query

**Goal:** Build the schema setup and point writing described in SPEC, verified against real InfluxDB 1.3.8.

**Files:**
- Create `src/influx_store.py`:
  - `InfluxStore(client, database)`;
  - `ensure_schema()`, which creates the database, `raw` 7d as the default RP, `rollup` 52w and `cq_readings_1m`, and is idempotent because it checks `SHOW` output before creating anything. The CQ text from SPEC is a template filled with `self.database`, and it is issued with `client.query('CREATE CONTINUOUS QUERY ...')`, because influxdb-python 4.1.1 has no CQ helper. Idempotence for the CQ is checked through `SHOW CONTINUOUS QUERIES`;
  - `reading_point`, `alert_point`, `write_reading` and `write_alert`, using `time_precision='u'`.
- Create `config/influxdb.conf`, a minimal 1.3 config (meta, data and wal dirs under `/var/lib/influxdb`, `[http] bind-address=":8086"`, `[continuous_queries] enabled=true`).
- Modify `docker-compose.yml` to mount it at `/etc/influxdb/influxdb.conf:ro`.
- Create `tests/unit/test_influx_store.py` and `tests/integration/test_influx_store.py`.

**Tests to write first:**
- **Unit (FakeInfluxClient):**
  - `reading_point` has measurement `sensor_readings`, tags `gateway`/`zone`/`sensor`, float fields and the payload timestamp.
  - `alert_point` tags include `kind`, `state` and `metric`.
  - Calling `ensure_schema()` twice issues the create calls only once.
  - With database `test_x`, the issued CQ statement contains `ON "test_x"`, `INTO "test_x"."rollup"` and `FROM "test_x"."raw"`, and no literal `industrial_iot`.
- **Integration (a throwaway database named `test_<uuid>`, dropped in teardown):**
  - After `ensure_schema()`, `SHOW RETENTION POLICIES` lists `raw` (default, 168h0m0s) and `rollup`.
  - `SHOW CONTINUOUS QUERIES` lists `cq_readings_1m` under the `test_<uuid>` database.
  - After `write_reading`, `SELECT * FROM sensor_readings` returns the point with its tags.

**Acceptance:** `make test`

**Commit message:**
```
Add InfluxDB store with raw and rollup retention and 1m downsampling

Create the database, retention policies and continuous query
idempotently and write reading and alert points with zone tags.
```

---

## T9: Add data processor bridging MQTT to InfluxDB and alert topics

**Goal:** Build the processor, which wires `readings`, `alerts` and `influx_store` together behind an MQTT subscription.

**Files:**
- Create `src/data_processor.py`:
  - `DataProcessor(cfg, mqtt_client, store, engine)`;
  - `on_connect`, which subscribes to `sensors/+/+/data` with qos 1;
  - `on_message`, which parses the payload with `readings.from_payload`, checks it with `validate`, writes it with `store.write_reading`, passes it to `engine.evaluate`, and for each event publishes `alerts/<zone>/<sensor_id>` with qos 2 and calls `store.write_alert`;
  - `stats` counters (`received`, `stored`, `rejected`, `alerts`, `write_errors`);
  - handling for InfluxDB write errors, which are logged and counted in `write_errors` without crashing the loop;
  - a `main()` that uses argparse and `config.load` and calls `ensure_schema()` with retry until InfluxDB is up.
- Create `tests/unit/test_data_processor.py` and `tests/integration/test_processor.py`.

**Tests to write first:**
- **Unit:**
  - A valid message → one reading point and no alert.
  - A temperature of 50 → a reading point, an alert publish on `alerts/zone-a/SN-001` with qos=2, and an alert point.
  - Invalid JSON or a missing key → `rejected` is incremented and nothing is written.
  - A store that raises `InfluxDBServerError` → the error is logged, `received` is still counted and the next message is still processed.
  - The topic zone and sensor are ignored in favour of the payload's fields, and a mismatch is logged.
- **Integration:**
  - The processor is connected to the real Mosquitto and InfluxDB, using a test database.
  - The test publishes 3 normal readings and 1 overheat reading for the same zone and sensor, with distinct, increasing timestamps (`base + i * 1 s`), so InfluxDB does not merge them into one point.
  - Within 10 s: InfluxDB has 4 `sensor_readings` rows and 1 `alerts` row with `state='raised'`, and a subscriber on `alerts/#` received the event.

**Acceptance:** `make test`

**Commit message:**
```
Add data processor that stores readings and publishes alerts

Subscribe to sensor topics, validate payloads, write them to InfluxDB
and emit edge-triggered alert events on MQTT and into the alerts series.
```

---

## T10: Wire multi-zone compose stack and end-to-end pipeline test

**Goal:** `make up` (`$(COMPOSE) up -d --build`) runs the whole pipeline for two zones. An end-to-end test proves simulator → gateway → broker → processor → InfluxDB.

**Files:**
- Modify `docker-compose.yml` to add:
  - `simulator-a` (`python src/node_simulator.py --port 7000 --sensor-id SN-001 --profile normal --interval 1`);
  - `simulator-b` (`--sensor-id SN-101 --profile vibration-drift --interval 1`);
  - `gateway-a` and `gateway-b` (`SERIAL_URL=socket://simulator-a:7000` and `socket://simulator-b:7000`, plus `GATEWAY_ID`, `GATEWAY_ZONE` and `MQTT_HOST=mosquitto`);
  - `processor` (`MQTT_HOST`, `INFLUXDB_HOST`), with `restart: on-failure` on the gateways and the processor.
  - These five services share a `x-app` anchor (`build: .`, `image: industrial-iot:tests`) and run the code baked into that image.
  - Put the `tests` service under `profiles: [test]` so `make up` does not start it. `make test` still runs it, because `compose build tests` and `compose run tests` name the service explicitly.
- Modify `config/mosquitto.conf` only if needed for the container (it is expected to be unchanged).
- Modify `Makefile`:
  - `up` runs `$(COMPOSE) up -d --build`.
  - `smoke` runs `$(COMPOSE) exec influxdb influx -database industrial_iot -execute 'SELECT last(temperature),last(vibration) FROM sensor_readings GROUP BY zone,sensor'`.
- Create `tests/integration/test_pipeline.py`.

**Tests to write first:** the integration test runs everything in-process against the real broker and InfluxDB:
- a `node_simulator.serve` thread with the `overheat` profile at a 0.05 s interval;
- a `SensorGateway` thread using `socket://127.0.0.1:<port>`;
- a `DataProcessor` on a `test_<uuid>` database.

It asserts that within 30 s there are at least 10 readings for zone `zone-e2e` and a `raised` temperature alert in the `alerts` measurement.

**Acceptance:**
- `make test`
- `make up && sleep 20 && make smoke`: the smoke output shows rows for `zone-a/SN-001` and `zone-b/SN-101`.

**Commit message:**
```
Run two simulated zones through the full stack in compose

Add simulator, gateway and processor services and an end-to-end test
that follows a reading from the simulated node into InfluxDB.
```

---

## T11: Add Grafana 4.6 dashboard and API import script

**Goal:** Provide dashboards for per-zone monitoring and historical rollups, loaded into Grafana 4.6.3 through its HTTP API.

**Files:**
- Create `grafana/dashboard.json`:
  - title "Industrial IoT Floor", uid-less, `schemaVersion` 14;
  - every panel's `datasource` is the literal name `industrial_iot`;
  - a templating variable `zone` (`SHOW TAG VALUES FROM sensor_readings WITH KEY = "zone"`);
  - graph panels for temperature, humidity and vibration from `sensor_readings`, grouped by `sensor`, `$__interval`;
  - a "1m rollup" panel from `rollup.sensor_readings_1m`;
  - a table panel of the `alerts` measurement.
- Create `scripts/__init__.py` (empty) and `scripts/grafana_import.py`:
  - it uses requests;
  - it takes `--datasource-name` (default `industrial_iot`) and `--influx-db` (default `industrial_iot`);
  - it runs `POST /api/datasources` (name from `--datasource-name`, type InfluxDB, proxy access, database from `--influx-db`), accepting a 409 "already exists";
  - it runs `POST /api/dashboards/db` with `{"dashboard":..., "overwrite": true}`;
  - it retries until Grafana `/api/health` answers.
- Modify `docker-compose.yml` to add a one-shot `grafana-init` service (built from the project Dockerfile) that runs the script after Grafana starts.
- Modify `Makefile` so `lint` also covers `scripts`.
- Create `tests/unit/test_dashboard.py` and `tests/integration/test_grafana_import.py`.

**Tests to write first:**
- **Unit:**
  - The dashboard JSON loads.
  - Every panel target's `measurement` is in {`sensor_readings`, `sensor_readings_1m`, `alerts`}, and every selected field exists in the SPEC schema.
  - The `zone` template variable exists.
  - Every panel's `datasource` equals `industrial_iot`, the `grafana_import.py` default.
- **Integration:**
  - After running `grafana_import.main([...])` against `grafana:3000` twice (to check idempotence), `GET /api/dashboards/db/industrial-iot-floor` returns 200 with the expected title.
  - `GET /api/datasources/name/industrial_iot` returns 200.

**Acceptance:** `make test`

**Commit message:**
```
Add Grafana floor dashboard and HTTP API import script

Grafana 4.x lacks file provisioning, so a small script creates the
InfluxDB datasource and loads the per-zone and rollup dashboard.
```

---

## T12: Regenerate README from template with honest status

**Goal:** Replace `README.md` with the filled `tools/readme_template.md` format.

**Files:**
- Modify `README.md`.
- Create `tests/unit/test_readme.py`.
- Run `git add README.md tests/unit/test_readme.py` before generating the Layout block, so the tree includes the new test file. If the layout test then fails, regenerate the block, `git add` again and amend the task commit.

**Content rules:**
- Title "Industrial IoT Sensor Network". The one-paragraph description is written from SPEC Problem.
- The line "Personal project built on the 2017-era stack (Python 3.5, paho-mqtt 1.3, InfluxDB 1.3, Mosquitto 1.4, Grafana 4.6, Arduino)".
- **Status → Implemented:** one bullet per SPEC in-scope item, each mapped to a file and test.
- **Not implemented / known limitations:** every SPEC out-of-scope row and known limitation. It must explicitly state: "Arduino sensor nodes, the serial link and the Raspberry Pi gateway are simulated (`src/node_simulator.py`, pyserial `socket://`, x86 gateway container); the sketch is tested on the host with fake Arduino/Wire/DHT headers and has not been flashed to a board in this repo."
- **Built with:** the pinned versions from `requirements.txt` and the image tags.
- **Running it:** `make up` (which runs `$(COMPOSE) up -d --build`, with `COMPOSE ?= docker compose`) and `make smoke`.
- **Tests:** `make test`, plus one sentence saying unit, host-sketch and container integration tests are covered, and real hardware and CQ execution timing are not.
- **Layout:** generated with `git ls-files | tree --fromfile` or an equivalent Python one-liner run inside the container, then pasted in verbatim.
- No badges, no employer names, no role, no dates and no metrics. Remove the template comment block.

**Tests to write first:** `tests/unit/test_readme.py`:
- every repo path mentioned in README backticks exists;
- the README has no `shields.io`, `Organization` or `Developed during` text;
- the Layout block equals the sorted output of `git ls-files` rendered as a tree (skipped if `.git` is absent in the container).

**Acceptance:** `make test`

**Commit message:**
```
Rewrite README from template with implemented features and limits

Describe the simulated sensor pipeline, pinned stack, how to run and
test it, and a layout generated from the tracked files.
```

---

## Dependency order summary

| Task | Depends on |
|---|---|
| T1 | none |
| T2 | T1 |
| T3 | T2 |
| T4 | T1 (lint target from T2 not required) |
| T5 | T2 (parse_line) |
| T6 | T3, T5 |
| T7 | T2 |
| T8 | T1, T6 (fakes, integration conftest) |
| T9 | T6 (fakes), T7, T8 |
| T10 | T5, T6, T9 |
| T11 | T8, T10 |
| T12 | all of the above |

There are 12 tasks and 12 commits. `make test` is green after each one.
