# -*- coding: utf-8 -*-
from bson import DBRef

from flask_mongoengine import Document
from mongoengine import StringField, BooleanField, DictField, ListField, URLField
from .helpers import DocumentMixin, ReferenceField
from yoapi.models import User


class PushApp(DocumentMixin, Document):

    meta = {'collection': 'push_app'}

    app_name = StringField()

    username = StringField()

    category = StringField()

    short_description = StringField()

    description = StringField()

    hex_color = StringField()

    config = ListField()

    icon_url = StringField()

    is_featured = BooleanField()

    app_sound = StringField()

    slug = StringField()

    demo_url = URLField()


class EnabledPushApp(DocumentMixin, Document):

    meta = {'collection': 'enabled_push_app'}

    user = ReferenceField(User)

    app = ReferenceField(PushApp, unique_with=['user'])

    config = DictField()

    is_active = BooleanField()

    def has_dbrefs(self):
        if isinstance(self.app, DBRef):
            return True

        return False
