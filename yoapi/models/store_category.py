# -*- coding: utf-8 -*-

"""StoreCategory model"""

from flask_mongoengine import Document
from mongoengine import StringField, LongField

from .helpers import DocumentMixin



class StoreCategory(DocumentMixin, Document):

    meta = {'collection': 'store_category',
            'indexes': [
                {'fields': ['category']},
                {'fields': ['rank']},
                {'fields': ['region']}],
            'auto_create_index': False}

    # category for the yo store.
    category = StringField(required=True)

    # index in spreadsheet
    rank = LongField()

    # if category is region specific which region, if not default to world
    region = StringField()

    def __str__(self):
        return 'category=%s' % self.category
