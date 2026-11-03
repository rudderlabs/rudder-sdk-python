"""All 37 Python-applicable shared fixtures bound to complete HTTP requests."""

import copy
from datetime import datetime, timezone
import gzip
import json
import logging
from pathlib import Path
from unittest import mock

import pytest

from rudderstack.analytics.client import Client
from rudderstack.analytics import client as client_module
from rudderstack.analytics.consumer import MAX_MSG_SIZE
from rudderstack.analytics import request
from rudderstack.analytics.utils import clean


CONFORMANCE = json.loads(
    (Path(__file__).parent / 'fixtures' / 'before_enqueue.json').read_text())
FIXTURES = {item['id']: item for item in CONFORMANCE['fixtures']}
MARKER = CONFORMANCE['defaults']['payload_marker']
HOST = 'https://data-plane.example.test'


@pytest.fixture
def wire(monkeypatch, caplog):
    """Keep SDK serialization and batching real; replace only the HTTP transport."""
    caplog.set_level(logging.DEBUG, logger='rudderstack')

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 23, 10, 0, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(request, 'datetime', Clock)
    monkeypatch.setattr(client_module, 'uuid4', lambda: 'm1')
    transport = mock.Mock(return_value=mock.Mock(status_code=200))
    monkeypatch.setattr(request._session, 'post', transport)
    return transport


def call(client, fields, method='track'):
    common = dict(user_id=fields.get('userId'), context=fields.get('context'),
                  message_id=fields.get('messageId'),
                  timestamp=datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc))
    if method == 'track':
        common.update(event=fields['event'], properties=fields['properties'])
    elif method == 'group':
        common.update(group_id=fields['groupId'], traits=fields['traits'])
    elif method == 'alias':
        common.update(previous_id=fields['previousId'])
    return getattr(client, method)(**common)


def requests(transport):
    result = []
    for item in transport.call_args_list:
        body = item.kwargs['data']
        if isinstance(body, bytes):
            body = gzip.decompress(body).decode('utf-8')
        result.append({'method': 'POST', 'url': item.args[0],
                       'body': json.loads(body)})
    return result


def baseline(wire, fixture, **options):
    fields = copy.deepcopy(fixture['input']['call']['fields'])
    client = Client('test-write-key', host=HOST, sync_mode=True, **options)
    caller_result = call(client, fields, fixture['input']['call']['type'])
    expected = requests(wire)
    assert len(expected) == 1
    assert expected[0]['url'] == HOST + '/v1/batch'
    wire.reset_mock()
    return fields, caller_result, expected


def assert_logs(caplog, error=False):
    records = [r for r in caplog.records if r.name == 'rudderstack']
    assert records
    assert all(MARKER not in r.getMessage() for r in records)
    errors = [r for r in records if r.levelno >= logging.ERROR]
    assert len(errors) == int(error)
    assert all(r.exc_info is None and r.stack_info is None for r in records)


@pytest.mark.parametrize('compressed', [False, True])
def test_identity_semantically_equal(wire, caplog, compressed):
    fixture = FIXTURES['identity_semantically_equal']
    fields, original, expected = baseline(wire, fixture, gzip=compressed)
    hook = mock.Mock(side_effect=lambda msg: msg)
    on_error = mock.Mock()
    client = Client('test-write-key', host=HOST, sync_mode=True, gzip=compressed,
                    before_enqueue=hook, on_error=on_error)
    caplog.clear()
    result = call(client, fields)
    assert result == original
    assert requests(wire) == expected
    body = wire.call_args.kwargs['data']
    if compressed:
        body = gzip.decompress(body).decode()
    assert MARKER in body
    hook.assert_called_once()
    on_error.assert_not_called()
    assert 'sentAt' not in hook.call_args.args[0]
    assert_logs(caplog)


@pytest.mark.parametrize('policy', ['send', 'drop'])
@pytest.mark.parametrize('bad', [complex(1, 2), float('nan'), float('inf'), float('-inf')],
                         ids=['complex', 'nan', 'infinity', 'negative-infinity'])
