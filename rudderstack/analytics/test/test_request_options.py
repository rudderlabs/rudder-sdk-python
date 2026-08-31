"""Request option tests without credentials or external network access."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import gzip
import json
import socket
from threading import Thread
import unittest
from unittest import mock

import requests

from rudderstack.analytics.client import Client
from rudderstack.analytics.consumer import Consumer
from rudderstack.analytics.request import post


class TestRequestOptions(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch('rudderstack.analytics.request._session.post')
        self.session_post = patcher.start()
        self.addCleanup(patcher.stop)
        self.session_post.return_value = mock.Mock(status_code=200)

    def test_legacy_proxy_strings(self):
        for value, expected in (
            ('proxy.example:8080', 'http://proxy.example:8080'),
            ('http://proxy.example:8080', 'http://proxy.example:8080'),
            ('https://proxy.example:8080', 'https://proxy.example:8080'),
            ('socks5://proxy.example:1080', 'socks5://proxy.example:1080'),
        ):
            with self.subTest(proxy=value):
                post('test-key', proxies=value, batch=[])
                self.assertEqual(self.session_post.call_args.kwargs['proxies'],
                                 {'http': expected, 'https': expected})

    def test_proxy_mapping_is_not_modified(self):
        proxies = {'http': 'http://proxy.example:8080',
                   'https': 'http://secure-proxy.example:8080'}
        original = proxies.copy()
        post('test-key', proxies=proxies, batch=[])
        self.assertIs(self.session_post.call_args.kwargs['proxies'], proxies)
        self.assertEqual(proxies, original)

    def test_empty_proxy_configuration_is_omitted(self):
        for proxies in (None, '', {}):
            with self.subTest(proxies=proxies):
                post('test-key', proxies=proxies, batch=[])
                self.assertNotIn('proxies', self.session_post.call_args.kwargs)

    def test_default_and_custom_timeouts(self):
        post('test-key', batch=[])
        self.assertEqual(self.session_post.call_args.kwargs['timeout'], 15)
        post('test-key', timeout=7.5, batch=[])
        self.assertEqual(self.session_post.call_args.kwargs['timeout'], 7.5)

    def test_sync_client_forwards_legacy_proxy_and_timeout(self):
        client = Client('test-key', sync_mode=True,
                        proxies='proxy.example:8080', timeout=7.5)
        success, message = client.track('user-id', 'test event')
        self.assertIs(success, True)
        self.assertEqual(message['type'], 'track')
        self.assertEqual(self.session_post.call_args.kwargs['proxies'],
                         {'http': 'http://proxy.example:8080',
                          'https': 'http://proxy.example:8080'})
        self.assertEqual(self.session_post.call_args.kwargs['timeout'], 7.5)

    def test_consumer_forwards_legacy_proxy_and_timeout(self):
        consumer = Consumer(None, 'test-key', proxies='proxy.example:8080',
                            timeout=7.5, retries=0)
        consumer.request([{'type': 'track', 'event': 'test event'}])
        self.assertEqual(self.session_post.call_args.kwargs['proxies'],
                         {'http': 'http://proxy.example:8080',
                          'https': 'http://proxy.example:8080'})
        self.assertEqual(self.session_post.call_args.kwargs['timeout'], 7.5)


class TestProxyTransport(unittest.TestCase):
    def test_real_requests_routes_through_proxy(self):
        received = []
        getaddrinfo = socket.getaddrinfo

        def local_only(host, *args, **kwargs):
            self.assertEqual(host, '127.0.0.1',
                             'Unexpected external connection')
            return getaddrinfo(host, *args, **kwargs)

        patcher = mock.patch('socket.getaddrinfo', side_effect=local_only)
        patcher.start()
        self.addCleanup(patcher.stop)

        class ProxyHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                if self.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
                received.append((self.path, json.loads(body)))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), ProxyHandler)
        thread = Thread(target=server.serve_forever,
                        kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        try:
            address = '127.0.0.1:{}'.format(server.server_port)
            with requests.Session() as session:
                session.trust_env = False
                with mock.patch('rudderstack.analytics.request._session',
                                session):
                    for proxies in (address, 'http://' + address,
                                    {'http': 'http://' + address}):
                        for compressed in (False, True):
                            with self.subTest(proxies=proxies,
                                              gzip=compressed):
                                response = post(
                                    'test-key', host='http://data.example',
                                    proxies=proxies, timeout=2,
                                    gzip=compressed, batch=[])
                                self.assertEqual(response.status_code, 200)
                                path, payload = received[-1]
                                self.assertEqual(
                                    path, 'http://data.example/v1/batch')
                                self.assertEqual(payload['batch'], [])
                                self.assertIn('sentAt', payload)
                                self.assertNotIn('proxies', payload)
                                self.assertNotIn('timeout', payload)
            self.assertEqual(len(received), 6)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
