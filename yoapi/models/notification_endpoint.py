# -*- coding: utf-8 -*-

"""NotificationEndpoint model"""

import sys

import semver
from bson import DBRef
from flask import current_app
from flask_mongoengine import Document
from mongoengine import BooleanField, StringField
from .helpers import DocumentMixin, ReferenceField
from .user import User


IOS = 'ios'
IOSBETA = 'ios-beta'
IOSDEV = 'ios-development'
ANDROID = 'android'
WINPHONE = 'winphone'
FLASHPOLLSBETADEV = 'com.flashpolls.beta.dev'
FLASHPOLLSBETAPROD = 'com.flashpolls.beta.prod'
FLASHPOLLSDEV = 'com.flashpolls.flashpolls.dev'
FLASHPOLLSPROD = 'com.flashpolls.flashpolls.prod'

# Android legacy is defined as the version of android that can
# support custom push text. In the past, the only format Android
# supported was '(@|* )?From username'. Starting with this version
# the push text could be anything
ANDROID_LEGACY = '111064076'

# Android os legacy is defined as version of the
# android os that can support emoji's
ANDROID_OS_LEGACY = '4.1'

# iOS legacy is defined as the semver comparison version of ios that can
# support ANY push text. Prior to this version, iOS would ony work properly
# if the text ENDED in 'From username' and none of the text prior contained
# the work' from'.
IOS_LEGACY = '>1.5.4'

# iOS CATEGORIES is defined as the semver comparison version of ios that
# supports the category field in the payload having values other than
# 'Response_category'
IOS_CATEGORIES = '>=1.5.6'


# iOS real names is defined as the semver comparison version of ios that
# started using real names for the contacts instead of usernames.
IOS_REAL_NAMES = '>=1.6.7'


# iOS invisible push is defined as the semver comparison version of ios that
# supports payloads without alert text and sound.
IOS_INVISIBLE_PUSH = '>=2.0.0'


# iOS emoji category is defined as the semver comparison version of ios that
# supports payloads with actions.
IOS_EMOJI_CATEGORY = '>=2.0.3'


# iOS clients that support adding response categories via a silent push.
IOS_ADD_RESPONSE = '>=2.0.6'


