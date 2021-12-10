from flask.ext.mongoengine import Document
from mongoengine import FloatField, IntField, StringField
from yoapi.models.helpers import DocumentMixin


class Region(DocumentMixin, Document):

    meta = {'collection': 'region'}

    name = StringField()

    latitude = FloatField()

    longitude = FloatField()

    radius = IntField()