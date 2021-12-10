# -*- coding: utf-8 -*-

"""The core security module for the Yo API.

To implement the Flask-JWT extension we need to supply at least two
two functions; one for creating a user from payload data, and another
to make payload data given a user instance.

The current release of Flask-JWT is 0.2.0, but this API requires
the latest code from the master branch. This can be installed using:

    pip install git+https://github.com/mattupstate/flask-jwt.git

To create a token, simply call flask_jwt.generate_token from anywhere in the
code, passing a user instance as the only argument.

Authentication and authorization is handled by the flask_jwt.require_jwt
function. This is implemented in the route decorators in the subclassed
Flask and Blueprint classes in yoflask.py.
"""

import sys

from flask import request, current_app, g, session
from flask_principal import Identity, identity_changed, identity_loaded
from .errors import APIError
from .models import Client
from mongoengine import DoesNotExist
from .permissions import (LoginNeed, ViewProfileNeed, AccountNeed,
                          admin_need, pseudo_need)
from .accounts import get_user, find_user_ids, user_id_exists
from .core import principals
from . import jwt
from .jwt import JWTError
from yoapi.helpers import make_json_response
from yoapi.models.oauth import Token


def is_admin():
    """Returns true if current user is an admin"""
    if g.identity.user and g.identity.user.is_admin:
        return True
    else:
        return False


def clear_identity():
    client = Client.from_request(request)
    identity = AnonymousYoIdentity(client=client)
    principals.set_identity(identity)
    identity_changed.send(current_app, identity=identity)


def load_identity(user_id):
    client = Client.from_request(request)
    identity = YoIdentity(user_id, auth_type='WEB',
                          client=client)
    principals.set_identity(identity)
    identity_changed.send(current_app, identity=identity)


@principals.identity_loader
def identity_loader():
    """Loads identity if JWT provided.

    This function is executed before requests. If a JWT can be verified then
    it updates the current identity. It can be accessed at through the global
    object at g.identity (thread local).

    If no authorization header is set we check if an identity has been set
    on the session.
    """
    client = Client.from_request(request)

    auth_header_value = request.headers.get('Authorization', None)

    # First check for JWT token.
    # This should only be used with workers.
    if request.environ.get('REMOTE_USER', None):
        return YoIdentity(request.environ['REMOTE_USER'], auth_type='RELAY',
                          client=client)

    elif auth_header_value:

        splitted = auth_header_value.split(' ')
        if len(splitted) < 2:
            raise APIError('Invalid access token.', status_code=401)

        token_value = splitted[1]

        if len(token_value) == 30:
            try:
                token = Token.objects.get(access_token__iexact=token_value)
            except DoesNotExist as e:
                raise APIError('Invalid access token.', status_code=401)
            user = token.user
            return YoIdentity(str(user.id), auth_type='OAUTH', client=client)
        try:
            jwt_token = jwt.get_decoded_token()
            # If successful we can access the parsed User object.
            if user_id_exists(jwt_token.user_id):
                return YoIdentity(jwt_token.user_id,
                                  auth_type=jwt_token.token_type,
                                  client=client)
        except JWTError:
            # There was a bug in production on 07 May 2015 where null was sent in
            # the JWT token response for ~10 minutes. There are old clients in
            # the wild who are affected by this problem and that don't sign
            # out on a 401 response. matt@justyo.co
            if request.headers.get('Authorization') != 'Bearer null':
                raise APIError('Invalid API token.', status_code=401)

    # Then check for an API token in either the GET/POST data.
    if 'api_token' in request.values or 'api_token' in request.json:
        api_token = request.values.get('api_token')
        api_token = api_token or request.json.get('api_token')

        user_ids = find_user_ids(api_token=api_token) if api_token else None
        if user_ids and len(user_ids) == 1:
            return YoIdentity(user_ids[0], auth_type='API', client=client)

        raise APIError('Invalid API token.', status_code=401)

    if 'access_token' in request.json:
        try:
            access_token = request.json.get('access_token')
            token = Token.objects.get(access_token=access_token)
            user = token.user
            return YoIdentity(str(user.id), auth_type='OAUTH', client=client)

        except DoesNotExist as e:

            raise APIError('Invalid access token.', status_code=401)

        except Exception as e:

            user_ids = find_user_ids(api_token=access_token)
            if user_ids and len(user_ids) == 1:
                return YoIdentity(user_ids[0], auth_type='API', client=client)

            current_app.log_exception(sys.exc_info())
            raise APIError('Invalid access token.', status_code=401)

    # Last check for secure cookie from web users.
    if 'identity.id' in session and 'identity.auth_type' in session:
        if user_id_exists(session['identity.id']):
            return YoIdentity(session['identity.id'], auth_type='WEB',
                              client=client)
        else:
            forget_auth_cookie()

    return AnonymousYoIdentity(client=client)


def set_auth_cookie(user):
    """Saves the current identity to an active session

    Most of the requests served by this API rely on JWT's for which there is
    no concept of saving a session. Therefore, we make sure to only save
    sessions where auth_type == 'cookie'.

    Note: This identity save was originally copied in umodified form from
    the flask-principals extension.
    """
    session['identity.id'] = user.user_id
    session['identity.auth_type'] = 'WEB'
    session.modified = True


def forget_auth_cookie():
    """Forgets an authenticated user"""
    session.clear()
    session.modified = True


@identity_loaded.connect
@identity_changed.connect
def handle_identity_changed(sender, identity):
    """Signal handler for a loaded/changed identity.

    This is where we load user data and provide its needs.
    """
    if isinstance(identity, AnonymousYoIdentity):
        identity.provides.add(LoginNeed(False))
        identity.user = None
    else:
        identity.provides.add(LoginNeed(True))
        identity.provides.add(AccountNeed(identity.id))
        identity.provides.add(ViewProfileNeed(identity.id))
        # User can only be fetched after needs are provided.
        try:
            user = get_user(user_id=identity.id)
            identity.user = user

            # If user is an admin then provide that role need.
            if user.is_admin:
                identity.provides.add(admin_need)
                if identity.auth_type == 'JWT':
                    current_app.log_warning('admin login with insecure token')
            # If user is a pseudo user then provide that role need.
            if user.is_pseudo:
                identity.provides.add(pseudo_need)
        except APIError as err:
            # Since we are checking that the user exists in identity loader
            # this should never happen, but if it does send us an email.
            forget_auth_cookie()
            clear_identity()
            current_app.log_exception(sys.exc_info())


class YoIdentity(Identity):

    """Adds functionality to standard Flask-Principal Identity"""

    def __init__(self, user_id, auth_type=None, client=None):
        self.client = client
        super(YoIdentity, self).__init__(user_id, auth_type=auth_type)


class AnonymousYoIdentity(YoIdentity):

    """Adds functionality to standard Flask-Principal Identity"""

    def __init__(self, client=None):
        super(AnonymousYoIdentity, self).__init__(None, client=client)
