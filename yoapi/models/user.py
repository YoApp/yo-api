# -*- coding: utf-8 -*-

"""User model"""


import phonenumbers
import re

from bson import DBRef
from flask import current_app
from flask_mongoengine import Document
from mongoengine import (BooleanField, StringField, IntField, PULL,
                         EmbeddedDocumentField, LongField, ListField, FloatField)
from passlib.hash import bcrypt
from phonenumbers.phonenumberutil import NumberParseException

from .auth_token import AuthToken

from .helpers import PhoneField, URLField, DocumentMixin, ReferenceField
from ..errors import APIError
from ..helpers import get_image_url
from ..permissions import AccountPermission, admin_permission
from ..constants.regex import USERNAME_REGEX

# pylint: disable=too-many-public-methods

PUBLIC_FIELDS = [('bio', 'description'),
                 ('is_api_user', 'is_service'),
                 ('is_pseudo', 'is_pseudo'),
                 ('is_subscribable', 'is_subscribable'),
                 ('is_vip', 'is_official'),
                 ('name', 'full_name'),
                 ('first_name', 'first_name'),
                 ('last_name', 'last_name'),
                 ('display_name', 'display_name'),
                 ('app_name', 'app_name'),
                 ('needs_location', 'request_location'),
                 ('last_seen_time', 'last_seen_time'),
                 ('photo', 'photo'),
                 ('type', 'user_type'),
                 ('user_id', 'user_id'),
                 ('username', 'username'),
                 ('status', 'status'),
                 ('status_last_updated', 'status_last_updated'),
                 ('last_yo', 'last_yo'),
                 ('yo_count', 'yo_count')]

ACCOUNT_FIELDS = [('api_token', 'api_token'),
                  ('coins', 'coins'),
                  ('bitly', 'bitly'),
                  ('callback', 'callback'),
                  ('email', 'email'),
                  ('stripe_id', 'stripe_id'),
                  ('phone', 'phone'),
                  ('welcome_link', 'welcome_link'),
                  ('is_verified', 'verified'),
                  ('is_guest', 'is_guest'),
                  ('is_beta_tester', 'is_beta_tester'),
                  ('country_code', 'country_code')]

ACCOUNT_FIELDS += PUBLIC_FIELDS

ADMIN_FIELDS = [('created', 'created'),
                ('is_yo_team', 'is_yo_team'),
                ('last_seen_time', 'last_seen_time'),
                ('parse_id', 'parse_id'),
                ('updated', 'updated'),
                ('last_yo_time', 'last_yo_time'),
                ('last_sent_time', 'last_sent_time')]
ADMIN_FIELDS += ACCOUNT_FIELDS

FIELD_LIST_MAP = {'account': ACCOUNT_FIELDS,
                  'public': PUBLIC_FIELDS,
                  'admin': ADMIN_FIELDS}


