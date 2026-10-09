COMPOSE ?= docker compose

.PHONY: build test up down smoke check lint unit

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

check: lint unit

lint:
	flake8 src tests
	python -m compileall -q src

unit:
	python -m pytest tests/unit
