# -*- coding: utf-8 -*-

"""FAQ model"""

from flask_mongoengine import Document
from mongoengine import StringField, LongField

from .helpers import DocumentMixin



class FAQ(DocumentMixin, Document):

    meta = {'collection': 'faq',
            'indexes': [
                {'fields': ['question']},
                {'fields': ['rank']}],
            'auto_create_index': False}

    # FAQ question.
    question = StringField(required=True)

    # FAQ answer.
    answer = StringField(required=True)

    # index in spreadsheet
    rank = LongField()

    app_id = StringField()

    def __str__(self):
        return 'faq=%s' % self.question
