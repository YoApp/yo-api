# -*- coding: utf-8 -*-

"""Helpers module for data models"""
from datetime import datetime

import phonenumbers
import sys

from bson import DBRef
from flask import current_app
from mongoengine import (StringField, LongField, DoesNotExist,
                         MultipleObjectsReturned,
                         ReferenceField as BaseReferenceField, DateTimeField)
from wtforms import ValidationError
from werkzeug import import_string

from mongoengine.base import get_document
from phonenumbers.phonenumberutil import NumberParseException

from ..errors import APIError
from ..helpers import get_usec_timestamp
from ..urltools import UrlHelper


# pylint: disable=too-few-public-methods


class DocumentMixin(object):

    created_date = DateTimeField()

    # The time of creation.
    created = LongField(required=True)

    # The time of the last update.
    updated = LongField()

    def to_dict(self):
        """Returns a dictionary representation of the document"""
        return self.to_mongo().to_dict()

    def clean(self):
        # Default values on fields prevent us from detecting when they are
        # null after loading from the db. So we update created records on
        # documents when saving.
        if not self.created:
            self.created = get_usec_timestamp()

        # Only set the updated field when saving an existing document.
        if self.id:
            self.updated = get_usec_timestamp()


class URLField(StringField):

    def __init__(self, *args, **kwargs):
        super(URLField, self).__init__(*args, **kwargs)

    def validate(self, value):
        """Validates the URL with the help of the `UrlHelper`

        If no value is passed then we leave it up to the base class to
        determine if a value is required.
        """
        try:
            UrlHelper(value)
        except ValueError as err:
            self.error('URL validation error: %s' % err.message)


class PhoneField(StringField):

    def __init__(self, *args, **kwargs):
        super(PhoneField, self).__init__(*args, **kwargs)

    def validate(self, value):
        """Validates a phone number using `phonenumbers`

        Read more at: https://github.com/daviddrysdale/python-phonenumbers
        """
        try:
            phonenumbers.parse(value)
        except NumberParseException as err:
            self.error(err.message)


class URLFieldValidator(object):
    """Implements a wtforms URLField validation class"""

    def __init__(self):
        pass

    def __call__(self, form, field):
        try:
            UrlHelper(field.data)
        except ValueError as err:
            raise ValidationError(err.message)


_deps = {}

class ReferenceField(BaseReferenceField):
    """Override the ReferenceField to make dereferencing of
    User's and Yo's use redis"""

    @staticmethod
    def __load_dependencies():
        _deps['_user_class'] = get_document('User')
        _deps['_yo_class'] = get_document('Yo')
        _deps['_header_class'] = get_document('Header')
        _deps['_banner_class'] = get_document('Banner')
        _deps['_get_user'] = import_string('yoapi.accounts._get_user')
        _deps['_get_yo_by_id'] = import_string('yoapi.yos.queries.get_yo_by_id')
        _deps['_get_header_by_id'] = import_string('yoapi.headers.get_header_by_id')
        _deps['_get_banner_by_id'] = import_string('yoapi.banners.get_banner_by_id')

    @staticmethod
    def dereference_from_cache(document_type, dbref):
        """Function to dereference an item from cache.
        NOTE: This is only seperated from the ReferenceField.__get__
        method so that it can be mocked in tests"""
        value = None
        if document_type == _deps.get('_user_class'):
            value = _deps.get('_get_user')(user_id=str(dbref.id))
        elif document_type == _deps.get('_yo_class'):
            value = _deps.get('_get_yo_by_id')(str(dbref.id))
        elif document_type == _deps.get('_header_class'):
            value = _deps.get('_get_header_by_id')(str(dbref.id))
        elif document_type == _deps.get('_banner_class'):
            value = _deps.get('_get_banner_by_id')(str(dbref.id))

        return value

    def __get__(self, instance, owner):
        if instance is None:
            # Document class being used rather than a document object.
            return self

        # Get value from document instance if available.
        value = instance._data.get(self.name)
        self._auto_dereference = instance._fields[self.name]._auto_dereference
        # Dereference DBRefs.
        if self._auto_dereference and isinstance(value, DBRef):
            # Lazy load the dependencies.
            if not _deps:
                self.__load_dependencies()

            try:
                value = self.dereference_from_cache(self.document_type, value)
                if value is not None:
                    instance._data[self.name] = value
            except (APIError, DoesNotExist, MultipleObjectsReturned):
                pass
            except:
                # If this is not a known error. lets log it just in case.
                current_app.log_exception(sys.exc_info())

        return super(ReferenceField, self).__get__(instance, owner)
