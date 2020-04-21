import logging
import rudder_analytics

logging.basicConfig()
logging.getLogger('rudder').setLevel('DEBUG')

rudder_analytics.write_key = "1arY3oVVVTHxHWjYXjx6dFWRSze"
rudder_analytics.data_plane_url = "https://1b38a868.ngrok.io"
rudder_analytics.debug = True

rudder_analytics.track('user_id', 'simple_track', {
  'key1' : 'val1'
})

rudder_analytics.identify('user_id', {
    'key1': 'val1'
})
