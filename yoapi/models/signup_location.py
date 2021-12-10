# -*- coding: utf-8 -*-

"""SignupLocation model"""


from bson import DBRef
from flask_mongoengine import Document
from mongoengine import StringField

from .helpers import DocumentMixin, ReferenceField
from .user import User


class SignupLocation(DocumentMixin, Document):

    """Model for storing sign up locations"""

    meta = {'collection': 'signup_locations',
            'indexes': ['city', 'region_code', 'zip_code', 'metro_code',
                        'area_code'],
            'auto_create_index': False}

    user = ReferenceField(User)
    country_name = StringField()
    country_code = StringField()
    region_name = StringField()
    region_code = StringField()
    city = StringField()
    zip_code = StringField()
    metro_code = StringField()
    area_code = StringField()

    def has_dbrefs(self):
        """Checks if there are any users that could not be
        dereferenced."""
        if isinstance(self.user, DBRef):
            return True

        return False

    def __str__(self):
        return "<SignupLocation '%s'>" % self.user
