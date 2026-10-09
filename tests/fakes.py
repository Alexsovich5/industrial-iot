"""In-memory stand-ins for the paho MQTT client and the InfluxDB client."""

import collections
import re

from influxdb.resultset import ResultSet

PublishedMessage = collections.namedtuple('PublishedMessage', ['topic', 'payload', 'qos'])
FakeMessage = collections.namedtuple('FakeMessage', ['topic', 'payload', 'qos'])


class FakeMessageInfo(object):
    """Mimics paho's MQTTMessageInfo for a message that is delivered at once."""

    def __init__(self, mid):
        self.mid = mid
        self.rc = 0

    def is_published(self):
        return True

    def wait_for_publish(self):
        return None


class FakeMqttClient(object):
    """Records calls made on a paho ``Client`` and can fire its callbacks."""

    def __init__(self, client_id='', **kwargs):
        self.client_id = client_id
        self.kwargs = kwargs
        self.connected_to = None
        self.published = []
        self.subscriptions = []
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None
        self.userdata = None

    def connect(self, host, port=1883, keepalive=60, **kwargs):
        self.connected_to = (host, port, keepalive)
        return 0

    def disconnect(self):
        self.disconnected = True
        return 0

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self, force=False):
        self.loop_stopped = True

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append(PublishedMessage(topic, payload, qos))
        return FakeMessageInfo(len(self.published))

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        return (0, len(self.subscriptions))

    def fire_connect(self, rc=0):
        if self.on_connect is not None:
            self.on_connect(self, self.userdata, {}, rc)

    def fire_message(self, topic, payload, qos=0):
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        if self.on_message is not None:
            self.on_message(self, self.userdata, FakeMessage(topic, payload, qos))


class FakeInfluxClient(object):
    """Records the InfluxDBClient calls the processor and store make.

    It keeps enough state (databases, retention policies and continuous
    queries) to answer the ``get_list_*`` and ``SHOW CONTINUOUS QUERIES``
    calls the way the real server does.
    """

    def __init__(self, host='localhost', port=8086, database=None, **kwargs):
        self.host = host
        self.port = port
        self.database = database
        self.databases = []
        self.retention_policies = []
        self.continuous_queries = []
        self.points = []
        self.writes = []
        self.queries = []
        self.calls = []
        self.query_results = []

    def get_list_database(self):
        return [{'name': name} for name in self.databases]

    def create_database(self, name):
        self.calls.append(('create_database', name))
        if name not in self.databases:
            self.databases.append(name)

    def get_list_retention_policies(self, database=None):
        database = database or self.database
        return [{'name': rp['name'], 'duration': rp['duration'], 'default': rp['default']}
                for rp in self.retention_policies if rp['database'] == database]

    def create_retention_policy(self, name, duration, replication, database=None,
                                default=False):
        self.calls.append(('create_retention_policy', name))
        self.retention_policies.append(
            {'name': name, 'duration': duration, 'replication': replication,
             'database': database or self.database, 'default': default})

    def write_points(self, points, time_precision=None, database=None,
                     retention_policy=None, **kwargs):
        self.writes.append({'time_precision': time_precision, 'database': database,
                            'retention_policy': retention_policy})
        for point in points:
            self.points.append((retention_policy, point))
        return True

    def query(self, query, **kwargs):
        self.queries.append(query)
        if self.query_results:
            return self.query_results.pop(0)
        text = query.strip()
        upper = text.upper()
        if upper.startswith('CREATE CONTINUOUS QUERY'):
            self.calls.append(('create_continuous_query', text))
            match = re.match(r'CREATE CONTINUOUS QUERY\s+"?(\w+)"?\s+ON\s+"?(\w+)"?', text,
                             re.IGNORECASE)
            self.continuous_queries.append((match.group(2), match.group(1), text))
        elif upper == 'SHOW CONTINUOUS QUERIES':
            return self._show_continuous_queries()
        return ResultSet({})

    def _show_continuous_queries(self):
        names = list(self.databases)
        for database, _, _ in self.continuous_queries:
            if database not in names:
                names.append(database)
        series = []
        for database in names:
            values = [[name, text] for db, name, text in self.continuous_queries
                      if db == database]
            entry = {'name': database, 'columns': ['name', 'query']}
            if values:
                entry['values'] = values
            series.append(entry)
        return ResultSet({'series': series})
