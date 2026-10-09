"""grafana_import.py keeps credentials out of its logs and error messages."""

import json
import logging
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scripts import grafana_import

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DASHBOARD_PATH = os.path.join(ROOT, 'grafana', 'dashboard.json')
SENTINEL = 'S3NTINEL-pw'


def closed_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, status, body):
        data = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._reply(200, {'database': 'ok'})

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        self.rfile.read(length)
        self._reply(self.server.post_status, {'message': 'rejected'})


@pytest.fixture
def fake_grafana():
    server = HTTPServer(('127.0.0.1', 0), _Handler)
    server.post_status = 500
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize('url,expected', [
    ('http://grafana:3000', 'http://grafana:3000'),
    ('http://admin:{}@grafana:3000'.format(SENTINEL), 'http://<redacted>@grafana:3000'),
    ('https://grafana/sub?token={}'.format(SENTINEL), 'https://grafana/<redacted>'),
])
def test_redact_url_hides_userinfo_path_and_query(url, expected):
    assert grafana_import.redact_url(url) == expected


def run_main(argv, caplog, capsys):
    with caplog.at_level(logging.DEBUG):
        status = grafana_import.main(argv)
    out, err = capsys.readouterr()
    return status, caplog.text + out + err


def test_unreachable_grafana_error_does_not_leak_credentials(caplog, capsys):
    url = 'http://admin:{}@127.0.0.1:{}'.format(SENTINEL, closed_port())
    status, output = run_main(['--url', url, '--password', SENTINEL, '--wait', '0',
                               '--dashboard', DASHBOARD_PATH], caplog, capsys)
    assert status == 1
    assert 'not healthy' in output
    assert SENTINEL not in output


@pytest.mark.parametrize('post_status', [401, 500])
def test_rejected_datasource_error_does_not_leak_credentials(fake_grafana, post_status,
                                                             caplog, capsys):
    fake_grafana.post_status = post_status
    url = 'http://admin:{}@127.0.0.1:{}'.format(SENTINEL, fake_grafana.server_address[1])
    status, output = run_main(['--url', url, '--password', SENTINEL, '--wait', '5',
                               '--dashboard', DASHBOARD_PATH], caplog, capsys)
    assert status == 1
    assert 'datasource create failed: HTTP {}'.format(post_status) in output
    assert SENTINEL not in output
