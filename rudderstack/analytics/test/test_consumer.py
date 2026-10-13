import unittest
from unittest import mock
import time
import json
import logging

from rudderstack.analytics.test.test_constants import TEST_PROXY

try:
    from queue import Queue
except ImportError:
    from Queue import Queue

from rudderstack.analytics.consumer import Consumer, MAX_MSG_SIZE
from rudderstack.analytics.request import APIError, UploadError


TEST_WRITE_KEY = 'test-write-key'
TEST_DATA_PLANE_URL = 'https://example.test'


class TestConsumer(unittest.TestCase):

    def _all_log_output(self):
        return ' '.join(
            handler.stream.getvalue()
            for logger in logging.Logger.manager.loggerDict.values()
            if isinstance(logger, logging.Logger)
            for handler in logger.handlers
            if hasattr(getattr(handler, 'stream', None), 'getvalue'))

    def test_next(self):
        q = Queue()
        consumer = Consumer(q, '')
        q.put(1)
        next = consumer.next()
        self.assertEqual(next, [1])

    def test_next_limit(self):
        q = Queue()
        upload_size = 50
        consumer = Consumer(q, '', upload_size)
        for i in range(10000):
            q.put(i)
        next = consumer.next()
        self.assertEqual(next, list(range(upload_size)))

    def test_dropping_oversize_msg(self):
        q = Queue()
        consumer = Consumer(q, '')
        oversize_msg = {'m': 'x' * MAX_MSG_SIZE}
        q.put(oversize_msg)
        next = consumer.next()
        self.assertEqual(next, [])
        self.assertTrue(q.empty())

    @mock.patch('rudderstack.analytics.consumer.post')
    def test_upload(self, post):
        q = Queue()
        consumer = Consumer(q, host=TEST_DATA_PLANE_URL,
                            write_key=TEST_WRITE_KEY)
        track = {
            'type': 'track',
            'event': 'python event',
            'userId': 'userId'
        }
        q.put(track)
        success = consumer.upload()
        self.assertTrue(success)
        post.assert_called_once()

    @mock.patch('rudderstack.analytics.consumer.post')
    def test_upload_failure_is_safe_and_acknowledged(self, post):
        write_key = 'rk_live_SECRET_SHOULD_NOT_APPEAR'
        post.side_effect = Exception(
            'Authorization: Basic encoded {0}'.format(write_key))
        observed = []
        q = Queue()
        q.put({'type': 'track', 'event': 'event', 'userId': 'userId'})
        consumer = Consumer(
            q, write_key=write_key, host=TEST_DATA_PLANE_URL,
            retries=0, on_error=lambda error, batch: observed.append(error))

        with self.assertLogs(level=logging.ERROR) as captured:
            self.assertFalse(consumer.upload())

        self.assertEqual(q.unfinished_tasks, 0)
        self.assertEqual(len(observed), 1)
        self.assertIsInstance(observed[0], UploadError)
        exposed = captured.output + [str(observed[0]), repr(observed[0])]
        self.assertNotIn(write_key, ' '.join(exposed))
        self.assertNotIn('Authorization', ' '.join(exposed))

        q.join()

    @mock.patch('rudderstack.analytics.consumer.post')
    def test_on_error_failure_does_not_escape_or_block_flush(self, post):
        write_key = 'rk_live_SECRET_SHOULD_NOT_APPEAR'
        post.side_effect = UploadError(
            'ConnectionError Authorization: Basic {0}'.format(write_key))
        q = Queue()
        q.put({'type': 'track', 'event': 'event', 'userId': 'userId'})
        consumer = Consumer(
            q, write_key=write_key, retries=0,
            on_error=mock.Mock(side_effect=UploadError(
                'callback failed for {0}'.format(write_key))))

        with self.assertLogs('rudderstack', logging.ERROR) as captured:
            self.assertFalse(consumer.upload())

        self.assertEqual(q.unfinished_tasks, 0)
        self.assertNotIn(write_key, ' '.join(captured.output))

    def test_dropped_items_are_acknowledged(self):
        q = Queue()
        consumer = Consumer(q, '')
        q.put({'m': 'x' * MAX_MSG_SIZE})
        q.put({'not-json': object()})

        with self.assertLogs('rudderstack', logging.ERROR):
            self.assertEqual(consumer.next(), [])

        self.assertEqual(q.unfinished_tasks, 0)

    def test_upload_interval(self):
        # Put _n_ items in the queue, pausing a little bit more than
        # _upload_interval_ after each one.
        # The consumer should upload _n_ times.
        q = Queue()

        upload_interval = 0.3
        consumer = Consumer(q, host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY, upload_size=10,
                            upload_interval=upload_interval)
        with mock.patch('rudderstack.analytics.consumer.post') as mock_post:
            consumer.start()
            for i in range(0, 3):
                track = {
                    'type': 'track',
                    'event': 'python event %d' % i,
                    'userId': 'userId'
                }
                q.put(track)
                time.sleep(upload_interval * 1.1)
            self.assertEqual(mock_post.call_count, 3)

    def test_multiple_uploads_per_interval(self):
        # Put _upload_size*2_ items in the queue at once, then pause for
        # _upload_interval_. The consumer should upload 2 times.
        q = Queue()
        upload_interval = 0.5
        upload_size = 10
        consumer = Consumer(q,host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY, upload_size=upload_size,
                            upload_interval=upload_interval)
        with mock.patch('rudderstack.analytics.consumer.post') as mock_post:
            consumer.start()
            for i in range(0, upload_size * 2):
                track = {
                    'type': 'track',
                    'event': 'python event %d' % i,
                    'userId': 'userId'
                }
                q.put(track)
            time.sleep(upload_interval * 1.1)
            self.assertEqual(mock_post.call_count, 2)

    @mock.patch('rudderstack.analytics.consumer.post')
    def test_request(self, post):
        consumer = Consumer(None, host=TEST_DATA_PLANE_URL,
                            write_key=TEST_WRITE_KEY)
        track = {
            'type': 'track',
            'event': 'python event',
            'userId': 'userId'
        }
        consumer.request([track])
        post.assert_called_once()

    def _test_request_retry(self, consumer,
                            expected_exception, exception_count):

        def mock_post(*args, **kwargs):
            mock_post.call_count += 1
            if mock_post.call_count <= exception_count:
                raise expected_exception
        mock_post.call_count = 0

        with mock.patch('rudderstack.analytics.consumer.post',
                        mock.Mock(side_effect=mock_post)):
            track = {
                'type': 'track',
                'event': 'python event',
                'userId': 'userId'
            }
            # request() should succeed if the number of exceptions raised is
            # less than the retries parameter.
            if exception_count <= consumer.retries:
                consumer.request([track])
            else:
                # if exceptions are raised more times than the retries
                # parameter, we expect the exception to be returned to
                # the caller.
                try:
                    consumer.request([track])
                except type(expected_exception) as exc:
                    self.assertEqual(exc, expected_exception)
                else:
                    self.fail(
                        "request() should raise an exception if still failing "
                        "after %d retries" % consumer.retries)

    def test_request_retry(self):
        # we should retry on general errors
        consumer = Consumer(None, host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY,)
        self._test_request_retry(consumer, Exception('generic exception'), 2)

        # we should retry on server errors
        consumer = Consumer(None,host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY,)
        self._test_request_retry(consumer, APIError(
            500, 'code', 'Internal Server Error'), 2)

        # we should retry on HTTP 429 errors
        consumer = Consumer(None, host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY,)
        self._test_request_retry(consumer, APIError(
            429, 'code', 'Too Many Requests'), 2)

        # we should NOT retry on other client errors
        consumer = Consumer(None,host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY,)
        api_error = APIError(400, 'code', 'Client Errors')
        try:
            self._test_request_retry(consumer, api_error, 1)
        except APIError:
            pass
        else:
            self.fail('request() should not retry on client errors')

        # test for number of exceptions raise > retries value
        consumer = Consumer(None, host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY, retries=3)
        self._test_request_retry(consumer, APIError(
            500, 'code', 'Internal Server Error'), 3)

    def test_pause(self):
        consumer = Consumer(None, host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY,)
        consumer.pause()
        self.assertFalse(consumer.running)

    def test_max_batch_size(self):
        q = Queue()
        consumer = Consumer(
            q,host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY, upload_size=100000, upload_interval=3)
        track = {
            'type': 'track',
            'event': 'python event',
            'userId': 'userId'
        }
        msg_size = len(json.dumps(track).encode())
        # number of messages in a maximum-size batch
        n_msgs = int((4 << 10 << 10) / msg_size)

        def mock_post_fn(_, data, **kwargs):
            res = mock.Mock()
            res.status_code = 200
            self.assertTrue(len(data) < 500000,
                            'batch size (%d) exceeds 500KB limit'
                            % len(data))
            return res

        with mock.patch('rudderstack.analytics.request._session.post',
                        side_effect=mock_post_fn) as mock_post:
            for _ in range(0, n_msgs + 2):
                q.put(track)
            consumer.start()
            q.join()
            consumer.pause()
            consumer.join()
            self.assertEqual(mock_post.call_count, 2)

    @mock.patch('rudderstack.analytics.request._session.post')
    def test_proxies(self, session_post):
        session_post.return_value = mock.Mock(status_code=200)
        consumer = Consumer(None, host=TEST_DATA_PLANE_URL, 
        write_key=TEST_WRITE_KEY, proxies=TEST_PROXY)
        track = {
            'type': 'track',
            'event': 'python event',
            'userId': 'userId'
        }
        consumer.request([track])

        _, kwargs = session_post.call_args
        self.assertEqual(kwargs['proxies'], TEST_PROXY)