class User(DocumentMixin, Document):

    """MongoDB user model.

    All types of users share this model, for instance regular users and
    api users.

    This model is used by the security features of yoapi for handling
    a JWT authentication model. See security.py.
    """

    meta = {'collection': 'user',
            'indexes': [
                {'fields': ['api_token'], 'unique': True, 'sparse': True},
                {'fields': ['temp_token.token'], 'sparse': True},
                {'fields': ['children']},
                {'fields': ['email']},
                {'fields': ['parent']},
                {'fields': ['parse_id'], 'unique': True, 'sparse': True},
                {'fields': ['facebook_id'], 'unique': True, 'sparse': True},
                {'fields': ['phone']},
                {'fields': ['device_ids']},
                {'fields': ['was_reengaged'], 'sparse': True},
                {'fields': ['last_seen_time'], 'sparse': True},
                {'fields': ['invites_sent'], 'sparse': True},
                {'fields': ['created'], 'sparse': True},
                {'fields': ['username'], 'unique': True}],
            'auto_create_index': False}

    # Has this user announce their sign_up during find_frends?
    has_announced_signup = BooleanField()

    # An API access token. This can be used for a subset of API calls.
    api_token = StringField()

    # Users blocked by this user.
    blocked = ListField(ReferenceField('self', reverse_delete_rule=PULL),
                        default=None)

    # An optional personal bitly token for link management.
    bitly = StringField()

    # URL that should be called when user receives a Yo.
    callback = URLField()

    # URLs that should be called when user receives a Yo.
    callbacks = ListField(URLField())

    # Child accounts if such exists.
    children = ListField(ReferenceField('self', reverse_delete_rule=PULL),
                         default=None)

    # A description of this user account.
    description = StringField()

    # Device ids that have at any point been associated with this user.
    device_ids = ListField(StringField(), default=None)

    # Optional email address.
    email = StringField()

    # Admin status indicator
    is_admin = BooleanField()

    # beta tester indicator.
    is_beta_tester = BooleanField()

    # group indicator.
    is_group = BooleanField()

    is_done_polls_onboarding = BooleanField()

    # Private account status indicator
    is_private = BooleanField()

    is_guest = BooleanField()

    # is this explicitly set as a service.
    _is_service = BooleanField(db_field='is_service')

    # is this a "real person". Note, this currently isn't being
    # used but its good to have.
    _is_person = BooleanField(db_field='is_person')

    # Model validation errors from migrating parse data to mongodb.
    migration_errors = StringField()

    # Optional first-name to be displayed on a user's profile.
    first_name = StringField()

    # Optional last-name to be displayed on a user's profile.
    last_name = StringField()

    # Optional real-name to be displayed on a user's profile.
    name = StringField()

    # SHA1 of the username
    sha1_username = StringField()

    # Optional app name for Apps as Notifications apps.
    app_name = StringField()

    # Password. We could use a password field here, but the only difference to
    # a string field is that it outputs a password type input if used to
    # render HTML. Passwords are hashed using passlib.hash.bcrypt.
    # This field is not required since the user model is shared between regular
    # users, api users and potentially other types of users.
    password = StringField()

    # Parent account if such an account exists.
    parent = ReferenceField('self')

    # Phone number.
    phone = PhoneField()

    # Photo filename or URL.
    photo = StringField()

    # An emoji status
    status = StringField()

    status_last_updated = LongField()

    # Boolean value indicating if this account requests location data when
    # Yo'd.
    request_location = BooleanField()

    # Because usernames are not permanent we need a second identifier to
    # permanently identify a user. This field exists because that second
    # identifier while running on parse was the object id from the _User
    # table. This ID is incompatible with MongoDB's ObjectId so it wasn't
    # possible to re-use them as the _id for this table. This means we must
    # enforce versioning of authentication tokens, looking them up either
    # by parse_id or _id, depending on when the token was issued.
    parse_id = StringField()

    # Short lived token that can be used in emails or SMS messages for
    # e.g. password recovery.
    temp_token = EmbeddedDocumentField(AuthToken)

    # the user topic arn in sns. This is used to push notifications to all
    # of this user's endpoints
    topic_arn = StringField()

    # URL that should be called when user unsubscribes from this user.
    unsubscribe_callback = URLField()

    # The primary identifier of a Yo account.
    # It is important that the custom ModelConverter when using mongoengine
    # wtforms on models that reference this field, since otherwise wtforms
    # will build a dropdown with _all_ usernames.
    username = StringField(max_length=50,
                           required=True,
                           regex=USERNAME_REGEX,
                           unique=True)

    user_preferred_display_name = StringField()

    # Phone number verified?
    verified = BooleanField()

    # official entity controlling user
    is_official = BooleanField()

    # Is this user listed in the store
    in_store = BooleanField()

    # Is this user interactive. (not subscription based)
    is_interactive = BooleanField()

    # Is this user a pseudo-user who only receives texts and uses the web app
    is_pseudo = BooleanField()

    # If this user was a pseudo-user, when did they convert?
    converted_date = LongField()

    # The last time a user sent or received a yo.
    last_yo_time = LongField()

    # The last time a user sent  a yo.
    last_sent_time = LongField()

    # The last time a user received a yo.
    last_received_time = LongField()

    # The last time a user was considered active
    last_seen_time = LongField()

    # Was the user previously reengaged
    was_reengaged = BooleanField()

    last_reengamement_push_time = LongField()

    # URL that should be Yo'd to a user who subscribes to this user.
    welcome_link = URLField()

    # A counter of how many Yo's this person has received.
    count_in = LongField()

    # A counter of how many Yo's this person has sent.
    count_out = LongField()

    # A counter of how many invitations a user has sent.
    invites_sent = LongField()

    # A unicode representation of a custom emoji for the push text
    emoji = StringField()

    # The limits imposed on users sending a yoall.
    yoall_limits = StringField()

    # Facebook user id.
    facebook_id = StringField()

    coins = IntField()

    # The user object of account managing a publisher account
    phone_user = ReferenceField('self')

    # If this is a pseudouser who converted to a real user,
    # the user object of the real user.
    migrated_to = ReferenceField('self')

    # If this is a real user who was previously a pseudo user,
    # the user object of the pseudo user.
    migrated_from = ReferenceField('self')

    # The UTC offset of the last known timezone.
    utc_offset = IntField()

    # Last known TZ timezone.
    timezone = StringField()

    # last known country, city, and state.
    country_name = StringField()
    city = StringField()
    region_name = StringField()

    # the age range provided by facebook.
    age_range = StringField()

    # The gender reported by facebook.
    gender = StringField()

    # birthday reported by facebook.
    birthday = StringField()

    # user id of 3rd party clients (optional)
    external_user_id = StringField()

    stripe_id = StringField()

    latitude = FloatField()

    longitude = FloatField()

    def __str__(self):
        return self.user_id

    def clean(self):
        """Override cleaning performed prior to validation."""
        super(User, self).clean()

        self.clean_phone_field()
        # Remove empty URLs.
        if self.callback is not None and not self.callback:
            self.callback = None

        if self.first_name:
            self.first_name = self.first_name.strip()

        if self.last_name:
            self.last_name = self.last_name.strip()

        if self.name:
            self.name = self.name.strip()

    def clean_phone_field(self):
        """Cleans up the phone field"""
        if not self.phone:
            return

        if self.phone == '+1':
            self.phone = None
            return

        if len(self.phone) > 2 and self.phone.startswith('+1+'):
            self.phone = self.phone[2:]
        # Replace anything in the phone number which is not a digit or a
        # plus sign.
        self.phone = re.sub('[^+0-9]', '', self.phone)
        self.phone = '+' + self.phone.split('+')[-1]

        # Clean phone number using phonenumbers library.
        try:
            parsed_number = phonenumbers.parse(self.phone)
            self.phone = '+%s%s' % (parsed_number.country_code,
                                    parsed_number.national_number)
        except NumberParseException:
            # Number invalid so we leave it as it is. The field validator
            # should correctly raise an error.
            pass

    def set_password(self, value):
        """Hash the password using bcrypt before storing it."""
        self.password = bcrypt.encrypt(value)

    def verify_password(self, value):
        """Verify password against stored hash."""
        try:
            return bcrypt.verify(value, self.password)
        except (ValueError, TypeError) as err:
            raise APIError('Password missing or corrupt, please recover.')

    @property
    def is_subscribable(self):
        return bool(self.in_store and not self.callback)

    def get_public_dict(self,
                        display_name=None,
                        fields=None,
                        field_list=None,
                        last_yo=None):

        field_list = field_list or 'public'

        if (field_list == 'account' and
            not (AccountPermission(self).can() or admin_permission.can())):
            field_list = 'public'

        if field_list == 'admin' and not admin_permission.can():
            field_list = 'public'

        if field_list == 'admin' and admin_permission.can():
            field_list = 'admin'

        if not fields:
            fields = FIELD_LIST_MAP.get(field_list, PUBLIC_FIELDS)

        country_code = self.country_code
        if country_code:
            country_code = str(country_code)

        extras = {'photo': get_image_url(self.photo),
                  'display_name': display_name or self.display_name,
                  'last_yo': last_yo,
                  'country_code': country_code,
                  'status': self.status,
                  'yo_count': self.yo_count,
                  'is_yo_team': self.is_admin or False,
                  'verified': bool(self.verified)}

        public_dict = {}

        for return_key, user_attr in fields:

            # let extras overwrite things.
            if user_attr in extras:
                val = extras.get(user_attr)
            elif hasattr(self, user_attr):
                val = getattr(self, user_attr)
            else:
                message = 'Requesting none existent key %s:%s on user'
                message = message % (user_attr, return_key)
                current_app.log_error(message)
                continue

            if val is not None:
                public_dict[return_key] = val

        if self.phone_user:
            public_dict['phone_username'] = self.phone_user.username

        return public_dict


    @property
    def country_code(self):
        """Returns the country code of the user's phone number"""
        try:
            parsed_number = phonenumbers.parse(self.phone)
            return parsed_number.country_code
        except NumberParseException:
            # Number invalid so we leave it as it is. The field validator
            # should correctly raise an error.
            pass


    @property
    def yo_count(self):
        yo_count = 0
        if self.count_in:
            yo_count += self.count_in
        if self.count_out:
            yo_count += self.count_out
        return yo_count


    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return '%s %s' % (self.first_name, self.last_name)

        if self.first_name:
            return self.first_name

        if self.last_name:
            return self.last_name

        return self.name

    @staticmethod
    def convert_name_to_display(name, last=None):
        all_caps = bool(re.match(r'(?=^[^a-z]*$).*[A-Z]{3,}', name))

        name = name.strip()

        if last:
            last = last.strip()
            name_parts = [name, last]
        else:
            name_parts = name.split(' ')

        name_parts = [p for p in name_parts if p]
        first_name = None
        last_initial = None
        if len(name_parts) > 0:
            first_name = name_parts[0].split(' ')[0]
            if all_caps:
                first_name = '%s%s' % (first_name[:1], first_name[1:].lower())

        if len(name_parts) > 1:
            last_initial = name_parts[1][:1].upper()
            # Avoid sending partial unicode characters, or truncating
            # non-ascii last names.
            if not re.search('^[A-Z]$', last_initial):
                return '%s %s' % (first_name, name_parts[1]) 

        if first_name and last_initial:
            return '%s %s.' % (first_name, last_initial)

        if first_name:
            return first_name

    @property
    def has_good_name(self):
        return (self.is_group or self.parent or self.in_store or
            self.first_name or self.last_name or self.name or
            self.welcome_link or self.callback)

    @property
    def display_name(self):
        """Returns the first name and last initial"""
        if self.is_group:
            return self.name

        if self.app_name:
            return self.app_name

        if self.user_preferred_display_name:
            return self.user_preferred_display_name

        if self.is_service:
            return self.username

        if (self.first_name and self.last_name and
            self.first_name.strip() and self.last_name.strip()):
            return self.convert_name_to_display(self.first_name,
                                                last=self.last_name)
        elif self.first_name and self.first_name.strip():
            return self.convert_name_to_display(self.first_name)
        elif self.last_name and self.last_name.strip():
            return self.convert_name_to_display(self.last_name)
        elif self.name and self.name.strip():
            name = self.name.strip()
            name_parts = [part.strip() for part in name.split(' ') if part.strip()]
            if len(name_parts) > 5:
                return self.username
            # Try to convert names like John Doe to John D.
            # Try to convert names like JON DOE to Jon D.
            return self.convert_name_to_display(self.name)

        return self.username.title()

    @property
    def user_id(self):
        """Returns the user id as a string"""
        return str(self.id) if self.id else None

    @property
    def user_type(self):
        """Returns the type of user:
            user
            group
            pseudo
        """
        user_type = 'user'
        if self.is_group:
            user_type = 'group'
        if self.is_pseudo:
            user_type = 'pseudo_user'
        return user_type

    @property
    def is_person(self):
        # Allows us to override these checks.
        if self._is_person is not None:
            return self._is_person

        # Saying that a user is a real person is interesting because
        # "real people" can also be functional. Some examples include:
        # If they are in the store they are definitely a service, but that
        # doesn't mean they aren't a person: LILBUB, EDDIEGRIFFIN.
        # If they have a callback or welcome link.


        # If this is a group it definitely isn't a person.
        if self.is_group:
            return False

        # This is interesting. Not sure what it should be set to.
        if self.is_pseudo:
            return True

        # These fields can only be set via the app.
        if self.first_name or self.last_name:
            return True
        if self.facebook_id:
            return True
        if self.invites_sent:
            return True
        # These are only set if a user has added a phone number
        # at some point.
        if self.temp_token or self.verified or self.phone:
            return True

        if self.bitly:
            return False
        if self.request_location is not None:
            return False
        
        # If this user has a parent, it is most likely created on the
        # dashboard. Accounts like these could also have been turned into
        # "real users" but that is unlikely.
        if self.parent:
            return False

        # If the ratio of yos received to yos sent is very high this
        # is probably a service.
        if (self.count_in and self.count_out and
            self.count_in / self.count_out > 3):
            return False


        # Last resort checks that aren't very accurate.
        # If the name is considerably long this is likely a description.
        if self.name:
            name = self.name.strip()
            name_parts = [part.strip() for part in name.split(' ') if part.strip()]
            name = ''.join(name_parts)
            if len(name_parts) > 5:
                return False

        # True by default.
        return True

    @property
    def is_service(self):
        # Allows us to override these checks.
        if self._is_service is not None:
            return self._is_service

        # If this is a group it definitely isn't a service.
        if self.is_group:
            return False
        # If they are in the store they are definitely a service.
        if self.in_store:
            return True

        if self.is_pseudo:
            return False

        if self._is_person:
            return False

        # These fields can only be set via the dashboard.
        # Albeit any user can log in and do this, it wouldn't make sense
        # for a regular user to set these fields.
        if self.callback or self.welcome_link:
            return True
        if self.bitly:
            return True
        if self.request_location is not None:
            return True
        
        # If this user has a parent, it is most likely created on the
        # dashboard. Accounts like these could also have been turned into
        # "real users" but that is unlikely.
        if self.parent:
            return True

        # If the ratio of yos received to yos sent is very high this
        # is probably a service.
        if (self.count_in and self.count_out and
            self.count_in / self.count_out > 3):
            return True

        # These fields can only be set via the app.
        # Albeit services could have used the app at one point,
        # the hope is they never make it to these checks.
        if self.first_name or self.last_name:
            return False
        if self.facebook_id:
            return False
        if self.invites_sent:
            return False

        # These are only set if a user has added a phone number
        # at some point.
        if self.temp_token or self.verified or self.phone:
            return False

        # Last resort checks that aren't very accurate.
        # If the name is considerably long this is likely a description.
        if self.name:
            name = self.name.strip()
            name_parts = [part.strip() for part in name.split(' ') if part.strip()]
            name = ''.join(name_parts)
            if len(name_parts) > 5:
                return True
            if len(name_parts) == 2:
                return False

        # False by default. Even though some cases could be removed and
        # use this default it is better to be explicit.
        return False

    def has_dbrefs(self):
        """Checks if there are any users that could not be
        dereferenced."""
        if isinstance(self.parent, DBRef):
            return True

        if self.blocked and isinstance(self.blocked, list):
            for user in self.blocked:
                if isinstance(user, DBRef):
                    return True

        if self.children and isinstance(self.children, list):
            for user in self.children:
                if isinstance(user, DBRef):
                    return True

        return False

    def has_blocked(self, user):
        """Returns True if this user is in our blocked list"""
        if not self.blocked:
            return False

        return user in self.blocked

    def as_topic(self):
        return {
            'id': self.user_id,
            'name': self.name,
            'description': self.description,
            'callback_url': self.callback_url
        }
