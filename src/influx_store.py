"""InfluxDB schema setup and point writing for readings and alerts.

The database gets two retention policies: ``raw`` (7 days, the default)
holds every reading and alert, and ``rollup`` (52 weeks) holds the
1-minute means written by the ``cq_readings_1m`` continuous query.
"""

RAW_RP = 'raw'
RAW_DURATION = '7d'
ROLLUP_RP = 'rollup'
ROLLUP_DURATION = '52w'
REPLICATION = 1

READINGS_MEASUREMENT = 'sensor_readings'
ALERTS_MEASUREMENT = 'alerts'

CQ_NAME = 'cq_readings_1m'
CQ_TEMPLATE = (
    'CREATE CONTINUOUS QUERY {name} ON "{db}" BEGIN\n'
    '  SELECT mean(temperature) AS temperature, mean(humidity) AS humidity,\n'
    '         mean(vibration) AS vibration, max(vibration) AS vibration_max\n'
    '  INTO "{db}"."rollup".sensor_readings_1m\n'
    '  FROM "{db}"."raw".sensor_readings GROUP BY time(1m), *\n'
    'END'
)

TIME_PRECISION = 'u'


class InfluxStore(object):
    def __init__(self, client, database):
        self.client = client
        self.database = database

    def continuous_query(self):
        """Return the CREATE CONTINUOUS QUERY statement for this database."""
        return CQ_TEMPLATE.format(name=CQ_NAME, db=self.database)

    def ensure_schema(self):
        """Create the database, retention policies and continuous query if missing."""
        existing = [db['name'] for db in self.client.get_list_database()]
        if self.database not in existing:
            self.client.create_database(self.database)

        policies = [rp['name'] for rp in self.client.get_list_retention_policies(self.database)]
        if RAW_RP not in policies:
            self.client.create_retention_policy(
                RAW_RP, RAW_DURATION, REPLICATION, database=self.database, default=True)
        if ROLLUP_RP not in policies:
            self.client.create_retention_policy(
                ROLLUP_RP, ROLLUP_DURATION, REPLICATION, database=self.database, default=False)

        if not self._has_continuous_query():
            self.client.query(self.continuous_query())

    def _has_continuous_query(self):
        result = self.client.query('SHOW CONTINUOUS QUERIES')
        names = [cq['name'] for cq in result.get_points(measurement=self.database)]
        return CQ_NAME in names

    def reading_point(self, payload):
        return {
            'measurement': READINGS_MEASUREMENT,
            'tags': {
                'gateway': payload['gateway'],
                'zone': payload['zone'],
                'sensor': payload['sensor_id'],
            },
            'fields': {
                'temperature': float(payload['temperature']),
                'humidity': float(payload['humidity']),
                'vibration': float(payload['vibration']),
            },
            'time': payload['timestamp'],
        }

    def alert_point(self, event):
        return {
            'measurement': ALERTS_MEASUREMENT,
            'tags': {
                'zone': event.zone,
                'sensor': event.sensor_id,
                'metric': event.metric,
                'kind': event.kind,
                'state': event.state,
            },
            'fields': {
                'value': float(event.value),
                'limit': float(event.limit),
                'message': event.message,
            },
            'time': event.timestamp,
        }

    def _write(self, point):
        self.client.write_points(
            [point], time_precision=TIME_PRECISION, database=self.database)

    def write_reading(self, payload):
        self._write(self.reading_point(payload))

    def write_alert(self, event):
        self._write(self.alert_point(event))
