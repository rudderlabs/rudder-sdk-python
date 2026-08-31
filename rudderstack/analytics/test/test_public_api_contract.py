"""Compatibility checks for the existing module and Client APIs."""

import unittest
from unittest import mock

import rudderstack.analytics as analytics
from rudderstack.analytics.client import Client


EVENT_CALLS = (
    ('track', ('user-id', 'test event')),
    ('identify', ('user-id',)),
    ('group', ('user-id', 'group-id')),
    ('alias', ('previous-id', 'user-id')),
    ('page', ('user-id',)),
    ('screen', ('user-id',)),
)


class TestPublicApiContract(unittest.TestCase):
    def test_module_discards_client_results(self):
        client = mock.Mock()
        with mock.patch.object(analytics, 'default_client', client):
            for method, args in EVENT_CALLS:
                with self.subTest(method=method):
                    getattr(client, method).return_value = mock.sentinel.result
                    self.assertIsNone(getattr(analytics, method)(
                        *args, message_id='message-id'))
                    getattr(client, method).assert_called_once_with(
                        *args, message_id='message-id')
            for method in ('flush', 'join', 'shutdown'):
                with self.subTest(method=method):
                    getattr(client, method).return_value = mock.sentinel.result
                    self.assertIsNone(getattr(analytics, method)())

    def test_module_returns_none_when_queue_accepts_or_rejects_event(self):
        for method, args in EVENT_CALLS:
            with self.subTest(method=method):
                client = Client('test-key', send=False, max_queue_size=1)
                # Enable enqueueing without starting a background consumer.
                client.send = True
                with mock.patch.object(analytics, 'default_client', client):
                    self.assertIsNone(getattr(analytics, method)(*args))
                    self.assertEqual(client.queue.qsize(), 1)
                    self.assertIsNone(getattr(analytics, method)(*args))
                    self.assertEqual(client.queue.qsize(), 1)

    def test_client_returns_success_and_message(self):
        for method, args in EVENT_CALLS:
            with self.subTest(method=method):
                client = Client('test-key', send=False)
                result = getattr(client, method)(
                    *args, message_id='message-id')
                self.assertIsInstance(result, tuple)
                self.assertEqual(len(result), 2)
                success, message = result
                self.assertIs(success, True)
                self.assertEqual(message['type'], method)
                self.assertEqual(message['messageId'], 'message-id')

    def test_client_returns_false_and_message_when_queue_is_full(self):
        for method, args in EVENT_CALLS:
            with self.subTest(method=method):
                client = Client('test-key', send=False, max_queue_size=1)
                client.send = True
                success, message = getattr(client, method)(*args)
                self.assertIs(success, True)
                self.assertEqual(client.queue.get_nowait(), message)
                client.queue.task_done()
                client.queue.put_nowait(message)
                result = getattr(client, method)(*args)
                self.assertIsInstance(result, tuple)
                self.assertEqual(len(result), 2)
                success, message = result
                self.assertIs(success, False)
                self.assertEqual(message['type'], method)

    def test_module_preserves_validation_errors(self):
        client = Client('test-key', send=False)
        with mock.patch.object(analytics, 'default_client', client):
            with self.assertRaises(AssertionError):
                analytics.track('user-id', event=123)

    def test_client_lifecycle_returns_none(self):
        client = Client('test-key', send=False)
        for method in ('flush', 'join', 'shutdown'):
            with self.subTest(method=method):
                self.assertIsNone(getattr(client, method)())


class TestShutdownDelegation(unittest.TestCase):
    def test_module_calls_client_shutdown_once(self):
        client = mock.Mock()
        with mock.patch.object(analytics, 'default_client', client):
            self.assertIsNone(analytics.shutdown())
        self.assertEqual(client.mock_calls, [mock.call.shutdown()])