class NotificationEndpoint(DocumentMixin, Document):

    """Endpoints associated with a user.

    This term is borrowed from AWS Simple Notification Service (SNS) and
    describes an entity capable of receiving push notifications. This
    can mean anything from a physical device, to a webhook url, but
    we'll primarily use this for the physical devices.

    This class is largely similar to Device, but we're changing the name
    to better reflect the real semantics. In addition, it does not seem
    like a good idea to use the token as the primary key of the collection.
    """

    meta = {'collection': 'notification_endpoint',
            'indexes': [
                {'fields': ['owner']},
                {'fields': ['arn']},
                {'fields': ['installation_id'], 'sparse': True}],
            'auto_create_index': False}

    # Boolean indicator for devices reported as disabled by the notification
    # manager (e.g. Amazon SNS)
    disabled = BooleanField()

    # ARN for this device. This can be used to target push notifications
    # to a specific device so each user doesn't need their own topic.
    arn = StringField(required=True)

    # Endpoint platform, e.g. android, ios or winphone.
    platform = StringField(required=True)

    # Owner who subscribes to target.
    owner = ReferenceField(User)

    # A unique push identifier for the given platform. For android, this is
    # a registration id, for iOS a push token and for Windows Phones this
    # is a device URI.
    token = StringField(required=True)

    # installation_id is an identifier to tie this endpoint arn
    # to a particular installation
    installation_id = StringField()

    # Version of the client installed on device
    version = StringField()

    # Version of the endpoint operating system
    os_version = StringField()

    # Version of the endpoint sdk (currently android only)
    sdk_version = StringField()

    @staticmethod
    def perfect_payload_support_dict():
        return {
            'handles_any_text': True,
            'handles_emoji_categories': True,
            'handles_invisible_push': True,
            'handles_display_names': True,
            'handles_long_text': True,
            'handles_response_category': True,
            'is_legacy': False,
            'platform': IOS
        }

    def get_payload_support_dict(self):
        handles_long_text = True
        # Android does not support the swipe/tap text or
        # extra long push text in general.
        if self.platform == ANDROID:
            handles_long_text = False

        return {
            'handles_any_text': self.handles_any_text,
            'handles_emoji_categories': self.handles_emoji_categories,
            'handles_invisible_push': self.handles_invisible_push,
            'handles_display_names': self.handles_display_names,
            'handles_long_text': handles_long_text,
            'handles_response_category': self.handles_response_category,
            'is_legacy': self.is_legacy,
            'platform': self.platform
        }

    @property
    def handles_emoji_categories(self):
        if self.platform and 'polls' in self.platform:
            return True
        if self.platform and 'status' in self.platform:
            return True
        if not self.handles_response_category:
            return False

        try:
            if self.platform == ANDROID and self.version >= '111064084':
                return True
            return semver.match(self.version, IOS_EMOJI_CATEGORY)
        except ValueError:
            current_app.log_exception(sys.exc_info())

        return False

    @property
    def handles_response_category(self):
        if self.platform and 'polls' in self.platform:
            return True
        if self.platform and 'status' in self.platform:
            return True
        if self.platform == ANDROID and self.version >= '111064084':
            return True
        if self.platform not in [IOS, IOSBETA, IOSDEV]:
            return False
        if not self.handles_any_text:
            return False

        # If the version is not a valid semver string log it and
        # mark it legacy.
        try:
            return semver.match(self.version, IOS_CATEGORIES)
        except ValueError:
            current_app.log_exception(sys.exc_info())

        return False

    @property
    def handles_any_text(self):
        if self.platform and 'polls' in self.platform:
            return True
        if self.platform and 'status' in self.platform:
            return True
        if self.is_legacy:
            return False

        if (self.platform == IOS or
            self.platform == IOSBETA or
            self.platform == IOSDEV):
            if not self.version:
                return False
            # If the version is not a valid semver string log it and
            # mark it legacy.
            try:
                return semver.match(self.version, IOS_LEGACY)
            except ValueError:
                current_app.log_exception(sys.exc_info())
        # if android is not legacy, it can handle any text
        if self.platform == ANDROID:
            return True

        return False

    @property
    def handles_display_names(self):
        if self.platform and 'polls' in self.platform:
            return True
        if self.platform and 'status' in self.platform:
            return True
        if self.platform and 'no' in self.platform:
            return True
        if self.is_legacy:
            return False
        if self.platform not in [IOS, IOSBETA, IOSDEV]:
            return False
        if not self.version:
            return False

        # If the version is not a valid semver string log it and
        # mark it legacy.
        try:
            return semver.match(self.version, IOS_REAL_NAMES)
        except ValueError:
            current_app.log_exception(sys.exc_info())

        return False

    @property
    def handles_invisible_push(self):
        if self.platform and 'polls' in self.platform:
            return True
        if self.platform and 'status' in self.platform:
            return True
        if self.is_legacy:
            return False
        if self.platform not in [IOS, IOSBETA, IOSDEV]:
            return False
        if not self.version:
            return False

        # If the version is not a valid semver string log it and
        # mark it legacy.
        try:
            return semver.match(self.version, IOS_INVISIBLE_PUSH)
        except ValueError:
            current_app.log_exception(sys.exc_info())

        return False

    @property
    def is_legacy(self):
        if not self.platform:
            return True
        if self.platform == IOSBETA:
            return False
        if self.platform == IOS:
            return False
        if self.platform == IOSDEV:
            return False
        if self.platform == WINPHONE:
            return True
        if 'polls' in self.platform:
            return False
        if 'status' in self.platform:
            return False
        if self.platform == ANDROID:
            if not self.version:
                return True
            if self.version < ANDROID_LEGACY:
                return True
            if not self.os_version:
                return True
            return self.os_version < ANDROID_OS_LEGACY

        return True

    @property
    def handles_add_response_push(self):
        if self.platform and 'polls' in self.platform:
            return True
        return self.platform in [IOS, IOSBETA, IOSDEV] and \
            semver.match(self.version, IOS_ADD_RESPONSE)

    def get_subscription_by_arn(self, arn):
        subscriptions = [subscription for subscription in self.subscriptions
                         if subscription.arn == arn]
        return subscriptions[0] if subscriptions else None

    def get_dict(self):
        return {'token': self.token,
                'platform': self.platform,
                'owner': self.owner.user_id if self.owner else None}

    def has_dbrefs(self):
        """Checks if there are any users that could not be
        dereferenced."""
        if isinstance(self.owner, DBRef):
            return True

        return False

    def __str__(self):
        return str(self.get_dict())