@pytest.mark.parametrize('sync_mode', [True, False])
def test_unserialisable_output(wire, caplog, policy, bad, sync_mode):
    fixture = FIXTURES['unserialisable_output']
    fields, original, expected = baseline(wire, fixture)
    snapshot = copy.deepcopy(fields['properties'])

    def edit(msg):
        msg['properties']['marker'] = 'edited'
        # A key with event data also exercises encoder diagnostics privacy.
        msg['properties'][MARKER] = bad
        return msg

    hook = mock.Mock(side_effect=edit)
    on_error = mock.Mock()
    client = Client('test-write-key', host=HOST, sync_mode=sync_mode,
                    before_enqueue=hook, before_enqueue_on_error=policy,
                    on_error=on_error)
    caplog.clear()
    try:
        result = call(client, fields)
        client.flush()
    finally:
        if not sync_mode:
            client.shutdown()
    assert result == (original if policy == 'send' else (True, None))
    assert requests(wire) == (expected if policy == 'send' else [])
    assert fields['properties'] == snapshot
    hook.assert_called_once()
    on_error.assert_not_called()
    assert_logs(caplog, error=True)
    reason = 'TypeError' if isinstance(bad, complex) else 'ValueError'
    outcome = 'sending original' if policy == 'send' else 'dropping'
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR] == [
        'before_enqueue failed, {} track event m1: invalid_output ({})'.format(outcome, reason)]


def test_cyclic_input_hook_error(wire, caplog):
    fixture = FIXTURES['cyclic_input_hook_error']
    fields = copy.deepcopy(fixture['input']['call']['fields'])
    properties = fields['properties']
    properties['self'] = properties
    hook = mock.Mock(side_effect=lambda msg: msg)
    on_error = mock.Mock()
    client = Client('test-write-key', host=HOST, sync_mode=True,
                    before_enqueue=hook, before_enqueue_on_error='drop', on_error=on_error)
    # The existing caller-input clean rejects cycles before the hook boundary.
    with pytest.raises(RecursionError):
        call(client, fields)
    hook.assert_not_called()
    assert requests(wire) == []

    # Bind the fixture's graph at its specified enriched-input copy boundary.
    # Leave post-hook clean and the transport serializer unpatched.
    def enriched_with_cycle(msg):
        msg['properties'] = properties
        return msg

    caplog.clear()
    with mock.patch('rudderstack.analytics.client.clean', side_effect=lambda msg, **kwargs: (
            enriched_with_cycle(msg) if msg['properties'] is properties else clean(msg, **kwargs))):
        assert call(client, fields) == (True, None)
    assert requests(wire) == []
    hook.assert_called_once()
    on_error.assert_not_called()
    assert properties['self'] is properties
    assert properties['marker'] == MARKER
    assert_logs(caplog, error=True)
    assert 'RecursionError' not in caplog.text


@pytest.mark.parametrize('sync_mode', [True, False])
def test_shared_acyclic_input(wire, caplog, sync_mode):
    fixture = copy.deepcopy(FIXTURES['shared_acyclic_input'])
    shared = fixture['input']['call_graph']['shared_map']
    properties = fixture['input']['call']['fields']['properties']
    properties.update(a=shared, b=shared)
    fields, original, expected = baseline(wire, fixture)
    assert fields['properties']['a'] is fields['properties']['b']
    snapshot = copy.deepcopy(fields['properties'])
    hook = mock.Mock(side_effect=lambda msg: msg)
    on_error = mock.Mock()
    client = Client('test-write-key', host=HOST, sync_mode=sync_mode,
                    before_enqueue=hook, on_error=on_error)
    caplog.clear()
    try:
        assert call(client, fields) == original
        client.flush()
    finally:
        if not sync_mode:
            client.shutdown()
    assert requests(wire) == expected
    assert fields['properties'] == snapshot
    assert fields['properties']['a'] is fields['properties']['b']
    hook.assert_called_once()
    on_error.assert_not_called()
    assert_logs(caplog)


@pytest.mark.parametrize('policy', [None, 'send'])
@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf')],
                         ids=['nan', 'infinity', 'negative-infinity'])
