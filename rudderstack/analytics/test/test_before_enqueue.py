"""Focused tests for the synchronous before_enqueue contract."""
import json
from datetime import datetime, timezone
from unittest import mock

import pytest

from rudderstack.analytics.client import Client
from rudderstack.analytics.consumer import MAX_MSG_SIZE
from rudderstack.analytics.version import VERSION


def make_client(hook=None, **options):
    return Client('test-key', host='http://localhost', sync_mode=True, gzip=False,
                  before_enqueue=hook, **options)


def track(client, **fields):
    options = dict(user_id='u1', event='Purchase', properties={'total': 1},
                   timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), message_id='m1')
    options.update(fields)
    return client.track(**options)


def sent(wire):
    return [event for call in wire.call_args_list
            for event in json.loads(call.kwargs['data'])['batch']]


def throw(event):
    event['properties']['total'] = 99
    raise ValueError('hook failure as thrown')


def test_edit_reaches_wire(wire):
    def hook(event):
        event['properties']['total'] = 99
        event['type'] = 'page'
        event['userId'] = 7
        return event
    assert track(make_client(hook))[0]
    assert sent(wire)[0]['properties']['total'] == 99
    assert sent(wire)[0]['type'] == 'page'
    assert sent(wire)[0]['userId'] == 7


def test_none_drop(wire, caplog):
    on_error = mock.Mock()
    with caplog.at_level('DEBUG', logger='rudderstack'):
        assert track(make_client(lambda event: None, on_error=on_error)) == (True, None)
    wire.assert_not_called()
    on_error.assert_not_called()
    assert 'before_enqueue dropped track event m1.' in caplog.text


def test_throw_send_original(wire, caplog):
    on_error = mock.Mock()
    track(make_client(throw, on_error=on_error))
    assert sent(wire)[0]['properties']['total'] == 1
    assert 'sending the original event. hook failure as thrown' in caplog.text
    on_error.assert_not_called()


def test_throw_drop(wire, caplog):
    assert track(make_client(throw, before_enqueue_on_error='drop')) == (True, None)
    wire.assert_not_called()
    assert 'dropping the event. hook failure as thrown' in caplog.text


def test_non_dict_is_hook_error(wire, caplog):
    track(make_client(lambda event: 42))
    assert sent(wire)[0]['event'] == 'Purchase'
    assert 'before_enqueue failed' in caplog.text


def test_validation_failure_both_policies(wire, caplog):
    def hook(event):
        del event['event']
        return event
    for policy in ('send', 'drop'):
        wire.reset_mock()
        result = track(make_client(hook, before_enqueue_on_error=policy))
        assert sent(wire) == ([result[1]] if policy == 'send' else [])
    assert len([r for r in caplog.records if r.levelname == 'ERROR']) == 2


def test_changed_type_is_validated_by_its_own_rules(wire, caplog):
    def hook(event):
        event['type'] = 'track'
        return event
    make_client(hook).page(user_id='u1', name='Home')
    assert sent(wire)[0]['type'] == 'page'
    assert 'before_enqueue failed' in caplog.text


def test_hook_fixes_invalid_call(wire, caplog):
    def hook(event):
        event.update(event='Fixed', userId='fixed-user', properties={},
                     context={'library': {'name': 'analytics-python', 'version': VERSION}},
                     integrations={}, timestamp='2026-01-01T00:00:00+00:00')
        return event
    track(make_client(hook), user_id=None, event=None, properties='invalid',
          context='invalid', integrations='invalid', timestamp=42)
    assert sent(wire)[0]['event'] == 'Fixed'
    assert not caplog.records


def test_restore_channel_and_library_once(wire, caplog):
    def hook(event):
        event['channel'] = 'browser'
        event['context']['library'] = {'name': 'custom'}
        return event
    track(make_client(hook))
    event = sent(wire)[0]
    assert event['channel'] == 'server'
    assert event['context']['library'] == {'name': 'analytics-python', 'version': VERSION}
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == 'WARNING'


def test_message_id_change_and_removal(wire, caplog):
    for replacement in ('m2', None, ''):
        def hook(event):
            if replacement is None:
                del event['messageId']
            else:
                event['messageId'] = replacement
            return event
        wire.reset_mock()
        track(make_client(hook))
        assert sent(wire)[0]['messageId'] == (replacement or 'm1')
    assert not caplog.records


def test_oversize_raises_as_without_hook(wire, caplog):
    def hook(event):
        event['properties']['blob'] = 'x' * MAX_MSG_SIZE
        return event

    properties = {'total': 1, 'blob': 'x' * MAX_MSG_SIZE}
    with pytest.raises(RuntimeError) as baseline:
        track(make_client(), properties=properties)
    for policy in ('send', 'drop'):
        with pytest.raises(RuntimeError) as oversized:
            track(make_client(hook, before_enqueue_on_error=policy))
        assert type(oversized.value) is RuntimeError
        assert str(oversized.value) == str(baseline.value)
    wire.assert_not_called()
    assert not caplog.records

    # A throwing hook still follows the policy; send validates the original size.
    with pytest.raises(RuntimeError) as original:
        track(make_client(throw), properties=properties)
    assert str(original.value) == str(baseline.value)
    wire.assert_not_called()
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == 'ERROR'


def test_once_across_retries(wire):
    hook = mock.Mock(side_effect=lambda event: event)
    wire.side_effect = [RuntimeError('retry'), mock.Mock(status_code=200)]
    client = Client('test-key', host='http://localhost', gzip=False, before_enqueue=hook,
                    upload_interval=0.01, max_retries=1)
    try:
        with mock.patch('time.sleep'):
            track(client)
            client.flush()
    finally:
        client.shutdown()
    assert wire.call_count == 2
    hook.assert_called_once()


def test_option_validation():
    for options in ({'before_enqueue': 42}, {'before_enqueue_on_error': 'retry'}):
        with pytest.raises(AssertionError):
            Client('test-key', sync_mode=True, **options)


def test_without_hook_unchanged(wire, caplog):
    with caplog.at_level('DEBUG', logger='rudderstack'):
        result = track(make_client())
    assert sent(wire) == [result[1]]
    assert any(r.msg == 'queueing: %s' for r in caplog.records)
    assert any(r.msg == 'making request: %s' for r in caplog.records)
    with pytest.raises(AssertionError):
        track(make_client(), event=None)
    with pytest.raises(AssertionError):
        track(make_client(throw), event=None)
