<p align="center">
  <a href="https://rudderstack.com/">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/rudderlabs/rudder-sdk-js/develop/assets/rs-logo-full-dark.png">
      <img alt="RudderStack" width="512" src="https://raw.githubusercontent.com/rudderlabs/rudder-sdk-js/develop/assets/rs-logo-full-light.jpg">
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
