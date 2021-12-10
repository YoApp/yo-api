# -*- coding: utf-8 -*-

"""Status model"""


from flask_mongoengine import Document
from mongoengine import StringField
from .helpers import DocumentMixin, ReferenceField
from yoapi.models import User


class Status(DocumentMixin, Document):

    meta = {'collection': 'status',
            'indexes': ['user'],
            'auto_create_index': False}

    user = ReferenceField(User)

    status = StringField(required=True)

    def get_public_dict(self):
        return {
            'status': self.status,
            'created': self.created
        }