def test_no_hook_and_send_fallback_keep_non_finite_encoding(wire, caplog, policy, bad):
    """Strict validation must not change pre-existing wire rules for originals."""
    fixture = copy.deepcopy(FIXTURES['identity_semantically_equal'])
    fixture['input']['call']['fields']['properties']['total'] = bad
    fields, _, _ = baseline(wire, fixture, gzip=False)
    # Compare raw bodies because NaN is not equal to itself as a parsed value.
    call(Client('test-write-key', host=HOST, sync_mode=True, gzip=False), fields)
    expected_body = wire.call_args.kwargs['data']
    wire.reset_mock()
    hook = None if policy is None else mock.Mock(side_effect=ValueError(MARKER))
    client = Client('test-write-key', host=HOST, sync_mode=True, gzip=False,
                    before_enqueue=hook)
    caplog.clear()
    success, _ = call(client, fields)
    assert success
    wire.assert_called_once()
    assert wire.call_args.args[0] == HOST + '/v1/batch'
    assert wire.call_args.kwargs['data'] == expected_body
    assert_logs(caplog, error=policy is not None)


def test_datetime_encoder_and_normalisation_reach_complete_request(wire, caplog):
    fixture = FIXTURES['identity_semantically_equal']
    fields, _, expected = baseline(wire, fixture)

    def hook(msg):
        from datetime import date
        from decimal import Decimal

        msg['properties']['date'] = date(2026, 10, 23)
        msg['properties']['datetime'] = datetime(2026, 10, 23, tzinfo=timezone.utc)
        msg['properties']['total'] = Decimal('1.5')
        msg['userId'] = 42
        return msg

    expected[0]['body']['batch'][0]['properties'].update(
        date='2026-10-23', datetime='2026-10-23T00:00:00+00:00', total=1.5)
    expected[0]['body']['batch'][0]['userId'] = '42'
    client = Client('test-write-key', host=HOST, sync_mode=True, before_enqueue=hook)
    caplog.clear()
    assert call(client, fields)[0]
    assert requests(wire) == expected
    assert_logs(caplog)


@pytest.mark.parametrize('signal', [KeyboardInterrupt, SystemExit])
def test_process_control_propagates(wire, caplog, signal):
    fields = copy.deepcopy(FIXTURES['identity_semantically_equal']['input']['call']['fields'])
    client = Client('test-write-key', host=HOST, sync_mode=True,
                    before_enqueue=mock.Mock(side_effect=signal))
    with pytest.raises(signal):
        call(client, fields)
    assert requests(wire) == []
    assert MARKER not in caplog.text


@pytest.mark.parametrize('policy', ['send', 'drop'])
@pytest.mark.parametrize('hostile', [False, True])
def test_returned_date_error_is_private_and_contained(wire, caplog, policy, hostile):
    from datetime import date
    from rudderstack.analytics.client import BeforeEnqueueError

    class HostileError(BeforeEnqueueError):
        def __str__(self):
            raise RuntimeError(MARKER)

    class BadDate(date):
        def isoformat(self):
            raise (HostileError if hostile else BeforeEnqueueError)(MARKER)

    fields, original, expected = baseline(wire, FIXTURES['identity_semantically_equal'])

    def hook(msg):
        msg['properties']['date'] = BadDate(2026, 10, 23)
        return msg

    on_error = mock.Mock()
    client = Client('test-write-key', host=HOST, sync_mode=True,
                    before_enqueue=hook, before_enqueue_on_error=policy, on_error=on_error)
    caplog.clear()
    assert call(client, fields) == (original if policy == 'send' else (True, None))
    assert requests(wire) == (expected if policy == 'send' else [])
    on_error.assert_not_called()
    assert_logs(caplog, error=True)


@pytest.mark.parametrize('policy', ['send', 'drop'])
def test_hook_failure_log_formatting_is_contained(wire, policy):
    fields, original, expected = baseline(wire, FIXTURES['identity_semantically_equal'])
    client = Client('test-write-key', host=HOST, sync_mode=True,
                    before_enqueue=mock.Mock(side_effect=ValueError(MARKER)),
                    before_enqueue_on_error=policy)
    with mock.patch.object(client.log, 'error', side_effect=RuntimeError(MARKER)):
        assert call(client, fields) == (original if policy == 'send' else (True, None))
    assert requests(wire) == (expected if policy == 'send' else [])


