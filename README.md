<p align="center">
  <a href="https://rudderstack.com/">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://cdn.rudderlabs.com/brand/logo_watermark_dark.png">
      <img alt="RudderStack" width="512" src="https://cdn.rudderlabs.com/brand/logo_watermark_light.png">
    </picture>
  </a>
</p>

# RudderStack Python SDK

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/rudderlabs/rudder-sdk-python)

RudderStack’s Python SDK lets you track events from your Python application. Once enabled, the event requests hit the RudderStack servers. RudderStack then transforms and routes these events to your specified destination platforms.

More details on the Python SDK can be found in our [**documentation**](https://docs.rudderstack.com/stream-sources/rudderstack-sdk-integration-guides/rudderstack-python-sdk)

## Getting Started with Python SDK

Install `rudder-sdk-python` using `pip`:

```bash
pip install rudder-sdk-python
```

## Initializing the RudderStack Client

```python
import rudderstack.analytics as analytics

analytics.write_key = <SOURCE_WRITE_KEY>
analytics.on_error = <FAILURE CALLBACK>
analytics.debug = <True or False>
analytics.dataPlaneUrl = <RUDDERSTACK_DATA_PLANE_URL>

analytics.gzip = <True or False>
```

## Sending Events

Once the RudderStack client is initialized, you can use it to send your customer events. A sample `track` call is shown below:

```python
rudder_analytics.track('developer_user_id', 'Simple Track Event', {
  'key1': 'val1'
})
analytics.track('user_id', 'Simple Track Event', anonymous_id='anonymousId',
  properties={
  'key1': 'val1'
}, context={
  'key1': 'val1'
})
```

For more information on the supported calls, refer to the [**documentation**](https://docs.rudderstack.com/stream-sources/rudderstack-sdk-integration-guides/rudderstack-python-sdk#sending-events-from-rudderstack).

## Editing or dropping events before enqueue

Set `before_enqueue` to edit or drop events before they leave your process. It
runs once per event, on the calling thread, after the SDK fills in `messageId`,
`timestamp`, `channel` and `context`. It receives its own copy of the event as a
dict. Return the (possibly edited) dict to send it, or `None` to drop it.

```python
import rudderstack.analytics as analytics


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


analytics.before_enqueue = before_enqueue
# This hook redacts PII, so never fall back to the unredacted original
analytics.before_enqueue_on_error = 'drop'
```

The same options are available as `Client(..., before_enqueue=..., before_enqueue_on_error=...)`.

- Returning `None` drops the event, including a hook that ends without a `return`.
- A dropped event is not an error: `Client` methods return `(True, None)` and `on_error` is not called.
- If the hook raises an `Exception`, returns something other than a dict or `None`,
  changes the event `type`, removes a required field (`userId` or `anonymousId`,
  `event` on track, `groupId` on group, `previousId` and `userId` on alias), or
  returns unencodable data (including `NaN` or infinity), or grows the event past
  the 4 MB limit, the SDK logs an error and, by default
  (`'send'`), sends the original event. Set `before_enqueue_on_error = 'drop'`
  to drop it instead. The error is never raised to your app.
- Changes to `context.library`, `channel` and `messageId` are reverted with a warning.
- The hook must be thread-safe if you call the SDK from several threads.
- `sentAt` is absent from the hook input; the SDK sets it on the batch when sending.
- `KeyboardInterrupt` and `SystemExit` propagate. Avoid including event data in
  exceptions printed by your application or runtime.
- SDK logs omit event payloads, including without a hook. Oversize errors keep
  their existing type and prefix but report the message ID and size.

## Proxy configuration

Pass `proxies` when you create a `Client`. A Requests-style mapping is preferred:

```python
from rudderstack.analytics.client import Client

client = Client(
    'SOURCE_WRITE_KEY',
    host='https://YOUR_DATA_PLANE_URL',
    proxies={
        'http': 'http://proxy.example:8080',
        'https': 'http://proxy.example:8080',
    },
)
```

A legacy string such as `proxy.example:8080` is also supported. The SDK applies
the string to both HTTP and HTTPS requests. If the string has no scheme, the SDK
adds `http://`. An existing scheme is preserved.

Configured proxies are now used for event requests. Earlier versions ignored
this option. Check that any existing proxy configuration is reachable before
upgrading.

## About RudderStack

[**RudderStack**](https://rudderstack.com/) is a customer data platform for developers. Our tooling makes it easy to deploy pipelines that collect customer data from every app, website and SaaS platform, then activate it in your warehouse and business tools.

More information on RudderStack can be found [**here**](https://github.com/rudderlabs/rudder-server).

## Contact Us

For more information on any of the sections covered in this readme, you can [**contact us**](mailto:%20docs@rudderstack.com) or start a conversation on our [**Slack**](https://resources.rudderstack.com/join-rudderstack-slack) channel.
