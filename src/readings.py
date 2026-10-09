"""Sensor-node reading protocol.

Parses the CSV lines written by the Arduino sketch
(``SENSOR_ID,TEMP,HUMIDITY,VIBRATION``), range-checks the values against
the sensor limits and converts readings to and from the MQTT JSON payload.
"""

import collections
import json
import math
import re

Reading = collections.namedtuple(
    'Reading', ['sensor_id', 'temperature', 'humidity', 'vibration'])

SENSOR_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')

# Inclusive limits from the sensor datasheets: DHT22 temperature and
# humidity, and the vibration magnitude of an ADXL345 set to +/-16 g.
LIMITS = collections.OrderedDict([
    ('temperature', (-40.0, 80.0)),
    ('humidity', (0.0, 100.0)),
    ('vibration', (0.0, 28.0)),
])

NUMERIC_KEYS = ('temperature', 'humidity', 'vibration')
STRING_KEYS = ('gateway', 'zone', 'sensor_id', 'timestamp')


def _finite_float(text):
    value = float(text)
    if math.isnan(value) or math.isinf(value):
        raise ValueError('non-finite value: {!r}'.format(text))
    return value


def parse_line(line):
    """Return a Reading for one sketch line, or None if it is not a reading.

    Blank lines, ``#`` comment lines, lines with the wrong number of fields,
    non-numeric or non-finite values and invalid sensor IDs give None.
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    parts = [part.strip() for part in line.split(',')]
    if len(parts) != 4:
        return None
    sensor_id = parts[0]
    if not SENSOR_ID_RE.match(sensor_id):
        return None
    try:
        values = [_finite_float(part) for part in parts[1:]]
    except ValueError:
        return None
    return Reading(sensor_id, *values)


def validate(reading):
    """Return a list of range problems; an empty list means the reading is valid."""
    problems = []
    for name, (low, high) in LIMITS.items():
        value = getattr(reading, name)
        if not low <= value <= high:
            problems.append('{} {} outside {}..{}'.format(name, value, low, high))
    return problems


def to_payload(reading, gateway, zone, now):
    """Serialise a reading to the JSON payload published on the data topic.

    ``now`` is a naive UTC datetime; the timestamp is written in ISO 8601
    with a trailing ``Z``.
    """
    data = collections.OrderedDict([
        ('gateway', gateway),
        ('zone', zone),
        ('sensor_id', reading.sensor_id),
        ('temperature', float(reading.temperature)),
        ('humidity', float(reading.humidity)),
        ('vibration', float(reading.vibration)),
        ('timestamp', now.isoformat() + 'Z'),
    ])
    return json.dumps(data)


def from_payload(text):
    """Parse a data-topic payload into a dict, raising ValueError if it is malformed."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError('payload is not valid JSON: {}'.format(exc))
    if not isinstance(data, dict):
        raise ValueError('payload is not a JSON object')

    missing = [key for key in STRING_KEYS + NUMERIC_KEYS if key not in data]
    if missing:
        raise ValueError('payload missing keys: {}'.format(', '.join(sorted(missing))))

    for key in STRING_KEYS:
        if not isinstance(data[key], str):
            raise ValueError('payload field {} is not a string'.format(key))
    for key in NUMERIC_KEYS:
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('payload field {} is not a number'.format(key))
        data[key] = float(value)
    return data
