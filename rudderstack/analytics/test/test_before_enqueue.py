import copy
from decimal import Decimal
import inspect
import json
from pathlib import Path
from queue import Queue
import unittest
from unittest import mock

import rudderstack.analytics as analytics
from rudderstack.analytics.client import Client
from rudderstack.analytics.consumer import Consumer, MAX_MSG_SIZE
from rudderstack.analytics.request import APIError, post
from rudderstack.analytics.utils import clean
from rudderstack.analytics.version import VERSION


TEST_WRITE_KEY = 'test-write-key'
PII = 'ada@example.com'

EVENT_CALLS = (
    ('track', ('user-id', 'test event')),
    ('identify', ('user-id',)),
    ('group', ('user-id', 'group-id')),
    ('alias', ('previous-id', 'user-id')),
    ('page', ('user-id',)),
    ('screen', ('user-id',)),
)


def identity(msg):
    return msg


def before_enqueue(msg):
    # Drop: internal test traffic never leaves the process
    if (msg.get('userId') or '').startswith('test-'):
        return None
    # Edit: strip the email before it is transmitted
    for container in (msg, msg.get('context')):
        if isinstance(container, dict):
            traits = container.get('traits')
            if isinstance(traits, dict):
                traits.pop('email', None)
    # Must return the event: an implicit None drops it
    return msg


def set_context_traits(value):
    def hook(msg):
        msg['context']['traits'] = value
        return msg
    return hook


