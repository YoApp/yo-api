# -*- coding: utf-8 -*-

"""Flask extension pacakge for Facebook"""

import sys

from flask import current_app
from facebook import GraphAPI, GraphAPIError

from . import FlaskExtension
from ..errors import APIError


class Facebook(FlaskExtension):

    """A helper class for managing a the facebook API calls"""

    EXTENSION_NAME = 'facebook'

    def __init__(self, app=None):
        super(Facebook, self).__init__(app=app)

    def _create_instance(self, app):
        """Init and store the facebook graphapi object on the stack on
        first use."""
        client = GraphAPI(version='2.3')
        return client

    def get_profile(self, token, fields=None):
        """Get a user profile via token"""
        try:
            if fields:
                fields = ','.join(fields)
                profile = self.instance.get_object('me', access_token=token,
                                                   fields=fields)
            else:
                profile = self.instance.get_object('me', access_token=token)
        except GraphAPIError as err:
            """We probably don't actually care about an error here but
            lets get notified to be safe"""
            payload = {'fb_result': err.result,
                       'fb_type': err.type}
            current_app.log_exception(sys.exc_info())
            raise APIError(payload=payload, message=err.message)

        return profile

    def get_profile_picture(self, token):
        """Get a user profile picture via token"""
        try:
            picture_data = self.instance.get_object('me/picture', width=9999,
                height=9999, redirect=False, access_token=token)
        except GraphAPIError as err:
            """We probably don't actually care about an error here but
            lets get notified to be safe"""
            current_app.log_exception(sys.exc_info())
            self.instance.access_token = None
            return None

        return picture_data.get('data')