def test_delayed_serializer_logs_no_text_or_traceback_without_hook(wire, caplog):
    from datetime import date

    class DelayedDate(date):
        calls = 0

        def isoformat(self):
            self.calls += 1
            if self.calls > 1:
                raise ValueError(MARKER)
            return '2026-10-23'

    client = Client('test-write-key', host=HOST, send=False, upload_interval=0.01)
    fields = copy.deepcopy(FIXTURES['identity_semantically_equal']['input']['call']['fields'])
    fields['properties']['date'] = DelayedDate(2026, 10, 23)
    _, msg = call(client, fields)
    client.queue.put(msg)
    caplog.clear()
    assert client.consumers[0].next() == []
    assert requests(wire) == []
    assert_logs(caplog, error=True)
    assert client.queue.unfinished_tasks == 0


@pytest.mark.parametrize('json_response', [False, True])
def test_echoed_server_error_logs_no_body_and_preserves_on_error(wire, caplog, json_response):
    response = mock.Mock(status_code=400, text=MARKER)
    if json_response:
        response.json.return_value = {'code': MARKER, 'message': MARKER}
    else:
        response.json.side_effect = ValueError(MARKER)
    wire.return_value = response
    on_error = mock.Mock()
    client = Client('test-write-key', host=HOST, send=False, on_error=on_error,
                    upload_interval=0.01, max_retries=0)
    fields = copy.deepcopy(FIXTURES['identity_semantically_equal']['input']['call']['fields'])
    _, msg = call(client, fields)
    client.queue.put(msg)
    caplog.clear()
    assert client.consumers[0].upload() is False
    error, batch = on_error.call_args.args
    assert error.status == 400
    assert error.message == MARKER
    assert error.code == (MARKER if json_response else 'unknown')
    assert batch == [msg]
    assert MARKER not in caplog.text
    assert all(r.exc_info is None and r.stack_info is None for r in caplog.records)
    assert client.queue.unfinished_tasks == 0


def test_all_python_fixtures_are_imported():
    # Membership is defined by component-spec.md's applicability table.
    expected = {
        'enriched_input', 'identity_semantically_equal', 'no_hook_unchanged',
        'edit_reaches_wire', 'null_drop_accepted', 'throw_send_original', 'throw_drop_none',
        'mutate_then_throw_isolated', 'wrong_shape_hook_error', 'type_change_hook_error',
        'restore_messageid', 'restore_removed_messageid', 'restore_context_library',
        'restore_removed_context_library', 'restore_channel', 'restore_removed_channel',
        'removed_context_recreated', 'identity_fields_revalidated', 'required_track_field',
        'required_group_field', 'required_alias_field', 'post_hook_oversize', 'post_hook_oversize_drop',
        'unserialisable_output', 'container_type_violation', 'cyclic_input_hook_error',
        'shared_acyclic_input', 'retained_result_distinct_ids', 'once_across_retries',
        'no_payload_in_logs', 'exception_text_not_logged', 'invalid_hook_config',
        'invalid_policy_config', 'process_control_propagates', 'original_oversize_usual_handling',
        'output_normalisation', 'sent_at_ownership',
    }
    assert set(FIXTURES) == expected


def test_readme_explains_lazy_module_configuration():
    readme = (Path(__file__).parents[3] / 'README.md').read_text()
    assert 'before the first module call' in readme
    assert 'default client is created' in readme
    assert "Client(\n    'YOUR_WRITE_KEY', before_enqueue=before_enqueue," in readme


def edit_path(event, path, value=None, remove=False):
    parts = path.split('.')
    for part in parts[:-1]:
        event = event.setdefault(part, {})
    if remove:
        event.pop(parts[-1], None)
    else:
        event[parts[-1]] = value


