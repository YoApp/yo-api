from mongoengine import Document, StringField, ListField
from yoapi.models import User
from yoapi.models.helpers import DocumentMixin, ReferenceField


class Stats(DocumentMixin, Document):

    meta = {'collection': 'stats'}

    user = ReferenceField(User)

    installed_apps = ListField(StringField())
