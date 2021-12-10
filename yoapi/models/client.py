# -*- coding: utf-8 -*-

"""Client model"""


from flask_mongoengine import Document
from md5 import md5
from mongoengine import StringField

from .helpers import DocumentMixin
from ..helpers import get_remote_addr


class Client(DocumentMixin, Document):

    """A client identification model.

    This model is not directly intended for storing in the database, but
    serves a primary purpose as an in memory representation of an
    unauthenticated users.

    To uniquely represent any connected client we borrow `create_identifer`
    from Flask-Login: https://github.com/maxcountryman/flask-login

    Args:
        req: A Flask request.
    """

    # In production, this meta dictionary should contain set the key
    # `auto_create_index` to False to prevent any on-the-fly modifications to
    # the index.
    meta = {'collection': 'anonymous_user'}

    client_id = StringField(required=True)

    def __str__(self):
        return self.client_id

    @classmethod
    def from_request(cls, req):
        """Creates a unique fingerprint of a connected client"""

        # Compute fingerprint
        user_agent = req.headers.get('User-Agent')
        if user_agent is not None:
            user_agent = user_agent.encode('utf-8')
        base = '{0}|{1}'.format(get_remote_addr(req), user_agent)
        if str is bytes:
            base = unicode(base, 'utf-8', errors='replace')  # pragma: no cover
        h = md5()
        h.update(base.encode('utf8'))
        client = cls()
        client.client_id = h.hexdigest()
        return client
