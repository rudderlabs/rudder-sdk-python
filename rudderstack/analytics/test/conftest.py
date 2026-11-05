"""Mock event transport for hook unit and conformance tests."""
from unittest import mock

import pytest


@pytest.fixture
def wire():
    with mock.patch('rudderstack.analytics.request._session.post') as post:
        post.return_value.status_code = 200
        yield post
