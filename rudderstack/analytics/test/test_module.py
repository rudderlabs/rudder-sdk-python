import unittest
from unittest import mock

import rudderstack.analytics as analytics


TEST_WRITE_KEY = 'test-write-key'


class TestModule(unittest.TestCase):

    def failed(self):
        self.failed = True

    def setUp(self):
        self.failed = False
        self.client = mock.Mock()
        client_patcher = mock.patch.object(
            analytics, 'default_client', self.client)
        client_patcher.start()
        self.addCleanup(client_patcher.stop)

    def test_no_write_key(self):
        with mock.patch.object(analytics, 'default_client', None), \
                mock.patch.object(analytics, 'write_key', None):
            self.assertRaises(AssertionError, analytics.track)

    def test_no_host_is_forwarded_to_client(self):
        created_client = mock.Mock()
        with mock.patch.object(analytics, 'default_client', None), \
                mock.patch.object(analytics, 'write_key', TEST_WRITE_KEY), \
                mock.patch.object(analytics, 'host', None), \
                mock.patch.object(analytics, 'dataPlaneUrl', None), \
                mock.patch.object(analytics, 'Client',
                                  return_value=created_client) as client_class:
            analytics.track('userId', 'python module event')

        self.assertIsNone(client_class.call_args.kwargs['host'])
        created_client.track.assert_called_once_with(
            'userId', 'python module event')

    def test_track(self):
        analytics.track('userId', 'python module event')
        analytics.flush()
        self.client.track.assert_called_once_with(
            'userId', 'python module event')
        self.client.flush.assert_called_once_with()

    def test_identify(self):
        analytics.identify('userId', {'email': 'user@email.com'})
        analytics.flush()
        self.client.identify.assert_called_once_with(
            'userId', {'email': 'user@email.com'})
        self.client.flush.assert_called_once_with()

    def test_group(self):
        analytics.group('userId', 'groupId')
        analytics.flush()
        self.client.group.assert_called_once_with('userId', 'groupId')
        self.client.flush.assert_called_once_with()

    def test_alias(self):
        analytics.alias('previousId', 'userId')
        analytics.flush()
        self.client.alias.assert_called_once_with('previousId', 'userId')
        self.client.flush.assert_called_once_with()

    def test_page(self):
        analytics.page('userId')
        analytics.flush()
        self.client.page.assert_called_once_with('userId')
        self.client.flush.assert_called_once_with()

    def test_screen(self):
        analytics.screen('userId')
        analytics.flush()
        self.client.screen.assert_called_once_with('userId')
        self.client.flush.assert_called_once_with()

    def test_flush(self):
        analytics.flush()
        self.client.flush.assert_called_once_with()
