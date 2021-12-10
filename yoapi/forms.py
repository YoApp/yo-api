# -*- coding: utf-8 -*-

"""Forms related module"""

import re
import wtforms_json

from flask_wtf import Form as FlaskForm
from flask_mongoengine.wtf import model_form
from flask_mongoengine.wtf.orm import ModelConverter, converts
from flask_mongoengine.wtf.fields import NoneStringField
from wtforms.fields import StringField, FieldList, FormField, SelectField
from wtforms.validators import InputRequired, Regexp, Optional, Length

from .models import User, Yo
from .errors import APIFormError

from .models.helpers import URLFieldValidator
from .constants.regex import (LOCATION_REGEX, LOCATION_ERR_MESSAGE,
                              CONTEXT_REGEX, CONTEXT_ERR_MESSAGE,
                              USERNAME_REGEX, USERNAME_ERR_MESSAGE,
                              REAL_USERNAME_REGEX)

wtforms_json.init()


class YoModelConverter(ModelConverter):

    """Subclassing ModelConverter to exclude ReferenceField

    The WTForms conversion between mongoengine and wtforms maps a reference
    field to a Select element and fetches choices from the database. This
    is extremely bad when referencing the user collection since it is very
    large. Therefore let's eliminate the reference field conversion.
    """

    def __init__(self, *args, **kwargs):
        super(YoModelConverter, self).__init__(*args, **kwargs)

    @converts('ReferenceField')
    def conv_Reference(self, model, field, kwargs):
        return NoneStringField(**kwargs)

    @converts('URLField')
    def conv_URL(self, model, field, kwargs):
        kwargs['validators'].append(URLFieldValidator())
        self._string_common(model, field, kwargs)
        return NoneStringField(**kwargs)


class Form(FlaskForm):

    def validate(self):
        if super(Form, self).validate():
            return True
        else:
            raise APIFormError('Received invalid data', payload=self.errors)


excluded_user_fields = ['is_admin', 'temp_token', 'device_ids',
                        'api_token', 'parent', 'in_store',
                        'verified', 'count_out', 'count_in',
                        'is_group', 'has_announced_signup',
                        'blocked', 'children', 'is_beta_tester',
                        'is_private', 'migration_errors',
                        'parse_id', 'facebook_id', 'topic_arn',
                        'unsubscribe_callback', 'is_official',
                        'last_seen_time', 'was_reengaged',
                        'invites_sent', 'yoall_limits', 'is_pseudo']
excluded_existing_user_fields = excluded_user_fields + ['username']
excluded_group_user_fields = excluded_existing_user_fields  + ['password']


APIUserForm = model_form(User, Form, converter=YoModelConverter(),
                         exclude=excluded_user_fields + ['email'],
                         field_args={'username':{
                             'validators': [InputRequired(),
        Regexp(REAL_USERNAME_REGEX, message=USERNAME_ERR_MESSAGE)]
                             }})

UpdateUserForm = model_form(User, Form, converter=YoModelConverter(),
                            exclude=excluded_existing_user_fields)

UpdateGroupForm = model_form(User, Form, converter=YoModelConverter(),
                            exclude=excluded_group_user_fields)

UserForm = model_form(User, Form, converter=YoModelConverter(),
                      exclude=excluded_user_fields)

YoForm = model_form(Yo, Form, converter=YoModelConverter(),
                    exclude=['parent', 'children'])


class GroupMemberForm(Form):
    name = StringField()
    display_name = StringField()
    username = StringField(default=None,
        validators=[Optional(), Regexp(USERNAME_REGEX, flags=re.IGNORECASE,
                                       message=USERNAME_ERR_MESSAGE)])
    phone_number = StringField()
    user_type = SelectField(choices=[('user', 'user'),
                                     ('pseudo_user', 'pseudo_user')],
                            validators=[InputRequired()])


class AddGroupForm(Form):
    name = StringField()
    description = StringField()
    members = FieldList(FormField(GroupMemberForm))


class BroadcastYoForm(Form):
    context = StringField(
        validators=[Optional(), Regexp(CONTEXT_REGEX, flags=re.UNICODE,
                                       message=CONTEXT_ERR_MESSAGE)])
    header = StringField()
    link = StringField()
    location = StringField(
        validators=[Optional(),
                    Regexp(
                        LOCATION_REGEX, message=LOCATION_ERR_MESSAGE)])
    username = StringField(default=None,
        validators=[Optional(), Regexp(USERNAME_REGEX, flags=re.IGNORECASE,
                                       message=USERNAME_ERR_MESSAGE)])
    sound = StringField()
    yo_id = StringField()


class LoginForm(Form):
    username = StringField()
    email = StringField()
    phone = StringField()
    password = StringField(validators=[InputRequired()])


class GetUserForm(Form):
    username = StringField(default=None,
        validators=[Optional(), Regexp(USERNAME_REGEX, flags=re.IGNORECASE,
                                       message=USERNAME_ERR_MESSAGE)])
    device_ids = StringField()
    user_id = StringField()
    parse_id = StringField()
    api_token = StringField()
    phone = StringField()
    email = StringField()


class FindUserForm(GetUserForm):
    username__startswith = StringField()
    username__endswith = StringField()
    username__contains = StringField()


class InviteContactForm(Form):
    contact_name = StringField(validators=[InputRequired()])
    number = StringField(validators=[InputRequired()])
    country_code_if_missing = StringField()


class RegisterDeviceForm(Form):
    push_token = StringField(validators=[])
    device_type = StringField(validators=[InputRequired()])


class SendYoForm(Form):
    recipients = StringField()
    context = StringField(
        validators=[Optional(),
                    Regexp(CONTEXT_REGEX, flags=re.UNICODE,
                           message=CONTEXT_ERR_MESSAGE)])
    sound = StringField()
    link = StringField()
    location = StringField(
        validators=[Optional(),
                    Regexp(
                        LOCATION_REGEX, message=LOCATION_ERR_MESSAGE)])
    header = StringField()
    yo_id = StringField()
    contact_name = StringField()


class SignupForm(UserForm):
    """Subclassing the userform to make password required"""
    username = StringField(validators=[InputRequired(),
        Regexp(REAL_USERNAME_REGEX, message=USERNAME_ERR_MESSAGE)])
    password = StringField(validators=[InputRequired()])


class SubscribeForm(Form):
    push_token = StringField(validators=[InputRequired()])
    device_type = StringField(validators=[InputRequired()])


class UnregisterDeviceForm(Form):
    push_token = StringField()


class UnsubscribeForm(Form):
    push_token = StringField()


class UsernameForm(Form):
    username = StringField(validators=[Regexp(USERNAME_REGEX,
                                              flags=re.IGNORECASE,
                                              message=USERNAME_ERR_MESSAGE)]) 


class YoFromApiAccountForm(SendYoForm):
    sender = StringField(validators=[InputRequired()])
