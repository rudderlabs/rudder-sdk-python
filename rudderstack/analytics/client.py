from datetime import datetime, timezone
from uuid import uuid4
import logging
import numbers
import atexit
import copy
import json

from dateutil.tz import tzutc
from rudderstack.analytics.get_env import TEST_DATA_PLANE_URL

from rudderstack.analytics.utils import guess_timezone, clean
from rudderstack.analytics.consumer import Consumer, MAX_MSG_SIZE
from rudderstack.analytics.request import post, DatetimeSerializer
from rudderstack.analytics.version import VERSION

import queue

ID_TYPES = (numbers.Number, str)
CHANNEL = 'server'
BEFORE_ENQUEUE_ON_ERROR = ('send', 'drop')


class BeforeEnqueueError(Exception):
    """The SDK rejected `before_enqueue` output; the message never contains event values."""


class Client(object):
    class DefaultConfig(object):
        write_key = None
        host = TEST_DATA_PLANE_URL
        on_error = None
        debug = False
        send = True
        sync_mode = False
        max_queue_size = 10000
        gzip = True
        timeout = 15
        max_retries = 10
        proxies = None
        thread = 1
        upload_interval = 0.5
        upload_size = 100
        before_enqueue = None
        before_enqueue_on_error = 'send'

    """Create a new rudderstack client."""
    log = logging.getLogger('rudderstack')
    def __init__(self,
                 write_key=DefaultConfig.write_key,
                 host=DefaultConfig.host,
                 debug=DefaultConfig.debug,
                 max_queue_size=DefaultConfig.max_queue_size,
                 send=DefaultConfig.send,
                 on_error=DefaultConfig.on_error,
                 gzip=DefaultConfig.gzip,
                 max_retries=DefaultConfig.max_retries,
                 sync_mode=DefaultConfig.sync_mode,
                 timeout=DefaultConfig.timeout,
                 proxies=DefaultConfig.proxies,
                 thread=DefaultConfig.thread,
                 upload_size=DefaultConfig.upload_size,
                 upload_interval=DefaultConfig.upload_interval,
                 before_enqueue=DefaultConfig.before_enqueue,
                 before_enqueue_on_error=DefaultConfig.before_enqueue_on_error,):
        """Configure a synchronous dict-to-dict/None hook and its 'send'/'drop' error policy.

        The hook runs once on the calling thread before queueing or sending.
        A dropped event returns (True, None); hook errors never call on_error.
        """
        require('write_key', write_key, str)
        if before_enqueue is not None and not callable(before_enqueue):
            raise AssertionError('before_enqueue must be callable or None')
        if before_enqueue_on_error not in BEFORE_ENQUEUE_ON_ERROR:
            raise AssertionError(
                'before_enqueue_on_error must be one of {0}, got: {1}'.format(
                    BEFORE_ENQUEUE_ON_ERROR, before_enqueue_on_error))

        self.queue = queue.Queue(max_queue_size)
        self.write_key = write_key
        self.on_error = on_error
        self.debug = debug
        self.send = send
        self.sync_mode = sync_mode
        self.host = host
        self.gzip = gzip
        self.timeout = timeout
        self.proxies = proxies
        self.before_enqueue = before_enqueue
        self.before_enqueue_on_error = before_enqueue_on_error

        if debug:
            self.log.setLevel(logging.DEBUG)

        if sync_mode:
            self.consumers = None
        else:
            # On program exit, allow the consumer thread to exit cleanly.
            # This prevents exceptions and a messy shutdown when the
            # interpreter is destroyed before the daemon thread finishes
            # execution. However, it is *not* the same as flushing the queue!
            # To guarantee all messages have been delivered, you'll still need
            # to call flush().
            if send:
                atexit.register(self.join)
            for _ in range(thread):
                self.consumers = []
                consumer = Consumer(
                    self.queue, write_key, host=host, on_error=on_error,
                    upload_size=upload_size, upload_interval=upload_interval,
                    gzip=gzip, retries=max_retries, timeout=timeout,
                    proxies=proxies,
                )
                self.consumers.append(consumer)

                # if we've disabled sending, just don't start the consumer
                if send:
                    consumer.start()

    def identify(self, user_id=None, traits=None, context=None, timestamp=None,
                 anonymous_id=None, integrations=None, message_id=None):
        traits = traits or {}
        context = context or {}
        # putting traits inside context
        context['traits'] = traits
        integrations = integrations or {}
        require('user_id or anonymous_id', user_id or anonymous_id, ID_TYPES)
        require('traits', traits, dict)

        msg = {
            'integrations': integrations,
            'anonymousId': anonymous_id,
            'timestamp': timestamp,
            'context': context,
            'type': 'identify',
            'userId': user_id,
            # 'traits': traits, #traits not needed at root level
            'messageId': message_id,
        }

        return self._enqueue(msg)

    def track(self, user_id=None, event=None, properties=None, context=None,
              timestamp=None, anonymous_id=None, integrations=None,
              message_id=None):
        properties = properties or {}
        context = context or {}
        integrations = integrations or {}
        require('user_id or anonymous_id', user_id or anonymous_id, ID_TYPES)
        require('properties', properties, dict)
        require('event', event, str)

        msg = {
            'integrations': integrations,
            'anonymousId': anonymous_id,
            'properties': properties,
            'timestamp': timestamp,
            'context': context,
            'userId': user_id,
            'type': 'track',
            'event': event,
            'messageId': message_id,
        }

        return self._enqueue(msg)

    def alias(self, previous_id=None, user_id=None, context=None,
              timestamp=None, integrations=None, message_id=None):
        context = context or {}
        integrations = integrations or {}
        require('previous_id', previous_id, ID_TYPES)
        require('user_id', user_id, ID_TYPES)

        msg = {
            'integrations': integrations,
            'previousId': previous_id,
            'timestamp': timestamp,
            'context': context,
            'userId': user_id,
            'type': 'alias',
            'messageId': message_id,
        }

        return self._enqueue(msg)

    def group(self, user_id=None, group_id=None, traits=None, context=None,
              timestamp=None, anonymous_id=None, integrations=None,
              message_id=None):
        traits = traits or {}
        context = context or {}
        integrations = integrations or {}
        require('user_id or anonymous_id', user_id or anonymous_id, ID_TYPES)
        require('group_id', group_id, ID_TYPES)
        require('traits', traits, dict)

        msg = {
            'integrations': integrations,
            'anonymousId': anonymous_id,
            'timestamp': timestamp,
            'groupId': group_id,
            'context': context,
            'userId': user_id,
            'traits': traits,
            'type': 'group',
            'messageId': message_id,
        }

        return self._enqueue(msg)

    def page(self, user_id=None, category=None, name=None, properties=None,
             context=None, timestamp=None, anonymous_id=None,
             integrations=None, message_id=None):
        properties = properties or {}
        context = context or {}
        integrations = integrations or {}
        require('user_id or anonymous_id', user_id or anonymous_id, ID_TYPES)
        require('properties', properties, dict)

        if name:
            require('name', name, str)
        if category:
            require('category', category, str)

        msg = {
            'integrations': integrations,
            'anonymousId': anonymous_id,
            'properties': properties,
            'timestamp': timestamp,
            'category': category,
            'context': context,
            'userId': user_id,
            'type': 'page',
            'name': name,
            'messageId': message_id,
        }

        return self._enqueue(msg)

    def screen(self, user_id=None, category=None, name=None, properties=None,
               context=None, timestamp=None, anonymous_id=None,
               integrations=None, message_id=None):
        properties = properties or {}
        context = context or {}
        integrations = integrations or {}
        require('user_id or anonymous_id', user_id or anonymous_id, ID_TYPES)
        require('properties', properties, dict)

        if name:
            require('name', name, str)
        if category:
            require('category', category, str)

        msg = {
            'integrations': integrations,
            'anonymousId': anonymous_id,
            'properties': properties,
            'timestamp': timestamp,
            'category': category,
            'context': context,
            'userId': user_id,
            'type': 'screen',
            'name': name,
            'messageId': message_id,
        }

        return self._enqueue(msg)
    
    def _enqueue(self, msg):
        """Push a new `msg` onto the queue, return `(success, msg)`"""
        timestamp = msg['timestamp']
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).replace(tzinfo=tzutc())
        message_id = msg.get('messageId')
        if message_id is None:
            message_id = uuid4()

        # default integrations should be "All": True
        if msg['integrations'] == {} :
            msg['integrations'] = {"All" : True}
            
        require('integrations', msg['integrations'], dict)
        require('type', msg['type'], str)
        require('timestamp', timestamp, datetime)
        require('context', msg['context'], dict)

        # add common
        timestamp = guess_timezone(timestamp)
        msg['timestamp'] = timestamp.isoformat()
        msg['messageId'] = stringify_id(message_id)
        msg['context']['library'] = {
            'name': 'analytics-python',
            'version': VERSION
        }
        msg['userId'] = stringify_id(msg.get('userId', None))
        msg['anonymousId'] = stringify_id(msg.get('anonymousId', None))
        msg['channel'] = CHANNEL
        msg = clean(msg)
        msg = self._run_before_enqueue(msg)
        if msg is None:
            return True, None
        self.log.debug('queueing %s event %s.', msg['type'], msg.get('messageId'))

        # Check message size.
        size = msg_size(msg)
        if size > MAX_MSG_SIZE:
            raise RuntimeError(f'Message exceeds {str(int(MAX_MSG_SIZE / 1024))}kb limit. '
                               f'(messageId: {msg.get("messageId")}, size: {size} bytes)')

        # if send is False, return msg as if it was successfully queued
        if not self.send:
            return True, msg

        if self.sync_mode:
            self.log.debug('enqueued with blocking %s.', msg['type'])
            post(self.write_key, self.host, gzip=self.gzip,
                 timeout=self.timeout, proxies=self.proxies, batch=[msg])

            return True, msg

        try:
            self.queue.put(msg, block=False)
            self.log.debug('enqueued %s.', msg['type'])
            return True, msg
        except queue.Full:
            self.log.warning('analytics-python queue is full')
            return False, msg

    def _run_before_enqueue(self, msg):
        """Run `before_enqueue` on a copy of `msg`; return the event to send, or None to drop."""
        if self.before_enqueue is None:
            return msg
        checking_output = False
        try:
            result = self.before_enqueue(copy.deepcopy(msg))
            if result is None:
                self.log.debug('before_enqueue dropped %s event %s.', msg['type'], msg['messageId'])
                return None
            checking_output = True
            return self._check_before_enqueue(msg, result)
        except Exception as e:
            # Never raise into the app; the original is untouched because the hook got a copy.
            # Log the SDK's own reason, or only the class of any other exception: its text may carry event values.
            reason = str(e) if checking_output and isinstance(e, BeforeEnqueueError) else type(e).__name__
            if self.before_enqueue_on_error == 'drop':
                self.log.error('before_enqueue failed, dropping %s event %s: %s',
                               msg['type'], msg['messageId'], reason)
                return None
            self.log.error('before_enqueue failed, sending original %s event %s: %s',
                           msg['type'], msg['messageId'], reason)
            return msg

    def _check_before_enqueue(self, original, msg):
        """Restore reserved fields and re-validate the hook's output; raise if it is not sendable."""
        msg_type = original['type']
        if not isinstance(msg, dict):
            raise BeforeEnqueueError('before_enqueue must return a dict or None')
        if msg.get('type') != msg_type:
            raise BeforeEnqueueError('before_enqueue must not change the event type')
        if msg.get('context') is None:
            # A copy: the hook may retain its return value. Library is restored below, with a warning.
            msg = dict(msg, context={})
        if not isinstance(msg['context'], dict):
            raise BeforeEnqueueError('before_enqueue must return a dict context')
        msg = clean(msg, _active=set())

        if msg['context'].get('library') != original['context']['library']:
            self._warn_reserved('context.library', original)
            msg['context']['library'] = copy.deepcopy(original['context']['library'])
        for field in ('channel', 'messageId'):
            if msg.get(field) != original[field]:
                self._warn_reserved(field, original)
                msg[field] = original[field]

        require_sendable(msg_type, msg)
        msg['userId'] = stringify_id(msg.get('userId'))
        msg['anonymousId'] = stringify_id(msg.get('anonymousId'))
        # Strict wire validation belongs to the hook policy, not the no-hook/fallback path.
        size = len(json.dumps(msg, cls=DatetimeSerializer, allow_nan=False).encode())
        if size > MAX_MSG_SIZE:
            raise BeforeEnqueueError('before_enqueue returned {0} bytes, over the {1} byte limit'.format(
                size, MAX_MSG_SIZE))
        return msg

    def _warn_reserved(self, field, original):
        self.log.warning('before_enqueue changed %s on %s event %s; restoring the pre-hook value.',
                         field, original['type'], original['messageId'])

    def flush(self):
        """Forces a flush from the internal queue to the server"""
        queue = self.queue
        size = queue.qsize()
        queue.join()
        # Note that this message may not be precise, because of threading.
        self.log.debug('successfully flushed about %s items.', size)

    def join(self):
        """Ends the consumer thread once the queue is empty.
        Blocks execution until finished
        """
        for consumer in self.consumers:
            consumer.pause()
            try:
                consumer.join()
            except RuntimeError:
                # consumer thread has not started
                pass

    def shutdown(self):
        """Flush all messages and cleanly shutdown the client"""
        self.flush()
        self.join()


