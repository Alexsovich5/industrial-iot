"""In-memory stand-ins for the paho MQTT client and the InfluxDB client."""

import collections

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
    """Records the InfluxDBClient calls the processor and store make."""

    def __init__(self, host='localhost', port=8086, database=None, **kwargs):
        self.host = host
        self.port = port
        self.database = database
        self.databases = []
        self.retention_policies = []
        self.points = []
        self.queries = []
        self.query_results = []

    def get_list_database(self):
        return [{'name': name} for name in self.databases]

    def create_database(self, name):
        if name not in self.databases:
            self.databases.append(name)

    def create_retention_policy(self, name, duration, replication, database=None,
                                default=False):
        self.retention_policies.append(
            {'name': name, 'duration': duration, 'replication': replication,
             'database': database, 'default': default})

    def write_points(self, points, time_precision=None, database=None,
                     retention_policy=None, **kwargs):
        for point in points:
            self.points.append((retention_policy, point))
        return True

    def query(self, query, **kwargs):
        self.queries.append(query)
        if self.query_results:
            return self.query_results.pop(0)
        return []
