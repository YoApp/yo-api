# -*- coding: utf-8 -*-

"""Banner model"""


from flask_mongoengine import Document
from mongoengine import StringField, BooleanField, IntField

from .helpers import DocumentMixin, ReferenceField

from ..constants.context import VALID_CONTEXT_IDS


class Banner(DocumentMixin, Document):

    """MongoDB Banner model."""

    meta = {'collection': 'banner',
            'indexes': [
                {'fields': ['recipient'], 'sparse': True},
                {'fields': ['parent'], 'sparse': True},
                {'fields': ['status'], 'sparse': True},
                {'fields': ['context']}],
            'auto_create_index': False}

    # Is this banner enabled?
    enabled = BooleanField()

    # What context does this banner go to?
    context = StringField(choices=VALID_CONTEXT_IDS)

    # What content does this banner go to? (used for giphy phrases)
    content = StringField()

    # The text to be displayed when showing the banner.
    message = StringField()

    link = StringField()

    is_test = BooleanField()

    # The parent banner that this refers to.
    parent = ReferenceField('self')

    # The user that recieved this banner.
    recipient = ReferenceField('User')

    # The read status of the banner.
    status = StringField()

    # How many times the app needs to have been opened for
    # this to be displayed.
    open_count = IntField()

    # The priority of this banner over others.
    priority = IntField()


    @property
    def banner_id(self):
        return str(self.id) if self.id else None