class TestBeforeEnqueue(unittest.TestCase):

    def setUp(self):
        post_patcher = mock.patch('rudderstack.analytics.client.post')
        self.post = post_patcher.start()
        self.addCleanup(post_patcher.stop)

    def make_client(self, before_enqueue, **kwargs):
        kwargs.setdefault('sync_mode', True)
        return Client(TEST_WRITE_KEY, before_enqueue=before_enqueue, **kwargs)

    def sent(self):
        """Events posted to the data plane, in order."""
        return [m for call in self.post.call_args_list for m in call.kwargs['batch']]

    def assert_original_sent(self, original_props=None):
        self.post.assert_called_once()
        sent = self.sent()[0]
        self.assertEqual(sent['type'], 'track')
        self.assertEqual(sent['event'], 'test event')
        self.assertEqual(sent['userId'], 'user-id')
        self.assertEqual(sent['properties'], original_props or {'email': PII})

    # Input

    def test_hook_receives_enriched_wire_format_event(self):
        seen = []

        def hook(msg):
            seen.append(copy.deepcopy(msg))
            return msg

        client = self.make_client(hook)
        client.track('user-id', 'test event', context={
            'wrapperLibrary': {'name': 'ai-sdk-python'}})

        msg = seen[0]
        self.assertEqual(msg['type'], 'track')
        self.assertEqual(msg['channel'], 'server')
        self.assertIsInstance(msg['messageId'], str)
        self.assertIsInstance(msg['timestamp'], str)
        self.assertEqual(msg['integrations'], {'All': True})
        self.assertEqual(msg['context']['library'],
                         {'name': 'analytics-python', 'version': VERSION})
        self.assertEqual(msg['context']['wrapperLibrary'],
                         {'name': 'ai-sdk-python'})
        self.assertNotIn('sentAt', msg)

    # Edit

    def test_readme_hook_redacts_both_traits_locations_in_serialized_request(self):
        self.post.side_effect = post
        client = self.make_client(before_enqueue, before_enqueue_on_error='drop', gzip=False)
        original_client = self.make_client(identity, send=False)
        for method, args in EVENT_CALLS[1:3]:
            for location in ('top-level', 'context', 'both'):
                with self.subTest(method=method, location=location):
                    _, msg = getattr(original_client, method)(*args)
                    msg['timestamp'] = None
                    msg['traits'] = {'plan': 'pro'}
                    msg['context']['traits'] = {'role': 'admin'}
                    if location in ('top-level', 'both'):
                        msg['traits']['email'] = PII
                    if location in ('context', 'both'):
                        msg['context']['traits']['email'] = PII
                    with mock.patch('rudderstack.analytics.request._session.post',
                                    return_value=mock.Mock(status_code=200)) as transport, \
                            mock.patch.object(client.log, 'error') as error:
                        success, result = client._enqueue(msg)
                    self.assertTrue(success)
                    self.assertIsNotNone(result)
                    error.assert_not_called()
                    transport.assert_called_once()
                    body = transport.call_args.kwargs['data']
                    self.assertNotIn(PII, body)
                    batch = json.loads(body)['batch']
                    self.assertEqual(len(batch), 1)
                    self.assertEqual(batch[0]['type'], method)
                    self.assertEqual(batch[0]['traits'], {'plan': 'pro'})
                    self.assertEqual(batch[0]['context']['traits'], {'role': 'admin'})

    def test_readme_hook_sends_events_with_absent_or_non_dict_optional_traits(self):
        self.post.side_effect = post
        client = self.make_client(before_enqueue, before_enqueue_on_error='drop', gzip=False)
        cases = [('track', ('user-id', 'test event'), {})]
        cases.extend(('group', ('user-id', 'group-id'), {
            'traits': {'email': PII, 'plan': 'pro'}, 'context': {'traits': value}})
            for value in (None, 42, 'scalar', [], ['scalar']))
        for method, args, kwargs in cases:
            with self.subTest(method=method, kwargs=kwargs):
                with mock.patch('rudderstack.analytics.request._session.post',
                                return_value=mock.Mock(status_code=200)) as transport, \
                        mock.patch.object(client.log, 'error') as error:
                    success, result = getattr(client, method)(*args, **kwargs)
                self.assertTrue(success)
                self.assertIsNotNone(result)
                error.assert_not_called()
                transport.assert_called_once()
                body = transport.call_args.kwargs['data']
                self.assertNotIn(PII, body)
                batch = json.loads(body)['batch']
                self.assertEqual(len(batch), 1)
                self.assertEqual(batch[0]['type'], method)
                if method == 'group':
                    self.assertEqual(batch[0]['traits'], {'plan': 'pro'})
                    self.assertEqual(batch[0]['context']['traits'], kwargs['context']['traits'])

    def test_readme_hook_handles_missing_or_non_dict_traits_and_context(self):
        readme = Path(__file__).resolve().parents[3] / 'README.md'
        self.assertIn(inspect.getsource(before_enqueue), readme.read_text(encoding='utf-8'))
        for value in (None, 42, 'scalar', [], ['scalar']):
            for fields in ({}, {'traits': value}, {'context': value},
                           {'traits': value, 'context': {'traits': value}}):
                with self.subTest(fields=fields):
                    msg = dict(fields, userId='user-id')
                    self.assertIs(before_enqueue(msg), msg)

    def test_edit_arrives_at_data_plane_sync_mode(self):
        def hook(msg):
            msg['properties']['plan'] = 'pro'
            del msg['properties']['email']
            return msg

        client = self.make_client(hook)
        success, msg = client.track('user-id', 'test event',
                                    properties={'email': PII})

        self.assertTrue(success)
        self.assertEqual(msg['properties'], {'plan': 'pro'})
        self.assertEqual(self.sent()[0]['properties'], {'plan': 'pro'})

    def test_edit_arrives_at_data_plane_queue_mode(self):
        def hook(msg):
            msg['properties']['plan'] = 'pro'
            return msg

        with mock.patch('rudderstack.analytics.consumer.post') as consumer_post:
            client = self.make_client(hook, sync_mode=False)
            self.addCleanup(client.shutdown)
            client.track('user-id', 'test event')
            client.flush()

        batch = consumer_post.call_args.kwargs['batch']
        self.assertEqual(batch[0]['properties'], {'plan': 'pro'})

    def test_hook_output_is_cleaned_and_ids_stringified(self):
        def hook(msg):
            msg['properties']['price'] = Decimal('1.5')
            msg['userId'] = 42
            return msg

        client = self.make_client(hook)
        _, msg = client.track('user-id', 'test event')

        self.assertEqual(msg['properties']['price'], 1.5)
        self.assertEqual(msg['userId'], '42')

    # Drop

    def test_drop_returns_true_none_and_sends_nothing(self):
        for method, args in EVENT_CALLS:
            with self.subTest(method=method):
                self.post.reset_mock()
                client = self.make_client(lambda msg: None)
                self.assertEqual(getattr(client, method)(*args), (True, None))
                self.post.assert_not_called()

    def test_drop_in_queue_mode_does_not_enqueue_or_call_on_error(self):
        on_error = mock.Mock()
        with mock.patch('rudderstack.analytics.consumer.post') as consumer_post:
            client = self.make_client(lambda msg: None, sync_mode=False,
                                      on_error=on_error)
            self.addCleanup(client.shutdown)
            result = client.track('user-id', 'test event')
            client.flush()

        self.assertEqual(result, (True, None))
        self.assertTrue(client.queue.empty())
        consumer_post.assert_not_called()
        on_error.assert_not_called()

    def test_drop_is_logged_at_debug_without_payload(self):
        client = self.make_client(lambda msg: None)
        with self.assertLogs('rudderstack', level='DEBUG') as logs:
            client.track('user-id', 'test event', properties={'email': PII},
                         message_id='mid')

        self.assertIn('DEBUG:rudderstack:before_enqueue dropped track event mid.',
                      logs.output)
        self.assertNotIn(PII, '\n'.join(logs.output))

    def test_drop_with_send_false_returns_true_none(self):
        client = self.make_client(lambda msg: None, sync_mode=False, send=False)
        self.assertEqual(client.track('user-id', 'test event'), (True, None))
        self.assertTrue(client.queue.empty())

    def test_send_false_returns_hook_output(self):
        def hook(msg):
            msg['properties']['plan'] = 'pro'
            return msg

        client = self.make_client(hook, sync_mode=False, send=False)
        success, msg = client.track('user-id', 'test event')
        self.assertTrue(success)
        self.assertEqual(msg['properties'], {'plan': 'pro'})

    # Hook error

    def test_hook_error_send_posts_original_and_logs_error(self):
        def hook(msg):
            raise ValueError('boom')

        client = self.make_client(hook)
        with self.assertLogs('rudderstack', level='ERROR') as logs:
            success, msg = client.track('user-id', 'test event',
                                        properties={'email': PII},
                                        message_id='mid')

        self.assertTrue(success)
        self.assertEqual(msg['properties'], {'email': PII})
        self.assert_original_sent()
        self.assertEqual(logs.output, [
            'ERROR:rudderstack:before_enqueue failed, sending original '
            'track event mid: ValueError'])

    def test_hook_error_drop_sends_nothing_and_logs_error(self):
        def hook(msg):
            raise ValueError('boom')

        client = self.make_client(hook, before_enqueue_on_error='drop')
        with self.assertLogs('rudderstack', level='ERROR') as logs:
            result = client.track('user-id', 'test event',
                                  properties={'email': PII}, message_id='mid')

        self.assertEqual(result, (True, None))
        self.post.assert_not_called()
        self.assertEqual(logs.output, [
            'ERROR:rudderstack:before_enqueue failed, dropping track event mid: '
            'ValueError'])

    def test_uncopyable_event_is_hook_error(self):
        hook = mock.Mock(side_effect=identity)
        client = self.make_client(hook)
        with mock.patch('rudderstack.analytics.client.copy.deepcopy',
                        side_effect=TypeError('cannot copy')), \
                self.assertLogs('rudderstack', level='ERROR'):
            client.track('user-id', 'test event', properties={'email': PII})

        hook.assert_not_called()
        self.assert_original_sent()

    def test_hook_error_does_not_call_on_error(self):
        on_error = mock.Mock()

        def hook(msg):
            raise ValueError('boom')

        with mock.patch('rudderstack.analytics.consumer.post'):
            client = self.make_client(hook, sync_mode=False, on_error=on_error,
                                      before_enqueue_on_error='drop')
            self.addCleanup(client.shutdown)
            with self.assertLogs('rudderstack', level='ERROR'):
                client.track('user-id', 'test event')
            client.flush()
        on_error.assert_not_called()

    def test_non_event_return_is_hook_error(self):
        for bad in ('event', ['event'], 1, True):
            for on_error, sent in (('send', 1), ('drop', 0)):
                with self.subTest(bad=bad, on_error=on_error):
                    self.post.reset_mock()
                    client = self.make_client(
                        lambda msg, bad=bad: bad,
                        before_enqueue_on_error=on_error)
                    with self.assertLogs('rudderstack', level='ERROR'):
                        client.track('user-id', 'test event')
                    self.assertEqual(self.post.call_count, sent)

    def test_mutate_then_fail_sends_pre_hook_event(self):
        def hook(msg):
            msg['properties']['email'] = 'redacted'
            msg['context']['library'] = {'name': 'evil'}
            msg['userId'] = 'someone-else'
            raise RuntimeError('half way')

        client = self.make_client(hook)
        with self.assertLogs('rudderstack', level='ERROR'):
            client.track('user-id', 'test event', properties={'email': PII})

        self.assert_original_sent()
        self.assertEqual(self.sent()[0]['context']['library']['name'],
                         'analytics-python')

    def test_error_log_does_not_contain_payload(self):
        def hook(msg):
            msg.pop('userId')
            return msg

        client = self.make_client(hook)
        with self.assertLogs('rudderstack', level='DEBUG') as logs:
            client.track('user-id', 'test event', properties={'email': PII})
        self.assertNotIn(PII, '\n'.join(
            line for line in logs.output if 'before_enqueue' in line))

    # Reserved fields

    def test_reserved_fields_are_restored_with_warning(self):
        def hook(msg):
            msg['context']['library'] = {'name': 'custom', 'version': '0'}
            msg['channel'] = 'web'
            msg['messageId'] = 'other-id'
            return msg

        client = self.make_client(hook)
        with self.assertLogs('rudderstack', level='WARNING') as logs:
            _, msg = client.track('user-id', 'test event', message_id='mid')

        self.assertEqual(msg['context']['library'],
                         {'name': 'analytics-python', 'version': VERSION})
        self.assertEqual(msg['channel'], 'server')
        self.assertEqual(msg['messageId'], 'mid')
        self.assertEqual(self.sent()[0], msg)
        self.assertEqual(logs.output, [
            'WARNING:rudderstack:before_enqueue changed {0} on track event mid; '
            'restoring the pre-hook value.'.format(field)
            for field in ('context.library', 'channel', 'messageId')])

    def test_removed_reserved_fields_are_restored_with_warning(self):
        def hook(msg):
            del msg['context']['library']
            del msg['channel']
            del msg['messageId']
            return msg

        client = self.make_client(hook)
        with self.assertLogs('rudderstack', level='WARNING') as logs:
            _, msg = client.track('user-id', 'test event', message_id='mid')

        self.assertEqual(msg['context']['library']['name'], 'analytics-python')
        self.assertEqual(msg['channel'], 'server')
        self.assertEqual(msg['messageId'], 'mid')
        self.assertEqual(len(logs.output), 3)

    def test_removed_context_is_recreated_with_library_and_warning(self):
        for removal in ('delete', 'none'):
            with self.subTest(removal=removal):
                def hook(msg, removal=removal):
                    if removal == 'delete':
                        del msg['context']
                    else:
                        msg['context'] = None
                    return msg

                client = self.make_client(hook)
                with self.assertLogs('rudderstack', level='WARNING') as logs:
                    _, msg = client.track('user-id', 'test event', message_id='mid')

                self.assertEqual(msg['context'], {
                    'library': {'name': 'analytics-python', 'version': VERSION}})
                self.assertEqual(logs.output, [
                    'WARNING:rudderstack:before_enqueue changed context.library on '
                    'track event mid; restoring the pre-hook value.'])

    def test_retained_hook_output_is_not_written_and_ids_stay_distinct(self):
        retained = []

        def hook(msg):
            if not retained:
                del msg['context']
                retained.append(msg)
                retained.append(copy.deepcopy(msg))
            return retained[0]

        with mock.patch('rudderstack.analytics.consumer.post') as consumer_post:
            client = self.make_client(hook, sync_mode=False)
            self.addCleanup(client.shutdown)
            client.track('user-id', 'test event', message_id='mid-1')
            client.track('user-id', 'test event', message_id='mid-2')
            client.flush()

        batch = [m for call in consumer_post.call_args_list for m in call.kwargs['batch']]
        self.assertEqual([m['messageId'] for m in batch], ['mid-1', 'mid-2'])
        for m in batch:
            self.assertEqual(m['channel'], 'server')
            self.assertEqual(m['context']['library']['name'], 'analytics-python')
        self.assertEqual(retained[0], retained[1])

    def test_hook_exception_message_is_not_logged(self):
        def hook(msg):
            raise ValueError(msg['properties']['email'])

        for on_error in ('send', 'drop'):
            with self.subTest(on_error=on_error):
                client = self.make_client(hook, before_enqueue_on_error=on_error)
                with self.assertLogs('rudderstack', level='ERROR') as logs:
                    client.track('user-id', 'test event', properties={'email': PII})
                self.assertNotIn(PII, '\n'.join(logs.output))

    def test_unchanged_reserved_fields_do_not_warn(self):
        client = self.make_client(identity)
        with mock.patch.object(client.log, 'warning') as warning:
            client.track('user-id', 'test event')
        warning.assert_not_called()

    # Post-hook validation

    def test_post_hook_validation_failures_are_hook_errors(self):
        def drop_keys(*keys):
            def hook(msg):
                for key in keys:
                    msg.pop(key, None)
                return msg
            return hook

        def set_key(key, value):
            def hook(msg):
                msg[key] = value
                return msg
            return hook

        cases = (
            ('track', ('user-id', 'test event'), drop_keys('userId', 'anonymousId')),
            ('track', ('user-id', 'test event'), drop_keys('event')),
            ('track', ('user-id', 'test event'), set_key('event', 123)),
            ('identify', ('user-id',), drop_keys('userId', 'anonymousId')),
            ('page', ('user-id',), set_key('userId', None)),
            ('screen', ('user-id',), set_key('userId', {'id': 1})),
            ('group', ('user-id', 'group-id'), drop_keys('groupId')),
            ('group', ('user-id', 'group-id'), drop_keys('userId', 'anonymousId')),
            ('alias', ('previous-id', 'user-id'), drop_keys('previousId')),
            ('alias', ('previous-id', 'user-id'), drop_keys('userId')),
            ('track', ('user-id', 'test event'), set_key('context', 'ctx')),
            ('track', ('user-id', 'test event'), set_key('properties', ['a'])),
            ('track', ('user-id', 'test event'), drop_keys('properties')),
            ('track', ('user-id', 'test event'), set_key('integrations', 'All')),
            ('alias', ('previous-id', 'user-id'), drop_keys('integrations')),
            ('page', ('user-id',), set_key('properties', 'props')),
            ('page', ('user-id',), set_key('name', 1)),
            ('screen', ('user-id',), set_key('properties', None)),
            ('screen', ('user-id',), set_key('category', ['c'])),
            ('identify', ('user-id',), set_context_traits(['t'])),
            ('identify', ('user-id',), set_context_traits(None)),
            ('group', ('user-id', 'group-id'), set_key('traits', 'traits')),
        )
        for method, args, hook in cases:
            for on_error in ('send', 'drop'):
                with self.subTest(method=method, hook=hook, on_error=on_error):
                    self.post.reset_mock()
                    client = self.make_client(
                        hook, before_enqueue_on_error=on_error)
                    with self.assertLogs('rudderstack', level='ERROR'):
                        result = getattr(client, method)(*args)
                    if on_error == 'drop':
                        self.assertEqual(result, (True, None))
                        self.post.assert_not_called()
                    else:
                        self.post.assert_called_once()
                        sent = self.sent()[0]
                        self.assertEqual(sent['type'], method)
                        self.assertEqual(sent, result[1])

    def test_anonymous_id_alone_passes_validation(self):
        def hook(msg):
            msg['userId'] = None
            msg['anonymousId'] = 'anon-id'
            return msg

        client = self.make_client(hook)
        with mock.patch.object(client.log, 'error') as error:
            _, msg = client.track('user-id', 'test event')
        error.assert_not_called()
        self.assertIsNone(msg['userId'])
        self.assertEqual(self.sent()[0]['anonymousId'], 'anon-id')

    # Type change

    def test_type_change_is_hook_error_and_original_is_sent(self):
        def hook(msg):
            msg['type'] = 'identify'
            del msg['event']
            return msg

        client = self.make_client(hook)
        with self.assertLogs('rudderstack', level='ERROR'):
            client.track('user-id', 'test event', properties={'email': PII})

        self.assert_original_sent()

    # Size

    def test_hook_that_grows_event_past_limit_is_hook_error(self):
        def hook(msg):
            msg['properties']['blob'] = 'x' * MAX_MSG_SIZE
            return msg

        for on_error, sent in (('send', 1), ('drop', 0)):
            with self.subTest(on_error=on_error):
                self.post.reset_mock()
                client = self.make_client(hook, before_enqueue_on_error=on_error)
                with self.assertLogs('rudderstack', level='ERROR') as logs:
                    result = client.track('user-id', 'test event',
                                          properties={'email': PII})
                self.assertEqual(self.post.call_count, sent)
                if sent:
                    self.assert_original_sent()
                else:
                    self.assertEqual(result, (True, None))
                self.assertIn('over the {0} byte limit'.format(MAX_MSG_SIZE),
                              logs.output[0])
                self.assertNotIn('xxxx', logs.output[0])

    def test_oversized_original_after_hook_error_gets_usual_handling(self):
        def hook(msg):
            raise ValueError('boom')

        client = self.make_client(hook)
        with self.assertLogs('rudderstack', level='ERROR'), \
                self.assertRaisesRegex(RuntimeError, 'Message exceeds 4096kb limit'):
            client.track('user-id', 'test event',
                         properties={'blob': 'x' * MAX_MSG_SIZE})
        self.post.assert_not_called()

    def test_hook_that_shrinks_oversized_event_lets_it_through(self):
        def hook(msg):
            msg['properties'] = {}
            return msg

        client = self.make_client(hook)
        success, _ = client.track('user-id', 'test event',
                                  properties={'blob': 'x' * MAX_MSG_SIZE})
        self.assertTrue(success)
        self.post.assert_called_once()

    # Once per event

    def test_retried_delivery_does_not_call_hook_again(self):
        hook = mock.Mock(side_effect=identity)
        with mock.patch('rudderstack.analytics.consumer.post') as consumer_post, \
                mock.patch('time.sleep'):
            consumer_post.side_effect = [APIError(500, 'error', 'retry'), None]
            client = self.make_client(hook, sync_mode=False, max_retries=1)
            self.addCleanup(client.shutdown)
            client.track('user-id', 'test event')
            client.flush()

        self.assertEqual(consumer_post.call_count, 2)
        hook.assert_called_once()

    # No hook

    def test_no_hook_payload_is_unchanged_and_no_copy_is_made(self):
        kwargs = dict(properties={'k': 'v'}, message_id='message-id',
                      timestamp=None)
        with mock.patch('rudderstack.analytics.client.copy.deepcopy') as deepcopy:
            _, without_hook = Client(TEST_WRITE_KEY, sync_mode=True).track(
                'user-id', 'test event', **kwargs)
        deepcopy.assert_not_called()
        _, with_identity = self.make_client(identity).track(
            'user-id', 'test event', **kwargs)

        without_hook.pop('timestamp')
        with_identity.pop('timestamp')
        self.assertEqual(without_hook, with_identity)

    # Options

    def test_defaults(self):
        client = Client(TEST_WRITE_KEY, send=False)
        self.assertIsNone(client.before_enqueue)
        self.assertEqual(client.before_enqueue_on_error, 'send')

    def test_invalid_options_raise(self):
        with self.assertRaises(AssertionError):
            Client(TEST_WRITE_KEY, send=False, before_enqueue='not callable')
        with self.assertRaises(AssertionError):
            Client(TEST_WRITE_KEY, send=False, before_enqueue=identity,
                   before_enqueue_on_error='raise')


