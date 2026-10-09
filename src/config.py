"""INI configuration loading with environment-variable overrides.

``load(path)`` reads an INI file with the stdlib ``configparser`` and
returns a plain nested dict (``{section: {key: value}}``). Values that
look like integers become ``int``, values that look like decimals become
``float``, and everything in the ``[thresholds]`` and ``[trend]``
sections except ``window`` is a ``float``. Every section in the file is
kept, including ones this module does not know about.

The environment variables in ``ENV_OVERRIDES`` replace the matching INI
value when the section exists in the file. This is how Compose sets
host names, ports and zone ids per service.
"""

import configparser
import errno
import os
import re

ENV_OVERRIDES = (
    ('GATEWAY_ID', 'gateway', 'id'),
    ('GATEWAY_ZONE', 'gateway', 'zone'),
    ('SERIAL_URL', 'serial', 'url'),
    ('MQTT_HOST', 'mqtt', 'host'),
    ('MQTT_PORT', 'mqtt', 'port'),
    ('INFLUXDB_HOST', 'influxdb', 'host'),
    ('INFLUXDB_PORT', 'influxdb', 'port'),
    ('INFLUXDB_DATABASE', 'influxdb', 'database'),
)

INT_KEYS = frozenset([
    ('mqtt', 'port'),
    ('influxdb', 'port'),
])

FLOAT_SECTIONS = frozenset(['thresholds', 'trend'])
NON_FLOAT_KEYS = frozenset([('trend', 'window')])

_INT_RE = re.compile(r'^[+-]?\d+$')
_FLOAT_RE = re.compile(r'^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$')


def _coerce(section, key, text):
    value = text.strip()
    if section in FLOAT_SECTIONS and (section, key) not in NON_FLOAT_KEYS:
        if _FLOAT_RE.match(value):
            return float(value)
        return value
    if _INT_RE.match(value):
        return int(value)
    if _FLOAT_RE.match(value):
        return float(value)
    return value


def load(path, env=os.environ):
    """Load ``path`` and apply overrides from ``env``.

    Raises ``FileNotFoundError`` (with ``filename`` set to ``path``) when
    the file does not exist, and ``ValueError`` when a port override is
    not an integer.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            errno.ENOENT, 'configuration file not found', path)

    parser = configparser.ConfigParser(
        inline_comment_prefixes=(';', '#'), interpolation=None)
    with open(path, encoding='utf-8') as handle:
        parser.read_file(handle, source=path)

    cfg = {}
    for section in parser.sections():
        cfg[section] = dict(
            (key, _coerce(section, key, value))
            for key, value in parser.items(section))

    for var, section, key in ENV_OVERRIDES:
        if var not in env or section not in cfg:
            continue
        value = _coerce(section, key, env[var])
        if (section, key) in INT_KEYS and not isinstance(value, int):
            raise ValueError(
                '{} must be an integer, got {!r}'.format(var, env[var]))
        cfg[section][key] = value

    return cfg
