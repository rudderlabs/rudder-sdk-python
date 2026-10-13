from datetime import datetime, date
import base64
import traceback
import unittest
from unittest import mock
import json
import requests

from rudderstack.analytics.request import (
    APIError, DatetimeSerializer, _gzip_json, post)
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
    def test_request_error_is_propagated(self, session_post):
        session_post.side_effect = requests.RequestException('request failed')

        with self.assertRaisesRegex(requests.RequestException,
                                    'request failed'):
            post(TEST_WRITE_KEY, host=TEST_DATA_PLANE_URL, batch=[])

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_connection_error_is_propagated(self, session_post):
        session_post.side_effect = requests.ConnectionError(
            'host unavailable')

        with self.assertRaisesRegex(requests.ConnectionError,
                                    'host unavailable'):
            post(TEST_WRITE_KEY, host=TEST_DATA_PLANE_URL, batch=[])

    def test_connection_failure_does_not_expose_write_key(self):
        write_key = 'SECRET_WRITE_KEY_5579'
        encoded_key = base64.b64encode(b'SECRET_WRITE_KEY_5579:').decode()

        with self.assertRaises(requests.ConnectionError) as raised:
            post(write_key, host='http://127.0.0.1:1', timeout=2, batch=[])

        error = raised.exception
        self.assertIn('refused', str(error).lower())
        self.assertIsNone(error.request)
        self.assertIsNone(error.response)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        exposed = repr(error) + ''.join(traceback.format_exception(
            type(error), error, error.__traceback__))
        self.assertNotIn(write_key, exposed)
        self.assertNotIn(encoded_key, exposed)

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_request_error_message_is_redacted(self, session_post):
        write_key = 'SECRET_WRITE_KEY_5579'
        encoded_key = base64.b64encode(b'SECRET_WRITE_KEY_5579:').decode()
        session_post.side_effect = requests.ReadTimeout(
            'timed out for {0}, Authorization: Basic {1}'.format(
                write_key, encoded_key))

        with self.assertRaises(requests.ReadTimeout) as raised:
            post(write_key, host=TEST_DATA_PLANE_URL, batch=[])

        message = str(raised.exception)
        self.assertIn('timed out', message)
        self.assertNotIn(write_key, message)
        self.assertNotIn(encoded_key, message)

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_error_response_is_redacted(self, session_post):
        write_key = 'SECRET_WRITE_KEY_5579'
        response = mock.Mock(status_code=401)
        response.json.return_value = {
            'code': 'invalid_write_key',
            'message': "echo {'Authorization': 'Basic abc123'}",
        }
        session_post.return_value = response

        with self.assertRaises(APIError) as raised:
            post(write_key, host=TEST_DATA_PLANE_URL, batch=[])

        self.assertEqual(raised.exception.code, 'invalid_write_key')
        self.assertNotIn('abc123', str(raised.exception))
        self.assertIn('[REDACTED]', str(raised.exception))

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

        with self.assertRaises(requests.ReadTimeout):
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
