"""Edge-triggered alert rules for sensor readings.

The engine has no I/O. It takes validated data-topic payloads (dicts as
returned by ``readings.from_payload``) and returns the alert events they
cause. State is kept per ``(zone, sensor_id)``:

- threshold rules for temperature, humidity and vibration, which raise
  when a value goes above its ``<metric>_max`` limit and clear on the first
  reading back at or below it;
- a vibration trend rule, which raises when the rolling mean of the last
  ``trend_window`` vibration values goes above ``vibration_warn`` and
  clears when it falls back. It does not fire until the window is full.

Each rule emits one ``raised`` event on its first breach and one ``cleared``
event on recovery, never a repeat while the state is unchanged.
"""

import collections

AlertEvent = collections.namedtuple('AlertEvent', [
    'zone', 'sensor_id', 'gateway', 'kind', 'metric', 'state',
    'value', 'limit', 'message', 'timestamp',
])

THRESHOLD_METRICS = ('temperature', 'humidity', 'vibration')

RAISED = 'raised'
CLEARED = 'cleared'
THRESHOLD = 'threshold'
TREND = 'trend'


def _number(value):
    """Format a value for a message with at most two decimals, e.g. 46.0 or 2.55."""
    text = '{:.2f}'.format(value).rstrip('0')
    if text.endswith('.'):
        text += '0'
    return text


class _SensorState(object):
    def __init__(self, window):
        self.vibrations = collections.deque(maxlen=window)
        self.active = set()


class AlertEngine(object):
    def __init__(self, thresholds, trend_window, vibration_warn):
        trend_window = int(trend_window)
        if trend_window < 1:
            raise ValueError('trend_window must be at least 1, got {}'.format(trend_window))
        self.limits = collections.OrderedDict(
            (metric, float(thresholds['{}_max'.format(metric)]))
            for metric in THRESHOLD_METRICS)
        self.trend_window = trend_window
        self.vibration_warn = float(vibration_warn)
        self._state = {}

    def _sensor_state(self, zone, sensor_id):
        key = (zone, sensor_id)
        state = self._state.get(key)
        if state is None:
            state = _SensorState(self.trend_window)
            self._state[key] = state
        return state

    def evaluate(self, payload):
        """Return the list of AlertEvents caused by one reading payload."""
        state = self._sensor_state(payload['zone'], payload['sensor_id'])
        events = []

        for metric, limit in self.limits.items():
            value = float(payload[metric])
            event = self._edge(state, payload, THRESHOLD, metric, value, limit, metric)
            if event is not None:
                events.append(event)

        state.vibrations.append(float(payload['vibration']))
        if len(state.vibrations) == self.trend_window:
            mean = sum(state.vibrations) / len(state.vibrations)
            event = self._edge(state, payload, TREND, 'vibration', mean,
                               self.vibration_warn, 'vibration rolling mean')
            if event is not None:
                events.append(event)

        return events

    def _edge(self, state, payload, kind, metric, value, limit, label):
        key = (kind, metric)
        breached = value > limit
        active = key in state.active
        if breached == active:
            return None
        if breached:
            state.active.add(key)
            new_state = RAISED
            message = '{} {} above {}'.format(label, _number(value), _number(limit))
        else:
            state.active.discard(key)
            new_state = CLEARED
            message = '{} {} back below {}'.format(label, _number(value), _number(limit))
        return AlertEvent(
            zone=payload['zone'],
            sensor_id=payload['sensor_id'],
            gateway=payload.get('gateway'),
            kind=kind,
            metric=metric,
            state=new_state,
            value=value,
            limit=limit,
            message=message,
            timestamp=payload.get('timestamp'),
        )
