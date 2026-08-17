from datetime import datetime, date
import unittest
from unittest import mock
import json
import requests

from rudderstack.analytics.request import _gzip_json, post, DatetimeSerializer
from rudderstack.analytics.get_env import TEST_WRITE_KEY, TEST_DATA_PLANE_URL
from rudderstack.analytics.test.test_constants import TEST_PROXY

class TestRequests(unittest.TestCase):

    def test_valid_request(self):
        res = post(TEST_WRITE_KEY,host=TEST_DATA_PLANE_URL, batch=[{
            'userId': 'userId',
            'event': 'python event',
            'type': 'track'
        }])
        self.assertEqual(res.status_code, 200)

    def test_invalid_request_error(self):
        self.assertRaises(Exception, post, 'TEST_WRITE_KEY',
                          'https://hosted.rudderlabs.com', False, '[{]')

    def test_invalid_host(self):
        self.assertRaises(Exception, post, TEST_WRITE_KEY,
                          'https://invalid_host/', batch=[])

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

    def test_should_not_timeout(self):
        res = post(TEST_WRITE_KEY,host=TEST_DATA_PLANE_URL, batch=[{
            'userId': 'userId',
            'event': 'python event',
            'type': 'track'
        }], timeout=15)
        self.assertEqual(res.status_code, 200)

    def test_should_timeout(self):
        with self.assertRaises(requests.ReadTimeout):
            post(TEST_WRITE_KEY,host=TEST_DATA_PLANE_URL,
             batch=[{
                'userId': 'userId',
                'event': 'python event',
                'type': 'track'
            }], timeout=0.0001)

    def test_gzip_size_reduction(self):
        body = [{
                'userId': 'userId',
                'event': 'python event',
                'type': 'track'
            },{
                'userId': 'userId',
                'event': 'python event',
                'type': 'track'
            }]
        data = json.dumps(body, cls=DatetimeSerializer)
        self.assertTrue(len(data) > len(_gzip_json(data = data)))

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