def require(name, field, data_type):
    """Require that the named `field` has the right `data_type`"""
    if not isinstance(field, data_type):
        msg = '{0} must have {1}, got: {2}'.format(name, data_type, field)
        raise AssertionError(msg)


def require_sendable(msg_type, msg):
    """Apply the public methods' required-field rules to a hook's output, without echoing values."""
    if msg_type == 'alias':
        checks = [('previousId', msg.get('previousId'), ID_TYPES),
                  ('userId', msg.get('userId'), ID_TYPES)]
    else:
        checks = [('userId or anonymousId',
                   msg.get('userId') or msg.get('anonymousId'), ID_TYPES)]
    if msg_type == 'track':
        checks.append(('event', msg.get('event'), str))
    if msg_type == 'group':
        checks.append(('groupId', msg.get('groupId'), ID_TYPES))
        checks.append(('traits', msg.get('traits'), dict))
    if msg_type == 'identify':
        checks.append(('context.traits', msg['context'].get('traits'), dict))
    if msg_type in ('track', 'page', 'screen'):
        checks.append(('properties', msg.get('properties'), dict))
    if msg_type in ('page', 'screen'):
        # Optional, as in page()/screen(): checked only when set.
        checks.extend((name, msg.get(name), str) for name in ('name', 'category') if msg.get(name))
    checks.append(('integrations', msg.get('integrations'), dict))
    for name, value, data_type in checks:
        if not isinstance(value, data_type):
            raise BeforeEnqueueError('before_enqueue returned an event without a valid {0}'.format(name))


def msg_size(msg):
    """Serialized size of `msg` in bytes."""
    return len(json.dumps(msg, cls=DatetimeSerializer).encode())


def stringify_id(val):
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return str(val)
