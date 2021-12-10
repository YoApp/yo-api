# -*- coding: utf-8 -*-

"""Flask-Script subclasses."""

from flask import g, json, _request_ctx_stack, current_app, request
from flask_principal import identity_changed, Identity
from flask_script import (Command as BaseCommand, Manager as BaseManager,
                          Shell)
from werkzeug.datastructures import Headers

from .utils import load_config
from ..accounts import find_user_id, get_user, clear_get_user_cache
from ..core import sns, principals, cache, parse
from ..services import high_rq, low_rq
from .. import accounts, contacts, yos
from .. import models


def login(user_id):
    """Authenticates the current thread with a specific identity"""
    # Prepare the fake request.
    current_app.preprocess_request()
    # Create an identity.
    identity = Identity(user_id)
    # Set this identity on the thread.
    principals.set_identity(identity)
    # Tell listeners that the identity has changed.
    identity_changed.send(current_app, identity=identity)
    print "Now impersonating %s: ObjectId('%s')" % (identity.user.username,
                                                    identity.id)


class Command(BaseCommand):

    def __call__(self, app=None, *args, **kwargs):
        self.client = app.test_client()
        self.config = load_config() or {}
        self.jwt_token = self.config.get('jwt_token')
        super(Command, self).__call__(app=app, *args, **kwargs)

    def jsonpost(self, *args, **kwargs):
        """Convenience method for making JSON POST requests."""
        kwargs.setdefault('content_type', 'application/json')
        if 'data' in kwargs:
            kwargs['data'] = json.dumps(kwargs['data'])

        if 'jwt_token' in kwargs:
            token = kwargs.pop('jwt_token')
            headers = Headers()
            headers.add('Authorization', 'Bearer ' + token)
            kwargs.setdefault('headers', headers)
        return self.client.post(*args, **kwargs)


class YoShell(Shell):

    """A normal script shell with better context"""

    def __init__(self, *args, **kwargs):
        super(YoShell, self).__init__(*args, **kwargs)

    def get_context(self):
        return dict(accounts=accounts,
                    app=_request_ctx_stack.top.app,
                    cache=cache,
                    clear_get_user_cache=clear_get_user_cache,
                    contacts=contacts,
                    get_user=get_user,
                    high_rq=high_rq,
                    low_rq=low_rq,
                    me=g.identity.user,
                    models=models,
                    request=request,
                    sns=sns,
                    yos=yos)


class LoggedInYoShell(YoShell):

    """A pre-authenticated shell with a useful context"""

    def __init__(self, *args, **kwargs):
        super(LoggedInYoShell, self).__init__(*args, **kwargs)

    def run(self, *args, **kwargs):
        if hasattr(_request_ctx_stack.top.app, 'impersonate'):
            username = getattr(_request_ctx_stack.top.app, 'impersonate')
            user_id = find_user_id(username=username)
            login(user_id)
        super(LoggedInYoShell, self).run(*args, **kwargs)


class Manager(BaseManager):

    """Manager subclass that we currently have no use for"""

    def __init__(self, *args, **kwargs):
        super(Manager, self).__init__(*args, **kwargs)

    def run(self):
        super(Manager, self).run()
