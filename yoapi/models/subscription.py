# -*- coding: utf-8 -*-

"""Subscription model"""


from flask_mongoengine import Document
from mongoengine import StringField

from .helpers import DocumentMixin, ReferenceField, URLField
from yoapi.models import User


class Subscription(DocumentMixin, Document):

    meta = {'collection': 'subscription',
            'indexes': ['target'],
            'auto_create_index': False}

    owner = ReferenceField(User)

    target = ReferenceField(User)

    webhook_url = URLField(required=True)

    # User provided token that will be sent as 'token' to verify it came from us
    token = StringField()

    event_type = StringField()

    def get_public_dict(self):
        return {
            'id': str(self.id),
            'target_id': self.target.user_id,
            'webhook_url': self.webhook_url,
            'token': self.token
        }
