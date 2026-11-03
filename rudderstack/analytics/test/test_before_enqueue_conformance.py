"""One runner for the twenty reviewer-approved shared fixture IDs.

All fixtures apply in Python. Callback success maps to (True, None); Python
uses its existing 4 MB limit rather than Node's 32 KB. Python supports cycles.
post_hook_oversize_warns maps to the usual RuntimeError, as without a hook;
oversize is not a hook error and nothing is sent.
"""
import copy
import json
from pathlib import Path
from unittest import mock

import pytest

from rudderstack.analytics.client import Client
from rudderstack.analytics.consumer import MAX_MSG_SIZE
from rudderstack.analytics.test.test_before_enqueue import make_client, sent, track


FIXTURES = json.loads((Path(__file__).parent / 'fixtures' / 'before_enqueue.json').read_text())


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda fixture: fixture['id'])
def test_conformance(fixture, wire, caplog):
    fixture_id = fixture['id']
    track(make_client())
    baseline = sent(wire)[0]
    wire.reset_mock()
    observed = []

    def hook(event):
        observed.append(copy.deepcopy(event))
        if fixture_id == 'null_drop':
            return None
        if fixture_id in ('throw_send_original', 'throw_drop_none', 'mutate_then_throw_isolated'):
            if fixture_id == 'mutate_then_throw_isolated':
                event['properties']['total'] = 99
            raise ValueError('fixture failure')
        if fixture_id == 'non_object_hook_error':
            return 42
        if fixture_id in ('required_field_hook_error', 'required_field_hook_error_drop'):
            del event['event']
        if fixture_id == 'edit_reaches_wire':
            event['properties']['total'] = 99
        if fixture_id == 'hook_fixes_invalid_call':
            event['event'] = 'Fixed'
        if fixture_id == 'restore_channel':
            event['channel'] = 'browser'
        if fixture_id == 'restore_context_library':
            event['context']['library'] = {'name': 'custom'}
        if fixture_id == 'keep_messageid_change':
            event['messageId'] = 'm2'
        if fixture_id == 'restore_removed_messageid':
            del event['messageId']
        if fixture_id == 'post_hook_oversize_warns':
            event['properties']['blob'] = 'x' * MAX_MSG_SIZE
        if fixture_id == 'cyclic_output_hook_error':
            event['properties']['cycle'] = event
        return event

    on_error = mock.Mock()
    options = dict(before_enqueue_on_error=fixture['policy'], on_error=on_error)
    if fixture['outcome'] == 'config_error':
        options.update({'before_enqueue': 42} if fixture_id == 'invalid_hook_config'
                       else {'before_enqueue_on_error': 'retry'})
        with pytest.raises(AssertionError):
            Client('test-key', sync_mode=True, **options)
        wire.assert_not_called()
        return
    configured_hook = None if fixture_id == 'no_hook_unchanged' else hook
    client = make_client(configured_hook, **options)
    if fixture_id == 'once_across_retries':
        wire.side_effect = [RuntimeError('retry'), mock.Mock(status_code=200)]
        client = Client('test-key', host='http://localhost', gzip=False, before_enqueue=hook,
                        upload_interval=0.01, max_retries=1, **options)
    caplog.clear()
    if fixture_id == 'post_hook_oversize_warns':
        with pytest.raises(RuntimeError, match=r'^Message exceeds 4096kb limit\.'):
            track(client)
        wire.assert_not_called()
        on_error.assert_not_called()
        assert len(observed) == 1
        assert not caplog.records
        return
    try:
        with mock.patch('time.sleep'):
            result = track(client, **({'event': None} if fixture_id == 'hook_fixes_invalid_call' else {}))
            client.flush()
    finally:
        if not client.sync_mode:
            client.shutdown()
    actual = sent(wire)
    assert len(observed) == (0 if configured_hook is None else 1)
    on_error.assert_not_called()
    errors = [r for r in caplog.records if r.levelname == 'ERROR']
    warnings = [r for r in caplog.records if r.levelname == 'WARNING']
    assert len(errors) == int(fixture['outcome'] == 'original' or fixture_id in
                              ('throw_drop_none', 'required_field_hook_error_drop'))
    assert len(warnings) == int(fixture_id in
                                ('restore_channel', 'restore_context_library'))
    if fixture['outcome'] == 'drop':
        assert actual == []
        assert result == (True, None)
        return
    expected = copy.deepcopy(baseline)
    if fixture_id == 'edit_reaches_wire':
        expected['properties']['total'] = 99
    if fixture_id == 'hook_fixes_invalid_call':
        expected['event'] = 'Fixed'
    if fixture_id == 'keep_messageid_change':
        expected['messageId'] = 'm2'
    assert actual == [expected] * (2 if fixture_id == 'once_across_retries' else 1)
    assert result == (True, expected)
    if fixture_id == 'enriched_input':
        assert observed == [baseline]
    if fixture_id == 'once_across_retries':
        assert wire.call_count == 2
