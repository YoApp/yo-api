# -*- coding: utf-8 -*-

"""Image model"""

from bson import DBRef
from flask import current_app
from flask_mongoengine import Document
from mongoengine import BooleanField, StringField, CASCADE

from .helpers import ReferenceField, DocumentMixin, URLField
from .user import User


class Image(DocumentMixin, Document):

    meta = {'collection': 'image',
            'indexes': [
                {'fields': ['filename'], 'unique': True},
                {'fields': ['owner']},
                {'fields': ['yo']}],
            'auto_create_index': False}

    # Image filename.
    filename = StringField()

    # Image bitly link.
    short_link = URLField()

    # Public access.
    is_public = BooleanField()

    # The image owner.
    owner = ReferenceField(User, reverse_delete_rule=CASCADE)

    # Optional reference to a Yo
    yo = ReferenceField('Yo')

    def make_full_url(self):
        bucket = current_app.config.get('YO_PHOTO_BUCKET')
        return 'https://s3.amazonaws.com/%s/%s' % (bucket, self.filename)

    def has_dbrefs(self):
        """Checks if there are any users that could not be
        dereferenced."""
        if isinstance(self.owner, DBRef):
            return True

        return False