def bind_event(baseline_event, neutral_input, neutral_expected):
    """Apply only fixture differences, keeping every Python-owned baseline field."""
    result = copy.deepcopy(baseline_event)
    for key in neutral_input.keys() | neutral_expected.keys():
        if key not in neutral_expected:
            result.pop(key, None)
        elif key not in neutral_input:
            result[key] = copy.deepcopy(neutral_expected[key])
        elif neutral_input[key] != neutral_expected[key]:
            if isinstance(neutral_input[key], dict) and isinstance(neutral_expected[key], dict):
                result[key] = bind_event(result.get(key, {}), neutral_input[key], neutral_expected[key])
            else:
                result[key] = copy.deepcopy(neutral_expected[key])
    return result


def apply_hook_edits(msg, spec):
    for path, value in spec.get('set', {}).items():
        edit_path(msg, path, copy.deepcopy(value))
    for path in spec.get('remove', []):
        edit_path(msg, path, remove=True)
    behavior = spec['behavior']
    if behavior == 'change_type':
        msg['type'] = spec['value']
    elif behavior == 'change_reserved_field':
        edit_path(msg, spec['field'], spec.get('value'), spec.get('operation') == 'remove')
    elif behavior == 'remove_context':
        msg.pop('context')
    elif behavior == 'return_oversize':
        edit_path(msg, spec['field'], MARKER * (MAX_MSG_SIZE // len(MARKER) + 1))
    elif behavior == 'return_unserialisable':
        # Complex numbers survive clean() but the real JSON encoder rejects them.
        edit_path(msg, 'properties.bad', complex(1, 2))


def fixture_hook(spec, seen, retained):
    def hook(msg):
        seen.append(copy.deepcopy(msg))
        apply_hook_edits(msg, spec)
        behavior = spec['behavior']
        if behavior in ('throw', 'mutate_then_throw'):
            error = ValueError(spec['message'])
            error.name = spec.get('writable_error_name')
            raise error
        if behavior == 'return_null':
            return None
        if behavior == 'return_wrong_shape':
            return spec['value']
        if behavior == 'return_retained_object':
            if not retained:
                retained.extend([msg, copy.deepcopy(msg)])
            return retained[0]
        if behavior == 'throw_process_control_signal':
            raise KeyboardInterrupt('marker-free signal')
        return msg
    return mock.Mock(side_effect=hook)


def prepare_fixture(wire, spec):
    calls = copy.deepcopy(spec.get('calls', [spec['call']]))
    if 'shared_map' in spec.get('call_graph', {}):
        shared = copy.deepcopy(spec['call_graph']['shared_map'])
        calls[0]['fields']['properties'].update(a=shared, b=shared)
    originals, baselines, raw_baselines = [], [], []
    for event_call in calls:
        template = dict(input=dict(call=event_call))
        fields, original, captured = baseline(wire, template, gzip=False)
        event_call['fields'] = fields
        originals.append(original)
        baselines.extend(captured)
        # The no-hook compatibility fixture also compares the raw body.
        call(Client('test-write-key', host=HOST, sync_mode=True, gzip=False), fields, event_call['type'])
        raw_baselines.append(wire.call_args.kwargs['data'])
        wire.reset_mock()
    return calls, originals, baselines, raw_baselines


def expand_original(calls, originals):
    fields = calls[0]['fields']
    _, enriched = Client('test-write-key', send=False).track(
        fields['userId'], fields['event'], properties=dict(fields['properties'], blob=''),
        context=copy.deepcopy(fields['context']), message_id=fields['messageId'],
        timestamp=datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc))
    overhead = client_module.msg_size(enriched)
    repetitions = (MAX_MSG_SIZE - overhead) // len(MARKER) + 1
    fields['properties']['blob'] = MARKER * repetitions
    originals[0][1]['properties']['blob'] = fields['properties']['blob']
    assert overhead + (repetitions - 1) * len(MARKER) <= MAX_MSG_SIZE
    with pytest.raises(RuntimeError) as original_error:
        call(Client('test-write-key', host=HOST, sync_mode=True), copy.deepcopy(fields))
    return original_error.value


def deliver_fixture(client, calls, fixture, original_error):
    results = []
    try:
        for event_call in calls:
            if fixture['expected']['caller_result'] == 'process_control_signal':
                with pytest.raises(KeyboardInterrupt):
                    call(client, event_call['fields'], event_call['type'])
            elif original_error is not None:
                with pytest.raises(RuntimeError) as hooked_error:
                    call(client, event_call['fields'])
                assert hooked_error.value.args == original_error.args
            else:
                results.append(call(client, event_call['fields'], event_call['type']))
        client.flush()
    finally:
        if not client.sync_mode:
            client.shutdown()
    return results


def assert_fixture_request(wire, fixture, baselines, raw_baselines, results):
    expected = fixture['expected']
    actual = requests(wire)
    if expected['serialized_request'] == 'none':
        assert actual == []
        if expected['caller_result'] == 'accepted':
            assert results == [(True, None)]
        return
    serialized = expected['serialized_request']
    if isinstance(serialized, dict):
        serialized = [serialized]
    neutral = [event for item in serialized for event in json.loads(item['body'])['batch']]
    neutral_calls = fixture['input'].get('calls', [fixture['input']['call']])
    bound_events = [bind_event(baselines[i]['body']['batch'][0], event_call['fields'], neutral[i])
                    for i, event_call in enumerate(neutral_calls)]
    wanted = copy.deepcopy(baselines)
    for i, event in enumerate(bound_events):
        wanted[i]['body']['batch'] = [event]
    wanted *= expected.get('request_count', 1)
    assert actual == wanted
    assert results == [(True, event) for event in bound_events]
    if fixture['id'] == 'no_hook_unchanged':
        assert wire.call_args.kwargs['data'] == raw_baselines[0]


def assert_fixture_logs(caplog, expected):
    records = [r for r in caplog.records if r.name == 'rudderstack']
    assert MARKER not in caplog.text
    assert all(r.exc_info is None and r.stack_info is None for r in caplog.records)
    hook_records = [r for r in records if 'before_enqueue' in r.getMessage()]
    level = expected['logs']['level']
    assert len([r for r in hook_records if r.levelno == logging.ERROR]) == int(level == 'error')
    assert len([r for r in hook_records if r.levelno == logging.WARNING]) == len(
        expected['logs'].get('restored_fields', []))
    if level == 'debug':
        assert any(r.levelno == logging.DEBUG for r in hook_records)


# Cyclic graphs need the explicit enriched-input-boundary binding above.
REQUEST_FIXTURES = [f for f in FIXTURES.values() if f['id'] != 'cyclic_input_hook_error']


@pytest.mark.parametrize('fixture', REQUEST_FIXTURES, ids=lambda f: f['id'])
@pytest.mark.parametrize('sync_mode', [True, False], ids=['sync', 'queued'])
def test_fixture_complete_request(wire, caplog, fixture, sync_mode):
    spec = fixture['input']
    expected = fixture['expected']
    seen, retained = [], []
    hook = fixture_hook(spec['hook'], seen, retained)
    on_error = mock.Mock()
    # One event per batch fixes delivery grouping in both the baseline and queued runs.
    options = dict(host=HOST, sync_mode=sync_mode, gzip=False, before_enqueue=hook,
                   before_enqueue_on_error=spec['policy'], on_error=on_error,
                   upload_interval=0.01, upload_size=1, max_retries=1)
    if spec['hook']['behavior'] == 'not_configured':
        options['before_enqueue'] = None
    if expected['caller_result'] == 'configuration_error':
        options['before_enqueue'] = spec['hook'].get('hook_value', hook)
        with pytest.raises(AssertionError):
            Client('test-write-key', **options)
        assert requests(wire) == []
        hook.assert_not_called()
        on_error.assert_not_called()
        assert MARKER not in caplog.text
        return
    calls, originals, baselines, raw_baselines = prepare_fixture(wire, spec)
    original_error = expand_original(calls, originals) if 'original_expansion' in spec else None
    snapshot = copy.deepcopy(calls)
    caplog.clear()
    if 'delivery_responses' in spec:
        rejected = mock.Mock(status_code=spec['delivery_responses'][0])
        rejected.json.return_value = {'code': MARKER, 'message': MARKER}
        wire.side_effect = [rejected, mock.Mock(status_code=spec['delivery_responses'][1])]
        # Sync delivery has no retries; exercise the existing Consumer.request in either case.
        options['sync_mode'] = False
    with mock.patch('time.sleep'):
        results = deliver_fixture(Client('test-write-key', **options), calls, fixture, original_error)
    assert calls == snapshot
    assert hook.call_count == expected.get('hook_calls', 1)
    on_error.assert_not_called()
    assert seen == ([original[1] for original in originals] if options['before_enqueue'] else [])
    if retained:
        assert retained[0] == retained[1]
    if 'shared_map' in spec.get('call_graph', {}):
        props = calls[0]['fields']['properties']
        assert props['a'] is props['b']
    assert all('sentAt' not in event for event in seen)
    assert_fixture_request(wire, fixture, baselines, raw_baselines, results)
    assert_fixture_logs(caplog, expected)
    if fixture['id'] == 'no_payload_in_logs':
        wire.reset_mock()
        caplog.clear()
        assert call(Client('test-write-key', host=HOST, sync_mode=True), calls[0]['fields'])[0]
        assert requests(wire) == baselines
        assert MARKER not in caplog.text


@pytest.mark.parametrize('sync_mode', [True, False])
def test_concurrent_calls_have_distinct_ids_and_one_hook_call_each(wire, caplog, sync_mode):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock, get_ident

    count = 32
    barrier, lock = Barrier(count), Lock()
    observed = []
    fields, _, baseline_requests = baseline(wire, FIXTURES['identity_semantically_equal'])

    def hook(msg):
        barrier.wait(timeout=10)
        with lock:
            observed.append((msg['messageId'], get_ident()))
        msg['properties']['total'] = int(msg['messageId'].split('-')[1])
        return msg

    client = Client('test-write-key', host=HOST, sync_mode=sync_mode,
                    before_enqueue=hook, upload_interval=0.01)

    def submit(index):
        local = copy.deepcopy(fields)
        local['messageId'] = 'thread-{}'.format(index)
        result = call(client, local)
        return index, result, get_ident()

    try:
        with ThreadPoolExecutor(max_workers=count) as pool:
            results = list(pool.map(submit, range(count)))
        client.flush()
    finally:
        if not sync_mode:
            client.shutdown()

    assert len(observed) == count
    assert dict(observed) == {'thread-{}'.format(i): thread for i, _, thread in results}
    expected_events = []
    for index, result, _ in results:
        event = copy.deepcopy(baseline_requests[0]['body']['batch'][0])
        event['messageId'] = 'thread-{}'.format(index)
        event['properties']['total'] = index
        assert result == (True, event)
        expected_events.append(event)
    actual_events = []
    for sent in requests(wire):
        assert sent['method'] == 'POST'
        assert sent['url'] == HOST + '/v1/batch'
        assert sent['body'] == dict(baseline_requests[0]['body'], batch=sent['body']['batch'])
        actual_events.extend(sent['body']['batch'])
    assert sorted(actual_events, key=lambda e: e['messageId']) == sorted(
        expected_events, key=lambda e: e['messageId'])
    assert_logs(caplog)


def test_transport_exception_is_passed_unchanged_without_formatting(wire, caplog):
    class TransportError(Exception):
        def __str__(self):
            raise RuntimeError(MARKER)

    error = TransportError(MARKER)
    wire.side_effect = error
    on_error = mock.Mock()
    client = Client('test-write-key', host=HOST, send=False, on_error=on_error,
                    upload_interval=0.01, max_retries=0)
    fields = copy.deepcopy(FIXTURES['identity_semantically_equal']['input']['call']['fields'])
    _, event = call(client, fields)
    client.queue.put(event)
    caplog.clear()
    assert client.consumers[0].upload() is False
    assert on_error.call_args.args[0] is error
    assert on_error.call_args.args[1] == [event]
    assert_logs(caplog, error=True)
    assert caplog.records[-1].getMessage() == 'upload failed: TransportError'
