import logging
import rudderstack.analytics as analytics
from rudderstack.analytics.get_env import TEST_DATA_PLANE_URL
from rudderstack.analytics.get_env import TEST_WRITE_KEY

logging.basicConfig()
logging.getLogger('rudder').setLevel('DEBUG')

analytics.write_key = TEST_WRITE_KEY
analytics.dataPlaneUrl = TEST_DATA_PLANE_URL
analytics.debug = True

properties = {
  "library": {
    "application": 'Rudder Desktop',
    "version": '1.1.0',
    "platform": 'osx'
  }
}

traits = {
  "firstname": 'First',
  "lastname": 'Last',
  "Role": 'Jedi',
  "age": 25
}

context = {
  "screen": {
    "width": 852,
    "height": 393,
    "density": 3
  },
  "os": {
    "name": 'macOS',
    "version": '2.0.2'
  },
  "locale": 'en-US'
}

context_with_library = {
  "screen": {
    "width": 852,
    "height": 393,
    "density": 3
  },
  "os": {
    "name": 'macOS',
    "version": '2.0.2'
  },
  "locale": 'en-US',
  'library': {
    'name': 'analytics-random-sdk',
    'version': '1.0.0.beta.1'
  }
}

user_id = '123456'
anonymous_id = 'uid'

analytics.track(
  user_id= user_id,
  event= 'Test Track',
  anonymous_id= anonymous_id,
  properties= properties
)

analytics.screen(
  user_id= user_id,
  name= 'Test Screen',
  anonymous_id= anonymous_id,
  properties= properties
)

analytics.identify(
  user_id= '654321',
  traits= traits
)

analytics.group(
  user_id= user_id,
  group_id= "uid",
  anonymous_id= anonymous_id,
  traits= traits
)

analytics.alias(
  user_id= user_id,
  previous_id= '654321'
)

analytics.page(
  user_id= user_id,
  name= 'Test Page',
  anonymous_id= anonymous_id,
  properties= properties
)