class TestModuleBeforeEnqueue(unittest.TestCase):

    def test_module_globals_are_forwarded_to_client(self):
        with mock.patch.object(analytics, 'default_client', None), \
                mock.patch.object(analytics, 'write_key', TEST_WRITE_KEY), \
                mock.patch.object(analytics, 'before_enqueue', identity), \
                mock.patch.object(analytics, 'before_enqueue_on_error', 'drop'), \
                mock.patch.object(analytics, 'Client') as client_class:
            analytics.track('user-id', 'test event')

        kwargs = client_class.call_args.kwargs
        self.assertIs(kwargs['before_enqueue'], identity)
        self.assertEqual(kwargs['before_enqueue_on_error'], 'drop')

    def test_module_defaults(self):
        self.assertIsNone(analytics.before_enqueue)
        self.assertEqual(analytics.before_enqueue_on_error, 'send')

    def test_module_helpers_return_none_on_drop(self):
        client = Client(TEST_WRITE_KEY, send=False,
                        before_enqueue=lambda msg: None)
        with mock.patch.object(analytics, 'default_client', client):
            for method, args in EVENT_CALLS:
                with self.subTest(method=method):
                    self.assertIsNone(getattr(analytics, method)(*args))


class TestNoPayloadLogging(unittest.TestCase):
    """No log line or SDK-raised error carries the event body, hook or no hook."""

    def test_queueing_debug_log_has_no_payload(self):
        client = Client(TEST_WRITE_KEY, send=False, debug=True)
        with self.assertLogs('rudderstack', level='DEBUG') as logs:
            client.track('user-id', 'test event', properties={'email': PII},
                         message_id='mid')
        self.assertIn('DEBUG:rudderstack:queueing track event mid.', logs.output)
        self.assertNotIn(PII, '\n'.join(logs.output))

    def test_oversize_error_has_no_payload(self):
        client = Client(TEST_WRITE_KEY, send=False)
        with self.assertRaises(RuntimeError) as raised:
            client.track('user-id', 'test event', message_id='mid',
                         properties={'email': PII, 'blob': 'x' * MAX_MSG_SIZE})
        message = str(raised.exception)
        self.assertIn('messageId: mid', message)
        self.assertNotIn(PII, message)

    def test_request_debug_log_has_no_payload(self):
        response = mock.Mock(status_code=200)
        with mock.patch('rudderstack.analytics.request._session.post',
                        return_value=response), \
                self.assertLogs('rudderstack', level='DEBUG') as logs:
            post(TEST_WRITE_KEY, 'http://localhost', batch=[{'email': PII}])
        self.assertIn('making request: 1 events', '\n'.join(logs.output))
        self.assertNotIn(PII, '\n'.join(logs.output))

    def test_consumer_oversize_log_has_no_payload(self):
        q = Queue()
        q.put({'messageId': 'mid', 'email': PII, 'blob': 'x' * MAX_MSG_SIZE})
        with self.assertLogs('rudderstack', level='ERROR') as logs:
            self.assertEqual(Consumer(q, TEST_WRITE_KEY).next(), [])
        self.assertIn('messageId: mid', logs.output[0])
        self.assertNotIn(PII, logs.output[0])

    def test_clean_warning_has_no_value(self):
        class Unserializable(object):
            def __str__(self):
                return PII

        with mock.patch('rudderstack.analytics.utils._coerce_unicode',
                        side_effect=TypeError), \
                self.assertLogs('rudderstack', level='WARNING') as logs:
            clean({'email': Unserializable()})
        self.assertNotIn(PII, '\n'.join(logs.output))

    def test_clean_warning_has_no_key(self):
        for hook in (None, identity):
            with self.subTest(hook=hook):
                client = Client(TEST_WRITE_KEY, send=False, before_enqueue=hook)
                with self.assertLogs('rudderstack', level='WARNING') as logs:
                    client.track('user-id', 'test event', properties={PII: object()})
                self.assertIn('is unsupported', '\n'.join(logs.output))
                self.assertNotIn(PII, '\n'.join(logs.output))
