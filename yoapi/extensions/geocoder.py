# -*- coding: utf-8 -*-

"""Google Maps api Geocoder module"""

from pygeocoder import Geocoder as BaseGeocoder

from . import FlaskExtension


class Geocoder(FlaskExtension):

    """A helper class for managing the Geocoder"""

    EXTENSION_NAME = 'google-geocoder'

    def __init__(self, app=None):
        super(Geocoder, self).__init__(app=app)

    def _create_instance(self, app):
        """Init and store the Geocoder object on the stack on first use."""
        # TODO: In the future use the premere google service with an api_token
        geocoder = BaseGeocoder()
        return geocoder
