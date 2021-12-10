# -*- coding: utf-8 -*-

"""Auth token model"""


from datetime import timedelta
from functools import partial
from mongoengine import EmbeddedDocument, LongField, StringField

from ..helpers import get_usec_timestamp


class AuthToken(EmbeddedDocument):

    """Expiring auth token"""

    # Name of role.
    token = StringField(required=True)

    # Automatically store the tiemstamp of when this role was created.
    created = LongField()

    # Token expires by default one day after it was created.
    expires = LongField(default=partial(get_usec_timestamp,
                                        delta=timedelta(days=1)))

    # Timestamp of when authentication code was used.
    used = LongField()

    def __str__(self):
        return "<AuthToken '%s'>" % (self.created)
