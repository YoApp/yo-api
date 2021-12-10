# -*- coding: utf-8 -*-

"""PubSub module"""

import sys
import gevent

from flask import json, g
from redis.exceptions import ConnectionError

from . import FlaskExtension
from ..core import redis
from ..helpers import copy_current_request_context


class AlreadyRegisteredError(Exception):
    pass

class RedisPubSub(FlaskExtension):
    """A flask extension class for RedisPubSub"""

    EXTENSION_NAME = 'redis-pubsub'

    def _create_instance(self, app):
        """Init and store the twilio object on the stack on first use."""
        return _RedisPubSub(app)


class _RedisPubSub(object):
    """A helper for managing Redis based PubSub

    This module spawns a greenlet whose only responsibility is to wait for
    incoming messages on redis. The listen() command blocks until the next
    message comes through, which makes the greenlet cheap and efficient.
    """

    REDIS_CHAN = 'yochan'

    # Active greenlet instance for redis monitoring.
    greenlet = None

    def __init__(self, app):
        self.app = app
        self.callbacks = dict()
        self.greenlet = None
        self.pubsub = redis.pubsub()
        self.pubsub.subscribe(self.REDIS_CHAN)

    def __iter_data(self):
        try:
            for message in self.pubsub.listen():
                data = message.get('data')
                channel = message.get('channel')
                if message['type'] == 'message':
                    yield channel, json.loads(data)
        except (AttributeError, ConnectionError):
            self.app.log_exception(sys.exc_info())


    @property
    def channels(self):
        """Returns all subscribed channels"""
        return self.pubsub.channels

    def close(self):
        """Unsubscribe from all subscriptions"""
        for channel in self.pubsub.channels:
            self.pubsub.unsubscribe(channel)
        self.pubsub.close()
        self.callbacks = dict()

    def publish(self, message, channel=None):
        """Register a WebSocket connection for Redis updates."""
        if not isinstance(message, dict):
            raise TypeError('Message not a dict')
        if not channel:
            raise ValueError('Channel name required')
        redis.publish(channel, json.dumps(message))

    def register(self, callback, channels):
        """Register a WebSocket connection for Redis updates."""
        if channels is None:
            raise ValueError('At least one channel must be specified')
        if not isinstance(channels, list):
            channels = [channels]
        if not self.started:
            self.start()
        for channel in channels:
            if channel not in self.callbacks:
                self.callbacks[channel] = []
            if callback not in self.callbacks[channel]:
                self.callbacks[channel].append(callback)
            else:
                message = 'Callback already registered for %s' % channel
                raise AlreadyRegisteredError(message)
            if channel not in self.pubsub.channels:
                self.pubsub.subscribe(channel)

    def run(self):
        """Listens for new messages in Redis, and sends them to clients."""
        for channel, data in self.__iter_data():
            # If the next message is for the open channel then iterate over all
            # connected clients. Otherwise, pick out the clients stored in the
            # clients dictionary under the channel id.
            if channel in self.callbacks:
                for callback in self.callbacks[channel]:
                    try:
                        callback(data)
                    except:
                        self.app.log_exception(sys.exc_info())

    def start(self):
        """Maintains Redis subscription in the background."""
        if not self.started:
            self.greenlet = gevent.spawn(copy_current_request_context(self.run))

    @property
    def started(self):
        """Checks if the redis monitor has been started"""
        return self.greenlet and self.greenlet.started

    def stop(self):
        """Kills the redis consumer greenlet"""
        gevent.kill(self.greenlet)
        self.greenlet = None
        self.pubsub.unsubscribe(self.REDIS_CHAN)

    def unregister(self, callback, channels):
        """Unregister a WebSocket connection for Redis updates."""
        if not isinstance(channels, list):
            channels = [channels]
        for channel in channels:
            if channel in self.callbacks:
                self.callbacks[channel].remove(callback)
                # If the channel is now empty then we unsubscribe.
                if not self.callbacks[channel]:
                    self.pubsub.unsubscribe(channel)
                    del self.callbacks[channel]

