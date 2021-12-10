from mongoengine import Document, StringField, EmbeddedDocumentField, EmbeddedDocument, URLField
from yoapi.models import User
from yoapi.models.helpers import DocumentMixin, ReferenceField


class ExternalData(EmbeddedDocument):

    access_token = StringField(required=True)


class IntegrationType(DocumentMixin, Document):

    meta = {'collection': 'integration_type'}

    name = StringField(required=True)

    description = StringField(required=True)

    logo_url = URLField(required=True)

    authorization_url = URLField(required=True)

    token_url = URLField(required=True)

    client_id = StringField(required=True)

    client_secret = StringField(required=True)

    redirect_uri = StringField(required=True)

    scope = StringField(required=True)


class Integration(DocumentMixin, Document):

    meta = {'collection': 'integration'}

    type = ReferenceField(IntegrationType)

    user = ReferenceField(User)

    access_token = StringField()

    refresh_token = StringField()


class SpreadsheetFile(Document):

    meta = {'collection': 'spreadsheet'}

    yo_id = StringField(required=True)

    user_id = StringField(required=True)

    text = StringField(required=True)

    file_id = StringField(required=True)


