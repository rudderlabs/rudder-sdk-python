"""Shared fixtures bound to complete Python HTTP requests (PYTHON-BE-47–50)."""

import copy
from datetime import datetime, timezone
import gzip
import json
import logging
from pathlib import Path
from unittest import mock

import pytest

from rudderstack.analytics.client import Client
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
    transport = mock.Mock(return_value=mock.Mock(status_code=200))
    monkeypatch.setattr(request._session, 'post', transport)
    return transport


def call(client, fields):
    return client.track(
        fields['userId'], fields['event'], properties=fields['properties'],
        context=fields['context'], message_id=fields['messageId'],
        timestamp=datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc))


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
    caller_result = call(client, fields)
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
        'before_enqueue failed, {} track event m1: {}'.format(outcome, reason)]


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
