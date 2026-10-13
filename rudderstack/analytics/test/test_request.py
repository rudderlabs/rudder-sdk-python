from datetime import datetime, date
import base64
import unittest
from unittest import mock
import json
import requests

from rudderstack.analytics.request import (
    APIError, DatetimeSerializer, UploadError, _gzip_json, post)
from rudderstack.analytics.test.test_constants import TEST_PROXY


TEST_WRITE_KEY = 'test-write-key'
TEST_DATA_PLANE_URL = 'https://example.test'


class TestRequests(unittest.TestCase):

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_valid_request(self, session_post):
        session_post.return_value = mock.Mock(status_code=200)

        res = post(TEST_WRITE_KEY, host=TEST_DATA_PLANE_URL, batch=[{
            'userId': 'userId',
            'event': 'python event',
            'type': 'track'
        }])
        self.assertEqual(res.status_code, 200)

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_json_error_response(self, session_post):
        response = mock.Mock(status_code=401)
        response.json.return_value = {
            'code': 'invalid_write_key',
            'message': 'Invalid write key',
        }
        session_post.return_value = response

        with self.assertRaises(APIError) as raised:
            post(TEST_WRITE_KEY, host=TEST_DATA_PLANE_URL, batch=[])

        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.code, 'invalid_write_key')
        self.assertEqual(raised.exception.message, 'Invalid write key')

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_non_json_error_response(self, session_post):
        response = mock.Mock(status_code=502, text='Bad gateway')
        response.json.side_effect = ValueError('invalid JSON')
        session_post.return_value = response

        with self.assertRaises(APIError) as raised:
            post(TEST_WRITE_KEY, host=TEST_DATA_PLANE_URL, batch=[])

        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.code, 'unknown')
        self.assertEqual(raised.exception.message, 'Bad gateway')

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_request_error_is_sanitized(self, session_post):
        write_key = 'rk_live_SECRET_SHOULD_NOT_APPEAR'
        request = requests.Request('POST', TEST_DATA_PLANE_URL).prepare()
        request.headers['Authorization'] = 'Basic encoded-secret'
        session_post.side_effect = requests.ConnectionError(
            'failed with {0}; Authorization: Basic encoded-secret'.format(
                write_key),
            request=request)

        with self.assertRaises(UploadError) as raised:
            post(write_key, host=TEST_DATA_PLANE_URL, batch=[])

        error = raised.exception
        self.assertEqual(str(error),
                         '[rudderstack] upload failed (ConnectionError)')
        self.assertNotIn(write_key, str(error))
        self.assertNotIn(write_key, repr(error))
        self.assertNotIn('Authorization', str(error))
        self.assertFalse(hasattr(error, 'request'))
        self.assertFalse(hasattr(error, 'response'))

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_timeout_and_proxy_errors_are_sanitized(self, session_post):
        write_key = 'rk_live_SECRET_SHOULD_NOT_APPEAR'
        for error_type in (requests.ReadTimeout,
                           requests.exceptions.ProxyError):
            with self.subTest(error_type=error_type):
                session_post.side_effect = error_type(
                    'Authorization: Bearer {0}'.format(write_key))
                with self.assertRaises(UploadError) as raised:
                    post(write_key, host=TEST_DATA_PLANE_URL, batch=[])
                self.assertNotIn(write_key, str(raised.exception))
                self.assertNotIn('Authorization', str(raised.exception))
                self.assertIn(error_type.__name__, str(raised.exception))

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_error_response_redacts_credentials(self, session_post):
        write_key = 'rk_live_SECRET_SHOULD_NOT_APPEAR'
        encoded_key = base64.b64encode(
            ('{0}:'.format(write_key)).encode('utf-8')).decode('ascii')
        response = mock.Mock(status_code=401)
        response.json.return_value = {
            'code': 'invalid_write_key',
            'message': 'Authorization: Basic encoded {0}'.format(write_key),
        }
        session_post.return_value = response

        with self.assertRaises(APIError) as raised:
            post(write_key, host=TEST_DATA_PLANE_URL, batch=[])

        self.assertNotIn(write_key, str(raised.exception))
        self.assertNotIn(write_key, repr(raised.exception))
        self.assertNotIn('encoded', str(raised.exception))

        for echoed_headers in (
                "{'Authorization': 'Basic dict-secret'}",
                '{"Authorization":"Basic json-secret"}',
                'base64 credential {0}'.format(encoded_key)):
            with self.subTest(echoed_headers=echoed_headers):
                response.json.return_value = {
                    'code': 'invalid_write_key',
                    'message': echoed_headers,
                }
                with self.assertRaises(APIError) as raised:
                    post(write_key, host=TEST_DATA_PLANE_URL, batch=[])
                exposed = str(raised.exception) + repr(raised.exception)
                self.assertNotIn('dict-secret', exposed)
                self.assertNotIn('json-secret', exposed)
                self.assertNotIn(encoded_key, exposed)
                self.assertIn('[REDACTED]', exposed)

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_malformed_json_error_response_raises_api_error(self, session_post):
        for payload in ({'error': 'upstream failed'}, {'unexpected': 'shape'},
                        ['bad', 'gateway']):
            with self.subTest(payload=payload):
                response = mock.Mock(status_code=502, text='Bad gateway')
                response.json.return_value = payload
                session_post.return_value = response

                with self.assertRaises(APIError) as raised:
                    post(TEST_WRITE_KEY, host=TEST_DATA_PLANE_URL, batch=[])

                self.assertEqual(raised.exception.status, 502)
                self.assertEqual(raised.exception.code, 'unknown')
                self.assertIsInstance(raised.exception.message, str)

    def test_datetime_serialization(self):
        data = {'created': datetime(2012, 3, 4, 5, 6, 7, 891011)}
        result = json.dumps(data, cls=DatetimeSerializer)
        self.assertEqual(result, '{"created": "2012-03-04T05:06:07.891011"}')

    def test_date_serialization(self):
        today = date.today()
        data = {'created': today}
        result = json.dumps(data, cls=DatetimeSerializer)
        expected = '{"created": "%s"}' % today.isoformat()
        self.assertEqual(result, expected)

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_should_not_timeout(self, session_post):
        session_post.return_value = mock.Mock(status_code=200)

        res = post(TEST_WRITE_KEY, host=TEST_DATA_PLANE_URL, batch=[{
            'userId': 'userId',
            'event': 'python event',
            'type': 'track'
        }], timeout=15)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(session_post.call_args.kwargs['timeout'], 15)

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_should_timeout(self, session_post):
        session_post.side_effect = requests.ReadTimeout('request timed out')

        with self.assertRaises(UploadError):
            post(TEST_WRITE_KEY, host=TEST_DATA_PLANE_URL, batch=[{
                'userId': 'userId',
                'event': 'python event',
                'type': 'track'
            }], timeout=0.0001)

    def test_gzip_size_reduction(self):
        body = [{
            'userId': 'userId',
            'event': 'python event',
            'type': 'track'
        }, {
            'userId': 'userId',
            'event': 'python event',
            'type': 'track'
        }]
        data = json.dumps(body, cls=DatetimeSerializer)
        self.assertTrue(len(data) > len(_gzip_json(data=data)))

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_passes_proxy_and_timeout_to_session(self, session_post):
        response = mock.Mock(status_code=200)
        session_post.return_value = response

        self.assertIs(
            post(TEST_WRITE_KEY, host=TEST_DATA_PLANE_URL, proxies=TEST_PROXY,
                 timeout=7.5, batch=[]),
            response)
        _, kwargs = session_post.call_args
        self.assertEqual(kwargs['proxies'], TEST_PROXY)
        self.assertEqual(kwargs['timeout'], 7.5)
