# -*- coding: utf-8 -*-

"""Tests the rate limiting function for requests"""

import requests

from yoapi.core import limiter
from yoapi.limiters import limit_requests_by_user
from yoapi.helpers import make_json_response
from . import BaseTestCase


class RateLimiterTestCase(BaseTestCase):

    """Tests a bunch of different URLs."""

    def setUp(self):
        super(RateLimiterTestCase, self).setUp()
        self.app.config.setdefault('WHITELISTED_USERNAMES',
                                   self._user2.username)

    def test_whitelist(self):

        status_code = 429

        @limit_requests_by_user('1 per second')
        @self.app.route('/limit_me', login_required=False)
        def limit_me():
            return make_json_response()

        response = None

        # Test that anonymous user is rate limited by client id.
        for _ in range(0, 2):
            response = self.jsonpost('/limit_me', auth=False)
        self.assertEquals(response.status_code, status_code)

        # Test that self._user1 is rate limited.
        for _ in range(0, 2):
            response = self.jsonpost('/limit_me')
        self.assertEquals(response.status_code, status_code)

        # Test that self._user2 isn't rate limited.
        for _ in range(0, 10):
            response = self.jsonpost('/limit_me', jwt_token=self._user2_jwt)
        self.assertNotEquals(response.status_code, status_code)
