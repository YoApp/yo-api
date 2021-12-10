# -*- coding: utf-8 -*-

"""WatchPromo model"""

from flask_mongoengine import Document
from mongoengine import StringField, LongField

from .helpers import DocumentMixin, URLField



class WatchPromo(DocumentMixin, Document):

    meta = {'collection': 'watch_promo',
            'indexes': [
                {'fields': ['username'], 'unique': True}],
            'auto_create_index': False}

    # username to display.
    username = StringField(required=True)

    # index in spreadsheet
    rank = LongField()

    # URL for service
    url = URLField()

    # A long description to display with the item.
    description = StringField()

    # Filename of the profile picture.
    profile_picture = StringField()

    # Filename of the preview picture.
    preview_picture = StringField()

    def __str__(self):
        return 'username=%s' % self.username

