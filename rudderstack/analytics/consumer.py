import logging
import time
from threading import Thread
import backoff
import json

from rudderstack.analytics.request import post, APIError, DatetimeSerializer

from queue import Empty

# The data plane rejects request bodies larger than 4000 KB (rudder-server's
# Gateway.maxReqSizeInKB, checked after gzip decompression) with a 413, and a
# 4xx is not retried, so the whole batch would be lost. Batches are kept a
# little below that to leave space for the request envelope, eg. "sentAt".
MAX_REQUEST_SIZE = 4000 << 10
BATCH_SIZE_LIMIT = MAX_REQUEST_SIZE - (1 << 10)
# A message must fit in a batch on its own.
MAX_MSG_SIZE = BATCH_SIZE_LIMIT
# Messages in the batch array are separated by ", ".
ITEM_SEPARATOR_SIZE = 2


class Consumer(Thread):
    """Consumes the messages from the client's queue."""
    log = logging.getLogger('rudderstack')

    def __init__(self, queue, write_key, upload_size=100, host=None,
                 on_error=None, upload_interval=0.5, gzip=True, retries=10,
                 timeout=15, proxies=None):
        """Create a consumer thread."""
        Thread.__init__(self)
        # Make consumer a daemon thread so that it doesn't block program exit
        self.daemon = True
        self.upload_size = upload_size
        self.upload_interval = upload_interval
        self.write_key = write_key
        self.host = host
        self.on_error = on_error
        self.queue = queue
        self.gzip = gzip
        # It's important to set running in the constructor: if we are asked to
        # pause immediately after construction, we might set running to True in
        # run() *after* we set it to False in pause... and keep running
        # forever.
        self.running = True
        self.retries = retries
        self.timeout = timeout
        self.proxies = proxies
        # A message that did not fit in the previous batch, with its size.
        self._pending = None

    def run(self):
        """Runs the consumer."""
        self.log.debug('consumer is running...')
        while self.running:
            self.upload()

        self.log.debug('consumer exited.')

    def pause(self):
        """Pause the consumer."""
        self.running = False

    def upload(self):
        """Upload the next batch of items, return whether successful."""
        success = False
        batch = self.next()
        if len(batch) == 0:
            return False

        try:
            self.request(batch)
            success = True
        except Exception as e:
            self.log.error('error uploading: %s', e)
            success = False
            if self.on_error:
                self.on_error(e, batch)
        finally:
            # mark items as acknowledged from queue
            for _ in batch:
                self.queue.task_done()
        return success

    def next(self):
        """Return the next batch of items to upload."""
        queue = self.queue
        items = []

        start_time = time.monotonic()
        total_size = 0

        if self._pending is not None:
            item, item_size = self._pending
            self._pending = None
            items.append(item)
            total_size += item_size

        while len(items) < self.upload_size:
            elapsed = time.monotonic() - start_time
            if elapsed >= self.upload_interval:
                break
            try:
                item = queue.get(
                    block=True, timeout=self.upload_interval - elapsed)
            except Empty:
                break
            try:
                item_size = len(json.dumps(
                    item, cls=DatetimeSerializer).encode())
            except Exception as e:
                self.log.exception('Exception: %s', e)
                # The item is dropped, so it is done for queue.join().
                queue.task_done()
                continue
            if item_size > MAX_MSG_SIZE:
                self.log.error(
                    'Item exceeds 4000kb limit, dropping. (%s)', str(item))
                # The item is dropped, so it is done for queue.join().
                queue.task_done()
                continue
            if items:
                item_size += ITEM_SEPARATOR_SIZE
            if total_size + item_size > BATCH_SIZE_LIMIT:
                # Send it with the next batch instead of making this one
                # too large for the data plane. It is still unfinished in the
                # queue, so flush() waits for it.
                self._pending = (item, item_size - ITEM_SEPARATOR_SIZE)
                self.log.debug(
                    'hit batch size limit (size: %d)', total_size)
                break
            items.append(item)
            total_size += item_size

        return items

    def request(self, batch):
        """Attempt to upload the batch and retry before raising an error """

        def fatal_exception(exc):
            if isinstance(exc, APIError):
                # retry on server errors and client errors
                # with 429 status code (rate limited),
                # don't retry on other client errors
                return (400 <= exc.status < 500) and exc.status != 429
            else:
                # retry on all other errors (eg. network)
                return False

        @backoff.on_exception(
            backoff.expo,
            Exception,
            max_tries=self.retries + 1,
            giveup=fatal_exception)
        def send_request():
            post(self.write_key, self.host, gzip=self.gzip,
                 timeout=self.timeout, batch=batch, proxies=self.proxies)

        send_request()
