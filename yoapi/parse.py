# -*- coding: utf-8 -*-

"""Parse cloud support module"""

from .errors import APIError
from .helpers import gevent_thread
from parse_rest.connection import register as init_parse, ParseBatcher
from parse_rest.core import ResourceRequestBadRequest, ResourceRequestNotFound
from parse_rest.installation import Push, Installation
from parse_rest.user import User
from parse_rest.datatypes import Object


class Follower(Object):
    pass


class Parse(object):

    """A helper class to manage the Parse python library."""

    def __init__(self, app=None):
        if app:
            self.init_app(app)
        # Build a few data types using the Parse Object factory method.

    def init_app(self, app):
        # The parse REST client for python supports only a single
        # configuration so it can't be used by multiple applications
        # against different databases.
        init_parse(app.config.get('PARSE_APPLICATION_ID'),
                   app.config.get('PARSE_REST_API_KEY'),
                   master_key=app.config.get('PARSE_MASTER_KEY'))

    def login_with_token(self, token):
        session_header = {'X-Parse-Session-Token': token}
        try:
            return User.GET(
                User.ENDPOINT_ROOT + '/me', extra_headers=session_header)
        except ResourceRequestNotFound:
            raise APIError('Invalid parse session token')

    def push(self, channels, payload):
        """Pushes a message to one or more channels (recipients).

        Args:
            message: The payload.
            channels: A list of usernames or a string username.
        """
        if isinstance(channels, basestring):
            channels = [channels]
        Push._send(data=payload, channels=channels)

    def subscribe(self, user, device_type, token):
        """Subscribes a device from push notifications"""

        # Android registration is handled by the Parse SDK
        if device_type != 'ios':
            return

        def _newest(results):
            max_updated = None
            newest_result = None
            for result in results:
                if not max_updated or max_updated > result.updatedAt:
                    max_created = result.updatedAt
                    newest_result = result
            return newest_result

        subscriptions = Installation.Query.filter(deviceToken=token)
        subscription = _newest(subscriptions)
        if not subscription:
            subscription = Installation(deviceToken=token,
                                        deviceType=device_type,
                                        channels=[user.username])
        subscription.channels = [user.username]
        subscription.save()

    def unsubscribe(self, user, token):
        """Unsubscribes a device from push notifications"""

        # Android registration is handled by the Parse SDK
        # However, removing the channels twice should not
        # cause any issues so ignore the device_type

        subscriptions = Installation.Query.filter(deviceToken=token)
        for subscription in subscriptions:
            subscription.channels = []
            subscription.save()
