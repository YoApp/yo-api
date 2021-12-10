# -*- coding: utf-8 -*-

"""FAQ model"""

import time

from datetime import datetime
from flask_mongoengine import Document
from mongoengine import StringField, BooleanField

from .helpers import DocumentMixin



class GifPhrase(DocumentMixin, Document):

    meta = {'collection': 'gif_phrase',
            'indexes': [
                {'fields': ['day']},
                {'fields': ['date']},
                {'fields': ['is_default']}],
            'auto_create_index': False}

    # The keyword(s) to search giphy for gifs.
    keyword = StringField(required=True)

    # The header to display in the client when sending this.
    header = StringField(required=True)

    # The time that this starts in 24hour HH:MM format.
    start_time = StringField(required=True)

    # The time that this ends in 24hour HH:MM format.
    end_time = StringField(required=True)

    # The day of the week.
    day = StringField()

    # The specific date this applies to mm/dd/yy format..
    date = StringField()

    # Is this considered a default?
    is_default = BooleanField()

    @property
    def phrase_id(self):
        return str(self.id) if self.id else None
