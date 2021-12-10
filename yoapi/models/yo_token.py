# -*- coding: utf-8 -*-

"""SendYoLink model"""


from flask import current_app
from flask_mongoengine import Document
from mongoengine import (BooleanField, EmbeddedDocumentField, PULL,
                         StringField)

from .auth_token import AuthToken
from .helpers import DocumentMixin, ReferenceField
from .user import User

from ..helpers import random_string

class YoToken(DocumentMixin, Document):

    """Expiring Authorization to send a Yo"""

    meta = {'collection': 'yo_token',
            'indexes': [
                {'fields': ['auth_token.token']},
                {'fields': ['used'], 'sparse': True},
                {'fields': ['recipient']}],
            'auto_create_index': False}


    # The person who generated the link.
    recipient = ReferenceField(User, required=True, reverse_delete_rule=PULL)

    # The name to be used in the push text.
    header_text = StringField(required=True)

    # Has the link been used. (Convenience for analytics)
    used = BooleanField()

    # Token to validate the usability of the link.
    auth_token = EmbeddedDocumentField(AuthToken, required=True)

    @classmethod
    def generate(cls, recipient=None, text=None):
        token = AuthToken(token=random_string(5))
        return cls(recipient=recipient, header_text=text,
                   auth_token=token)

    @classmethod
    def generate_link(cls, **kwargs):
        instance = cls.generate(**kwargs)
        instance.save()
        server = current_app.config.get('SEND_YO_SERVER')
        return '%s/%s' % (server, instance.auth_token.token)
