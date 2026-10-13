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
    body["sentAt"] = datetime.now(timezone.utc).replace(
        tzinfo=tzutc()).isoformat()
    url = (remove_trailing_slash(host or 'https://api.rudderstack.com') +
           '/v1/batch')
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

    try:
        res = _session.post(url, **kwargs)
    except RequestException as error:
        raise sanitize_exception(error) from None

    if res.status_code == 200:
        log.debug('data uploaded successfully')
        return res

    try:
        payload = res.json()
        log.debug('received error response with status %s', res.status_code)
    except ValueError:
        code = 'unknown'
        message = res.text
    else:
        code = 'unknown'
        message = payload
        if isinstance(payload, dict):
            code = payload.get('code') or 'unknown'
            message = payload.get('message')
            if message is None:
                message = payload.get('error')
            if message is None:
                message = getattr(res, 'text', payload)

    raise APIError(
        res.status_code,
        _sanitize_text(code, write_key),
        _sanitize_text(message, write_key))


def _gzip_json(data):
    buf = BytesIO()
    with GzipFile(fileobj=buf, mode='w') as gz:
        # 'data' was produced by json.dumps(),
        # whose default encoding is utf-8.
        gz.write(data.encode('utf-8'))
    return buf.getvalue()


def _sanitize_text(value, write_key=None):
    text = str(value)
    if write_key:
        text = text.replace(write_key, '[REDACTED]')
        encoded_key = base64.b64encode(
            ('{0}:'.format(write_key)).encode('utf-8')).decode('ascii')
        text = text.replace(encoded_key, '[REDACTED]')
    return re.sub(
        r'''(?ix)(
            ["']?authorization["']?\s*[:=]\s*
            ["']?
            (?:(?:basic|bearer)\s+)?
        )[^"',}\]\s;]+''',
        r'\1[REDACTED]',
        text)


def sanitize_exception(error, write_key=None):
    """Return an exception safe to expose through logs or callbacks."""
    if isinstance(error, UploadError):
        return UploadError(_sanitize_text(error.reason, write_key))
    if isinstance(error, APIError):
        return APIError(
            error.status,
            _sanitize_text(error.code, write_key),
            _sanitize_text(error.message, write_key))
    return UploadError(type(error).__name__)


class UploadError(Exception):
    """Credential-free error raised when an upload cannot finish."""

    def __init__(self, reason):
        self.reason = reason

    def __str__(self):
        return '[rudderstack] upload failed ({0})'.format(self.reason)


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
