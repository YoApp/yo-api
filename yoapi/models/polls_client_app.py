# -*- coding: utf-8 -*-

from flask_mongoengine import Document
from mongoengine import StringField
from .helpers import DocumentMixin, ReferenceField
from yoapi.models import User


class PollsClientApp(DocumentMixin, Document):

    meta = {'collection': 'polls_client_app'}

    owner = ReferenceField(User)

    name = StringField()

    description = StringField()

    app_token = StringField()

    def get_public_dict(self):
        return {
            'id': str(self.id),
            'name': self.name,
            'description': self.description,
            'app_token': self.app_token
        }