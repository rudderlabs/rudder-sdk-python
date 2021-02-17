# What is RudderStack?

[RudderStack](https://rudderstack.com/) is a **customer data pipeline** tool for collecting, routing and processing data from your websites, apps, cloud tools, and data warehouse.

More information on RudderStack can be found [here](https://github.com/rudderlabs/rudder-server).

## RudderStack Python SDK

RudderStack’s Python SDK allows you to track your customer event data from your Python code. Once enabled, the event requests hit the RudderStack servers. RudderStack then routes the events to the specified destination platforms as configured by you.

## Getting Started with Python SDK

Install `rudder-sdk-python` using `pip`
```
pip install rudder-sdk-python
```

## Initialize the ```Client```

```
import rudder_analytics

rudder_analytics.write_key = <WRITE_KEY>
rudder_analytics.data_plane_url = <DATA_PLANE_URL>
```

## Send Events

```
rudder_analytics.track('developer_user_id', 'Simple Track Event', {
  'key1': 'val1'
})
```

## Contact Us

If you come across any issues while configuring or using this SDK, feel free to [start a conversation on our [Slack](https://resources.rudderstack.com/join-rudderstack-slack) channel. We will be happy to help you.
