# -*- coding: utf-8 -*-

"""ResponseCategory model"""

from flask_mongoengine import Document
from mongoengine import StringField

from .helpers import DocumentMixin


class ResponseCategory(DocumentMixin, Document):

    meta = {'collection': 'response_category',
            'indexes': [
                {'fields': ['content']},
                {'fields': ['yo_type']}],
            'auto_create_index': False}

    # The type of yo this applies to.
    yo_type = StringField(required=True)

    # The content of the yo this should be used for.
    # NOTE: This is mainly used for context_yo with emoji's.
    content = StringField()

    # the text to display on the left response button.
    left_text = StringField(required=True)

    # the text to display on the right response button.
    right_text = StringField(required=True)


    @property
    def category(self):
        return '%s.%s' % (self.left_text, self.right_text)

    @property
    def category_id(self):
        """Returns the category id as a string"""
        return str(self.id) if self.id else None
