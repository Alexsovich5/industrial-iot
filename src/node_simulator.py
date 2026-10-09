"""TCP stand-in for the Arduino sensor node and its serial cable.

Each connection receives the sketch's ``# Sensor node initialized`` banner
followed by one ``SENSOR_ID,TEMP,HUMIDITY,VIBRATION`` line per interval,
formatted with the sketch's precision (1, 1 and 2 decimal places). The
gateway reads it with the pyserial URL ``socket://host:port``.

Profiles are seeded and deterministic:

* ``normal``          values wander around a steady operating point;
* ``overheat``        temperature ramps up past 45 C;
* ``humid``           humidity ramps up past 80 %;
* ``vibration-drift`` vibration rises slowly past 2.0 g and then 5.0 g;
* ``dropout``         normal values, but some intervals produce no line at
                      all, as the sketch does when the DHT read returns NaN.

``--noise`` is separate from the profiles: it injects garbage and blank
lines to model a noisy serial link. The real sketch never writes those.
"""

import argparse
import logging
import random
import socketserver
import sys
import threading

BANNER = '# Sensor node initialized'
LINE_END = '\r\n'
PROFILES = ('normal', 'overheat', 'humid', 'vibration-drift', 'dropout')

DROPOUT_RATE = 0.2

log = logging.getLogger('node_simulator')


def _clamp(value, low, high):
    return max(low, min(high, value))


def _format(sensor_id, temperature, humidity, vibration):
    return '{},{:.1f},{:.1f},{:.2f}'.format(sensor_id, temperature, humidity, vibration)


def generate(profile, sensor_id, seed):
    """Yield one item per reading interval, forever.

    Each item is a CSV line in the sketch's format, or ``None`` for an
    interval in which the node writes nothing (only the ``dropout`` profile
    produces these).
    """
    if profile not in PROFILES:
        raise ValueError('unknown profile {!r}; choose from {}'.format(
            profile, ', '.join(PROFILES)))
    rng = random.Random(seed)
    temperature = 22.0
    humidity = 45.0
    vibration = 0.10
    step = 0
    while True:
        if profile == 'overheat':
            temperature = 30.0 + 0.6 * step + rng.uniform(-0.3, 0.3)
        else:
            temperature = _clamp(temperature + rng.uniform(-0.2, 0.2), 20.5, 23.5)

        if profile == 'humid':
            humidity = 55.0 + 0.4 * step + rng.uniform(-0.5, 0.5)
        else:
            humidity = _clamp(humidity + rng.uniform(-0.5, 0.5), 40.0, 50.0)

        if profile == 'vibration-drift':
            vibration = 0.20 + 0.08 * step + rng.uniform(-0.03, 0.03)
        else:
            vibration = _clamp(vibration + rng.uniform(-0.02, 0.02), 0.05, 0.20)

        step += 1
        if profile == 'dropout' and rng.random() < DROPOUT_RATE:
            yield None
            continue
        yield _format(sensor_id,
                      _clamp(temperature, -40.0, 79.0),
                      _clamp(humidity, 0.0, 99.0),
                      _clamp(vibration, 0.0, 27.0))


_GARBAGE_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.#?~'


def _noise_line(rng):
    kind = rng.randrange(3)
    if kind == 0:
        return ''
    if kind == 1:
        # Line truncated mid-field: too few fields to parse.
        return 'SN-0{}'.format(rng.choice(['', '0', '01,2', '01,23.', '01,23.4,4']))
    # Corrupted bytes with no field separators.
    return ''.join(rng.choice(_GARBAGE_CHARS) for _ in range(rng.randint(1, 12)))


def with_noise(lines, rate, seed):
    """Serial-noise injector: pass ``lines`` through, inserting garbage or
    blank lines before an item with probability ``rate``.

    With ``rate`` of 0 the input is returned unchanged.
    """
    if rate <= 0:
        for line in lines:
            yield line
        return
    rng = random.Random(seed)
    for line in lines:
        if rng.random() < rate:
            yield _noise_line(rng)
        yield line


class _NodeHandler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        try:
            items = server.line_factory()
            self.request.sendall((BANNER + LINE_END).encode('ascii'))
            for item in items:
                if server.stopping.wait(server.interval):
                    return
                if item is not None:
                    self.request.sendall((item + LINE_END).encode('ascii'))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            log.info('client %s disconnected', self.client_address)
        except Exception as exc:
            server.errors.append(exc)
            log.exception('error while serving %s', self.client_address)


class NodeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, line_factory, interval):
        self.line_factory = line_factory
        self.interval = interval
        self.stopping = threading.Event()
        self.errors = []
        self.thread = None
        socketserver.ThreadingTCPServer.__init__(self, address, _NodeHandler)

    def shutdown(self):
        self.stopping.set()
        socketserver.ThreadingTCPServer.shutdown(self)


def serve(host, port, line_factory, interval):
    """Start a simulator server in a background thread and return it.

    ``line_factory`` is called once per connection and must return a new
    iterator of lines (``None`` items are silent intervals). Stop the server
    with ``shutdown()`` and ``server_close()``.
    """
    server = NodeServer((host, port), line_factory, interval)
    server.thread = threading.Thread(target=server.serve_forever, name='node-simulator')
    server.thread.daemon = True
    server.thread.start()
    return server


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=7000)
    parser.add_argument('--sensor-id', default='SN-001')
    parser.add_argument('--interval', type=float, default=5.0,
                        help='seconds between readings (the sketch uses 5)')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--profile', choices=PROFILES, default='normal')
    parser.add_argument('--noise', type=float, default=0.0,
                        help='serial-noise injection rate (0 disables it)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(name)s %(levelname)s %(message)s')

    def line_factory():
        lines = generate(args.profile, args.sensor_id, args.seed)
        if args.noise > 0:
            return with_noise(lines, args.noise, args.seed)
        return lines

    if args.noise > 0:
        log.warning('serial-noise injection enabled at rate %.3f', args.noise)
    server = serve(args.host, args.port, line_factory, args.interval)
    log.info('simulating %s (%s) on %s:%d every %.2fs', args.sensor_id, args.profile,
             args.host, server.server_address[1], args.interval)
    try:
        server.thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
