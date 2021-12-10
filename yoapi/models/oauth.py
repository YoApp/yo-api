# -*- coding: utf-8 -*-

"""Oauth models"""

from mongoengine import StringField, ListField, DateTimeField
from flask_mongoengine import Document

from .user import User
from .helpers import DocumentMixin, ReferenceField


class Client(DocumentMixin, Document):

    meta = {'collection': 'oauth_client'}

    client_id = StringField()
    client_secret = StringField()
    user_id = StringField()
    default_redirect_uri = StringField()
    callback_url = StringField()
    redirect_uris = ListField(StringField(), default=None)
    default_scopes = ListField(StringField(), default=None)
    client_type = 'public'

    name = StringField()
    description = StringField()


class Grant(DocumentMixin, Document):

    meta = {'collection': 'oauth_grant'}

    client_id = StringField()
    code = StringField()
    user = ReferenceField(User)
    expires = DateTimeField()
    redirect_uri = StringField()
    scopes = ListField(StringField(), default=None)


class Token(DocumentMixin, Document):

    meta = {'collection': 'oauth_token'}

    access_token = StringField()
    refresh_token = StringField()
    client_id = StringField()
    expires = DateTimeField()
    user = ReferenceField(User)
    client = ReferenceField(Client)
    scopes = ListField(StringField(), default=None)
