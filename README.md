# RudderStack Python SDK

RudderStack’s Python SDK lets you track events from your Python application. Once enabled, the event requests hit the RudderStack servers. RudderStack then transforms and routes these events to your specified destination platforms.

More details on the Python SDK can be found in our [**documentation**](https://docs.rudderstack.com/stream-sources/rudderstack-sdk-integration-guides/rudderstack-python-sdk)

## Getting Started with Python SDK

Install `rudder-sdk-python` using `pip`:

```
pip install rudder-sdk-python
```

## Initializing the RudderStack Client

```
import rudder_analytics

rudder_analytics.write_key = <SOURCE_WRITE_KEY>
rudder_analytics.data_plane_url = <DATA_PLANE_URL>
```

## Sending Events

Once the RudderStack client is initialized, you can use it to send your customer events. A sample `track` call is shown below:

```
rudder_analytics.track('developer_user_id', 'Simple Track Event', {
  'key1': 'val1'
})
```

For more information on the supported calls, refer to the [**documentation**](https://docs.rudderstack.com/stream-sources/rudderstack-sdk-integration-guides/rudderstack-python-sdk#sending-events-from-rudderstack).

## About RudderStack

[**RudderStack**](https://rudderstack.com/) is a customer data platform for developers.  Our tooling makes it easy to deploy pipelines that collect customer data from every app, website and SaaS platform, then activate it in your warehouse and business tools.

More information on RudderStack can be found [**here**](https://github.com/rudderlabs/rudder-server).

## Contact Us

If you come across any issues while configuring or using this SDK, you can start a conversation on our [**Slack**](https://resources.rudderstack.com/join-rudderstack-slack) channel.
