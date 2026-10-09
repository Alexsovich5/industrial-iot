COMPOSE ?= docker compose

.PHONY: build test up down smoke check lint unit arduino integration

# Host targets (run Docker)

build:
	$(COMPOSE) build tests

test: build
	$(COMPOSE) run --rm tests make check

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

smoke:
	$(COMPOSE) exec influxdb influx -database industrial_iot \
		-execute 'SELECT last(temperature),last(vibration) FROM sensor_readings GROUP BY zone,sensor'

# In-container targets (run inside the tests image)

check: lint unit arduino integration

lint:
	flake8 src tests scripts
	python -m compileall -q src scripts

unit:
	python -m pytest tests/unit

arduino:
	mkdir -p build
	g++ -std=c++11 -Wall -Werror -Itests/arduino/stubs -Iarduino -x c++ \
		tests/arduino/test_sensor_node.cpp -o build/test_sensor_node \
		&& build/test_sensor_node

integration:
	python -m pytest tests/integration
