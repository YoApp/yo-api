# -*- coding: utf-8 -*-

"""Header model"""


from bson import DBRef
from flask_mongoengine import Document
from mongoengine import StringField, BooleanField

from .helpers import DocumentMixin, ReferenceField, URLField
from .user import User
from ..constants.payload import VALID_PAYLOAD_TYPES


class Header(DocumentMixin, Document):
    """MongoDB Header model."""

    meta = {'collection': 'header',
            'indexes': [{'fields': ['user'], 'sparse': True},
                        {'fields': ['yo_type', 'group_yo', 'is_default']},
                        {'fields': ['yo_type', 'group_yo']}],
            'auto_create_index': False}

    # the type of yo that this header can be used for.
    yo_type = StringField(required=True, choices=VALID_PAYLOAD_TYPES)

    # whether this should be used for group yos.
    group_yo = BooleanField(required=True)

    # Is this the default for this type/group?
    is_default = BooleanField()

    # Message copy for beginning of the message.
    # This will be truncated if the message is too long.
    sms = StringField(required=True)
    push = StringField(required=True)

    # Message copy for the end of the message.
    # This will never be truncated.
    ending = StringField(required=True)

    # user that owns this header
    user = ReferenceField(User)

    # link for reengagement pushes
    link = URLField()

    def has_dbrefs(self):
        """Checks if there are any users that could not be
        dereferenced."""
        if isinstance(self.user, DBRef):
            return True

        return False

    @property
    def header_id(self):
        return str(self.id) if self.id else None
