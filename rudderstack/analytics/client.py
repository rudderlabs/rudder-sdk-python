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


class _MessageTooBig(RuntimeError):
    """Separate the normal size error from hook and serialization failures."""


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
        if self.before_enqueue is None or isinstance(context, dict):
            context['traits'] = traits
        integrations = integrations or {}
        if self.before_enqueue is None:
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
        if self.before_enqueue is None:
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
        if self.before_enqueue is None:
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
        if self.before_enqueue is None:
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
        if self.before_enqueue is None:
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
        if self.before_enqueue is None:
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
            
        if self.before_enqueue is None:
            require('integrations', msg['integrations'], dict)
            require('type', msg['type'], str)
            require('timestamp', timestamp, datetime)
            require('context', msg['context'], dict)

        # add common
        if self.before_enqueue is None or isinstance(timestamp, datetime):
            timestamp = guess_timezone(timestamp)
            msg['timestamp'] = timestamp.isoformat()
        else:
            msg['timestamp'] = timestamp
        msg['messageId'] = stringify_id(message_id)
        if self.before_enqueue is None or isinstance(msg['context'], dict):
            msg['context']['library'] = {
                'name': 'analytics-python',
                'version': VERSION
            }
        msg['userId'] = stringify_id(msg.get('userId', None))
        msg['anonymousId'] = stringify_id(msg.get('anonymousId', None))
        msg['channel'] = CHANNEL
        msg = clean(msg)
        if self.before_enqueue is not None:
            msg = self._run_before_enqueue(msg)
            if msg is None:
                return True, None
        self.log.debug('queueing: %s', msg)

        # Check message size.
        msg_size = len(json.dumps(msg, cls=DatetimeSerializer).encode())
        if msg_size > MAX_MSG_SIZE:
            raise RuntimeError(f'Message exceeds {str(int(MAX_MSG_SIZE / 1024))}kb limit. ({str(msg)})')

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

    def _validate_before_enqueue(self, msg, msg_type=None):
        """Validate enriched hook results and originals using the call's rules."""
        msg_type = msg_type or msg['type']
        if msg_type == 'alias':
            require('previous_id', msg.get('previousId'), ID_TYPES)
            require('user_id', msg.get('userId'), ID_TYPES)
        else:
            require('user_id or anonymous_id', msg.get('userId') or msg.get('anonymousId'), ID_TYPES)
        fields = {
            'track': [('properties', msg.get('properties', {}), dict), ('event', msg.get('event'), str)],
            'group': [('group_id', msg.get('groupId'), ID_TYPES), ('traits', msg.get('traits', {}), dict)],
            'identify': ([('traits', msg.get('context', {}).get('traits', {}), dict)]
                         if msg_type == 'identify' else []),
            'page': [('properties', msg.get('properties', {}), dict)],
            'screen': [('properties', msg.get('properties', {}), dict)],
        }
        for name, value, data_type in fields.get(msg_type, []):
            require(name, value, data_type)
        if msg_type in ('page', 'screen'):
            for field in ('name', 'category'):
                if msg.get(field):
                    require(field, msg[field], str)
        require('integrations', msg.get('integrations', {}), dict)
        require('type', msg.get('type'), str)
        require('timestamp', msg.get('timestamp'), (str, datetime))
        require('context', msg.get('context', {}), dict)
        msg_size = len(json.dumps(msg, cls=DatetimeSerializer).encode())
        if msg_size > MAX_MSG_SIZE:
            raise _MessageTooBig(f'Message exceeds {str(int(MAX_MSG_SIZE / 1024))}kb limit. ({str(msg)})')

    def _run_before_enqueue(self, msg):
        """Run the hook on a deep copy; return its event, the original, or None."""
        try:
            result = self.before_enqueue(copy.deepcopy(msg))
            if result is None:
                self.log.debug('before_enqueue dropped %s event %s.', msg['type'], msg['messageId'])
                return None
            require('before_enqueue result (dict or None)', result, dict)
            self._validate_before_enqueue(result, msg_type=msg['type'])
            library = {'name': 'analytics-python', 'version': VERSION}
            context = result.setdefault('context', {})
            if result.get('channel') != CHANNEL or context.get('library') != library:
                self.log.warning('before_enqueue changed channel or context.library; they were restored.')
            result['channel'] = CHANNEL
            context['library'] = library
            if not result.get('messageId'):
                result['messageId'] = msg['messageId']
            return result
        except _MessageTooBig as error:
            raise RuntimeError(str(error)) from None
        except Exception as error:
            drop = self.before_enqueue_on_error == 'drop'
            self.log.error('before_enqueue failed for %s event %s, %s. %s',
                           msg['type'], msg['messageId'],
                           'dropping the event' if drop else 'sending the original event', error)
            if drop:
                return None
            try:
                self._validate_before_enqueue(msg)
            except _MessageTooBig as error:
                raise RuntimeError(str(error)) from None
            return msg

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


def stringify_id(val):
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return str(val)
