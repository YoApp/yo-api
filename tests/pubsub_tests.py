
# -*- coding: utf-8 -*-

"""Tests pubsub functionality."""

import gevent
import time
import requests

from flask import json
from gevent.queue import Queue
from yoapi.urltools import UrlHelper

from . import BaseTestCase

from yoapi.services import redis_pubsub
from yoapi.extensions.pubsub import AlreadyRegisteredError


class PubSubTestCase(BaseTestCase):

    counter = 0
    payload = {'Hello': 'World'}

    def callback(self, data):
        """Callback for pubsub messages"""
        self.assertEquals(data, self.payload)
        self.counter += 1

    def callback_b(self, data):
        """Callback for pubsub messages"""
        self.assertEquals(data, self.payload)
        self.counter += 1

    def test_channel(self):
        """Test that redis pubsub works"""

        channel = 'test-channel'

        with self.app.test_request_context():
            self.become(self._user1)
            # Register the client and start the pubsub manager.
            redis_pubsub.register(self.callback, channel)

            # Check that the call counter increments as expected.
            redis_pubsub.publish(self.payload, channel=channel)
            # Allow for context switch so our message gets processed.
            gevent.sleep(0.01)
            self.assertEquals(self.counter, 1)

            # Check that the call counter does not increment if we publish to a
            # different channel.
            redis_pubsub.publish(self.payload, channel='other-channel')
            # Allow for context switch so our message gets processed.
            gevent.sleep(0.01)
            self.assertEquals(self.counter, 1)

            redis_pubsub.close()

    def test_unregister(self):

        channel = 'test-channel'

        with self.app.test_request_context():
            self.become(self._user1)
            # Test that registered channel is subscribed.
            redis_pubsub.register(self.callback, channel)
            self.assertIn(channel, redis_pubsub.channels)

            # Test that registering the same channel and same function raises
            # an error.

            self.assertRaises(AlreadyRegisteredError, redis_pubsub.register,
                              self.callback, channel)

            # Register another listener on the same channel and unregister the
            # first registration.
            redis_pubsub.register(self.callback_b, channel)
            redis_pubsub.unregister(self.callback, channel)

            # Assert the channel is still subscribed.
            self.assertIn(channel, redis_pubsub.channels)

            # Unsubscribe the second registration and assert that the channel is
            # no longer subscribed.
            redis_pubsub.unregister(self.callback_b, channel)
            redis_pubsub.close()
