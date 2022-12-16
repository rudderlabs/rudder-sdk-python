import logging
import rudderstack.analytics as rudder_analytics
from rudderstack.analytics.get_env import HOST_URL
from rudderstack.analytics.get_env import TEST_SECRET

logging.basicConfig()
logging.getLogger('rudder').setLevel('DEBUG')

rudder_analytics.write_key = TEST_SECRET
rudder_analytics.data_plane_url = HOST_URL
rudder_analytics.debug = True

rudder_analytics.track(user_id = 'user', event = 'simple_track', properties = {
  'key1' : 'val1'
})

rudder_analytics.identify('user_id', {
    'key1': 'val1'
})
