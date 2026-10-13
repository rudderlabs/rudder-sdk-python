from datetime import date, datetime, timezone
from io import BytesIO
from gzip import GzipFile
import logging
import json
import base64
import re
from dateutil.tz import tzutc
from requests.auth import HTTPBasicAuth
from requests import RequestException, sessions

from rudderstack.analytics.version import VERSION
from rudderstack.analytics.utils import remove_trailing_slash

_session = sessions.Session()


def post(write_key, host=None, gzip=True, timeout=15, proxies=None, **kwargs):
    """Post the `kwargs` to the API"""
    log = logging.getLogger('rudderstack')
    body = kwargs
    body["sentAt"] = datetime.now(timezone.utc).replace(tzinfo=tzutc()).isoformat()
    url = remove_trailing_slash(host or 'https://api.rudderstack.com') + '/v1/batch'
    auth = HTTPBasicAuth(write_key, '')
    data = json.dumps(body, cls=DatetimeSerializer)
    log.debug('making request: %s', data)
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'analytics-python/' + VERSION
    }
    if gzip:
        headers['Content-Encoding'] = 'gzip'
        data = _gzip_json(data)

    kwargs = {
        "data": data,
        "auth": auth,
        "headers": headers,
        "timeout": timeout,
    }

    if proxies:
        # Older SDK versions accepted a single proxy string.
        if isinstance(proxies, str):
            proxy_url = proxies if '://' in proxies else 'http://' + proxies
            proxies = {'http': proxy_url, 'https': proxy_url}
        kwargs['proxies'] = proxies

    safe_error = None
    try:
        res = _session.post(url, **kwargs)
    except RequestException as error:
        safe_error = _redact_request_exception(error, write_key)
    # Raised outside the handler so the original error, whose request holds
    # the Authorization header, is not kept as __context__.
    if safe_error is not None:
        raise safe_error

    if res.status_code == 200:
        log.debug('data uploaded successfully')
        return res

    try:
        payload = res.json()
        log.debug('received response: %s',
                  _sanitize_text(str(payload), write_key))
        raise APIError(res.status_code, payload['code'],
                       _sanitize_text(payload['message'], write_key))
    except ValueError:
        raise APIError(res.status_code, 'unknown',
                       _sanitize_text(res.text, write_key))

def _gzip_json(data):
    buf = BytesIO()
    with GzipFile(fileobj=buf, mode='w') as gz:
        # 'data' was produced by json.dumps(),
        # whose default encoding is utf-8.
        gz.write(data.encode('utf-8'))
    return buf.getvalue()


def _sanitize_text(text, write_key):
    """Redact the write key, its Basic auth form and Authorization values."""
    if not isinstance(text, str):
        return text
    if write_key:
        encoded_key = base64.b64encode(
            '{0}:'.format(write_key).encode('utf-8')).decode('ascii')
        text = text.replace(encoded_key, '[REDACTED]')
        text = text.replace(write_key, '[REDACTED]')
    return re.sub(
        r'''(?ix)(
            ["']?authorization["']?\s*[:=]\s*
            ["']?
            (?:(?:basic|bearer)\s+)?
        )[^"',}\]\s;]+''',
        r'\1[REDACTED]',
        text)


def _redact_request_exception(error, write_key):
    """Return the same requests exception type without request/response."""
    message = _sanitize_text(str(error), write_key)
    try:
        return type(error)(message)
    except Exception:
        return RequestException(message)

class APIError(Exception):

    def __init__(self, status, code, message):
        self.message = message
        self.status = status
        self.code = code

    def __str__(self):
        msg = "[rudderstack] {0}: {1} ({2})"
        return msg.format(self.code, self.message, self.status)


class DatetimeSerializer(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()

        return json.JSONEncoder.default(self, obj)
