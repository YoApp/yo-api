# -*- coding: utf-8 -*-

"""Device model"""


from bson import DBRef
from flask_mongoengine import Document
from mongoengine import BooleanField, StringField

from .helpers import ReferenceField
from .user import User


class Device(Document):

    """This model has been deprecated.

    We are moving away from this model in favor of `Endpoints`.
    """

    meta = {'collection': 'device',
            'indexes': [
                {'fields': ['owner']},
                {'fields': ['installation_id'], 'unique': True,
                                                'sparse': True}],
            'auto_create_index': False}

    # Push token uniquely identifying a particular installation of the Yo app.
    # These tokens can expire and be automatically re-issued, so further
    # research is necessary. All we know at the moment is that there is an
    # SNS topic responsible for notifying us of such changes.
    token = StringField(primary_key=True)

    # Owner who subscribes to target.
    owner = ReferenceField(User)

    # Device type.
    device_type = StringField(required=True)

    # Boolean indicator for device disabled as reported by SNS.
    disabled = BooleanField()

    # installation_id is a unique identifier to tie this endpoint arn
    # to a particular installation
    installation_id = StringField()

    def get_dict(self):
        return {
            'device_token': self.token,
            'device_type': self.device_type,
            'owner': self.owner.user_id
        }

    def has_dbrefs(self):
        """Checks if there are any users that could not be
        dereferenced."""
        if isinstance(self.owner, DBRef):
            return True

        return False

    def to_dict(self):
        """Returns a dictionary representation of the document"""
        return self.to_mongo().to_dict()
