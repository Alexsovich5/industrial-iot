import itertools
import socket

import pytest

import node_simulator
import readings


BANNER = '# Sensor node initialized'


def take(iterator, count):
    return list(itertools.islice(iterator, count))


def data_lines(items):
    return [item for item in items if item is not None]


def parsed(lines, field):
    return [getattr(readings.parse_line(line), field) for line in lines]


def test_same_seed_gives_same_first_50_lines():
    first = take(node_simulator.generate('normal', 'SN-001', 7), 50)
    second = take(node_simulator.generate('normal', 'SN-001', 7), 50)
    assert first == second
    other = take(node_simulator.generate('normal', 'SN-001', 8), 50)
    assert first != other


def test_normal_lines_parse_and_validate_with_sketch_precision():
    lines = take(node_simulator.generate('normal', 'SN-007', 1), 300)
    assert None not in lines
    for line in lines:
        assert not line.startswith('#')
        reading = readings.parse_line(line)
        assert reading is not None, line
        assert reading.sensor_id == 'SN-007'
        assert readings.validate(reading) == [], line
        sensor_id, temp, humidity, vibration = line.split(',')
        assert len(temp.split('.')[1]) == 1
        assert len(humidity.split('.')[1]) == 1
        assert len(vibration.split('.')[1]) == 2


def test_overheat_exceeds_45_within_60_lines():
    lines = take(node_simulator.generate('overheat', 'SN-001', 3), 60)
    temps = parsed(lines, 'temperature')
    assert temps[0] < 45.0
    assert max(temps) > 45.0


def test_humid_exceeds_80_percent():
    lines = take(node_simulator.generate('humid', 'SN-001', 3), 120)
    humidity = parsed(lines, 'humidity')
    assert humidity[0] < 80.0
    assert max(humidity) > 80.0
    for line in lines:
        assert readings.validate(readings.parse_line(line)) == []


def test_vibration_drift_passes_warn_before_max():
    lines = take(node_simulator.generate('vibration-drift', 'SN-001', 5), 200)
    vibration = parsed(lines, 'vibration')
    first_warn = next(i for i, v in enumerate(vibration) if v > 2.0)
    first_max = next(i for i, v in enumerate(vibration) if v > 5.0)
    assert vibration[0] < 2.0
    assert first_warn < first_max
    for line in lines:
        assert readings.validate(readings.parse_line(line)) == []


def test_dropout_skips_intervals_and_emits_only_valid_lines():
    intervals = take(node_simulator.generate('dropout', 'SN-001', 11), 200)
    emitted = data_lines(intervals)
    assert 0 < len(emitted) < 200
    for line in emitted:
        reading = readings.parse_line(line)
        assert reading is not None, line
        assert readings.validate(reading) == []


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError):
        next(node_simulator.generate('nope', 'SN-001', 1))


def test_noise_injects_unparseable_lines():
    clean = take(node_simulator.generate('normal', 'SN-001', 2), 200)
    noisy = take(node_simulator.with_noise(iter(clean), 0.2, 9), 200)
    assert any(readings.parse_line(line) is None for line in noisy)
    # Original readings still come through, in order, between the noise.
    kept = [line for line in noisy if readings.parse_line(line) is not None]
    assert kept == clean[:len(kept)]


def test_zero_noise_leaves_input_unchanged():
    clean = take(node_simulator.generate('dropout', 'SN-001', 2), 200)
    assert list(node_simulator.with_noise(iter(clean), 0.0, 9)) == clean


def read_lines(port, count, timeout=5.0):
    sock = socket.create_connection(('127.0.0.1', port), timeout=timeout)
    try:
        stream = sock.makefile('r', encoding='ascii', newline='')
        return [stream.readline().rstrip('\r\n') for _ in range(count)]
    finally:
        sock.close()


@pytest.fixture
def server():
    created = []

    def start(factory, interval=0.01):
        srv = node_simulator.serve('127.0.0.1', 0, factory, interval)
        created.append(srv)
        return srv

    yield start
    for srv in created:
        srv.shutdown()
        srv.server_close()


def test_serve_sends_banner_then_lines(server):
    srv = server(lambda: node_simulator.generate('normal', 'SN-001', 4))
    port = srv.server_address[1]
    lines = read_lines(port, 4)
    expected = take(node_simulator.generate('normal', 'SN-001', 4), 3)
    assert lines[0] == BANNER
    assert lines[1:] == expected


def test_sequential_clients_each_get_their_own_iterator(server):
    srv = server(lambda: node_simulator.generate('normal', 'SN-001', 4))
    port = srv.server_address[1]
    first = read_lines(port, 4)
    second = read_lines(port, 4)
    assert first[0] == BANNER
    assert first == second
    assert srv.errors == []


def test_cli_parses_spec_options():
    args = node_simulator.parse_args([
        '--port', '7001', '--sensor-id', 'SN-002', '--interval', '0.5',
        '--seed', '3', '--profile', 'vibration-drift', '--noise', '0.1'])
    assert args.port == 7001
    assert args.sensor_id == 'SN-002'
    assert args.interval == 0.5
    assert args.seed == 3
    assert args.profile == 'vibration-drift'
    assert args.noise == 0.1
    defaults = node_simulator.parse_args([])
    assert defaults.port == 7000
    assert defaults.profile == 'normal'
    assert defaults.noise == 0.0
    assert defaults.interval == 5.0
