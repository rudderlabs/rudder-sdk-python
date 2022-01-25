import logging
import rudder_analytics

logging.basicConfig()
logging.getLogger('rudder').setLevel('DEBUG')

rudder_analytics.write_key = "test_secret"
rudder_analytics.data_plane_url = "https://hosted.rudderlabs.com"
rudder_analytics.debug = True

rudder_analytics.track(user_id = 'user', event = 'simple_track', properties = {
  'key1' : 'val1'
})

rudder_analytics.identify('user_id', {
    'key1': 'val1'
})
