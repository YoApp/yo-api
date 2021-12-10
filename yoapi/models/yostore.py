# -*- coding: utf-8 -*-

"""Yoindex model"""

from flask_mongoengine import Document
from mongoengine import BooleanField, StringField, LongField, ListField, IntField
from .helpers import URLField, DocumentMixin



class YoStore(DocumentMixin, Document):

    meta = {'collection': 'yoindex',
            'indexes': [
                {'fields': ['rank']},
                {'fields': ['category']},
                {'fields': ['region']}],
            'auto_create_index': False}

    # name displayed in yostore/yoindex
    name = StringField(required=True)

    # username of associated account
    username = StringField()

    # description to be displayed to users
    description = StringField()

    # URL for service
    url = URLField()

    # category in which the service appears.
    # Set up to support multiple categories in future
    category = ListField(StringField(), default=None)

    # When the item was added
    added_at = LongField()

    # denotes if service/brand is official
    is_official = BooleanField()

    # location required
    needs_location = BooleanField()

    # index in spreadsheet
    rank = LongField()

    # if service is region specific which region, if not default to world
    region = StringField()

    # denotes if service is in carousel
    in_carousel = BooleanField()

    # url to carousel picture
    carousel_picture = StringField()

    # url to profile picture to account
    profile_picture = StringField()

    # array of screenshots
    featured_screenshots = ListField(StringField(), default=None)

    def __str__(self):
        return 'name=%s' % self.name
