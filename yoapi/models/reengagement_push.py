# -*- coding: utf-8 -*-

from flask_mongoengine import Document
from .helpers import DocumentMixin, URLField, ReferenceField
from mongoengine import ListField, IntField, DateTimeField, StringField


class ReengagementPush(DocumentMixin, Document):

    meta = {'collection': 'reengagement_push'}

    name = StringField()

    date = DateTimeField()

    headers = ListField(ReferenceField('Header'))

    link = URLField()

    # auto-generated values

    bitly_links = ListField(URLField())  # bitly links for each header

    open_count = IntField()  # how many users opened the push

    elapsed = IntField()  # time it took to send this





