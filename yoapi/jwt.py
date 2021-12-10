# -*- coding: utf-8 -*-

"""Subclassing JWT to enable multiple secret keys"""

import itsdangerous

from collections import namedtuple
from datetime import timedelta
from flask import current_app, request
from itsdangerous import (
    BadSignature,
    SignatureExpired,
    JSONWebSignatureSerializer
)

from .accounts import find_user_id
from .helpers import get_usec_timestamp


class JWTError(Exception):
    def __init__(self, error, description):
        self.error = error
        self.description = description


class TokenType(object):
    LEGACY = 'JWT'
    SECURE = 'JWT2'

# Local cache for serializers.
_serializers = {}


def decode(token):
    """Return the decoded token

    We are weaning off the old "secret" secret, so we try both for decoding
    and only the new token for encoding.
    """
    secret = current_app.config['JWT_SECRET_KEY']
    old_secret = current_app.config['JWT_OLD_SECRET_KEY']

    def _loads(secret, token):
        return get_serializer(secret).loads(token)

    try:
        return TokenType.SECURE, _loads(secret, token)
    except BadSignature:
        return TokenType.LEGACY, _loads(old_secret, token)


def encode(payload):
    """Return the encoded payload."""
    secret = current_app.config['JWT_SECRET_KEY']
    return get_serializer(secret).dumps(payload).decode('utf-8')


def generate_token(user):
    """Generate a token for a user"""
    payload = make_payload(user)
    prefix = current_app.config['JWT_AUTH_HEADER_PREFIX']
    return encode(payload)


def get_decoded_token(auth=None):
    """Verifies the JWT data in the current request"""

    auth = auth or request.headers.get('Authorization', None)
    if auth is None:
        raise JWTError('Authorization header is missing')


    # There was a bug in production on 07052015 where Bearer was included in
    # the JWT token response for ~10 minutes. There are old clients in the wild
    # who are affected by this problem and that don't sign out on a 401
    # response. matt@justyo.co
    auth = auth.replace('Bearer Bearer', 'Bearer')

    auth_header_prefix = current_app.config['JWT_AUTH_HEADER_PREFIX']
    parts = auth.split()

    if parts[0].lower() != auth_header_prefix.lower():
        raise JWTError('Invalid JWT header', 'Unsupported authorization type')
    elif len(parts) == 1:
        raise JWTError('Invalid JWT header', 'Token missing')
    elif len(parts) > 2:
        raise JWTError('Invalid JWT header', 'Token contains spaces')

    try:
        token_type, payload = decode(parts[1])
    except BadSignature:
        raise JWTError('Invalid JWT', 'Token is undecipherable')

    JWTUser = namedtuple('JWTUser', ['user_id', 'token_type'])
    if 'id' in payload:
        return JWTUser(payload.get('id'), token_type)
    elif 'userID' in payload:
        user_id = find_user_id(parse_id=payload.get('userID'))
        return JWTUser(user_id, token_type)
    else:
        raise JWTError('Unrecognized JWT')


def get_serializer(secret):
    """Gets a JWT serializer for a specific secret"""
    if not secret:
        raise JWTError('JWT secret required but not provided')

    if secret not in _serializers:
        algorithm = current_app.config['JWT_ALGORITHM']
        _serializers[secret] = JSONWebSignatureSerializer(secret_key=secret,
                algorithm_name=algorithm)

    return _serializers[secret]


def make_payload(user):
    """Creates the payload for a JWT token upon calling generate_token"""
    return {'id': user.user_id,  # ObjectId from mongodb.
            'userID': user.parse_id,
            'username': user.username,
            'created': get_usec_timestamp()}

