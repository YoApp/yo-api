# -*- coding: utf-8 -*-

"""Account management package."""

import random
import pytz
import sys
from base64 import b64decode
from uuid import uuid4

import re
import requests
from bson import ObjectId
from datetime import datetime
from flask import current_app, g, request
from mongoengine import NotUniqueError, DoesNotExist, Q
from pytz import UnknownTimeZoneError
from parse_rest.user import User as ParseUser
from phonenumbers.phonenumberutil import NumberParseException
from requests.exceptions import RequestException
from .async import async_job
from .constants.regex import USERNAME_REGEX
from .core import cache, s3, twilio, sendgrid, redis, facebook
from .errors import APIError
from .helpers import (random_string, get_usec_timestamp, get_remote_addr,
                      random_number_string, clean_phone_number,
                      get_location_data)
from .models import (User, AuthToken, SignupLocation, Device,
                     NotificationEndpoint)
from .permissions import (assert_view_permission, assert_account_permission,
                          assert_admin_permission)
from .services import low_rq
from .urltools import UrlHelper



# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name


sms_redis_prefix = 'yoapi:sms:'

@async_job(rq=low_rq)
def add_email_to_mailchimp(email):
    """If the user has an email address on file add it to the mailchimp
    list"""
    request_json = {
        'apikey': current_app.config.get('MAILCHIMP_API_KEY'),
        'id': current_app.config.get('MAILCHIMP_LIST_ID'),
        'email': {'email': email},
        'double_optin': False
    }
    mailchimp_server = current_app.config.get('MAILCHIMP_SERVER')
    endpoint_url = '%s/%s' % (mailchimp_server, 'lists/subscribe.json')
    requests.post(endpoint_url, json=request_json)

def clear_profile_picture(user):
    """Clears the profile picture for a user"""
    if user.photo and not user.photo.startswith('http'):
        try:
            s3.delete_image(user.photo)
        except:
            """Since we're not sure what error could occur here log them"""
            current_app.log_exception(sys.exc_info())

    user.photo = None
    user.save()

    # Always clear the cache after modifying a user object.
    clear_get_user_cache(user)


def clear_get_facebook_user_cache(facebook_id):
    """Clears the cache for the given facebook user's id"""
    cache.delete_memoized(_get_facebook_user, facebook_id)


def clear_get_user_cache(user):
    """A convenience method to clear the _get_user cache"""
    cache.delete_memoized(_get_user, user_id=str(user.user_id))
    cache.delete_memoized(_get_user_by_username, str(user.username))
    if user.facebook_id:
                clear_get_facebook_user_cache(user.facebook_id)


def write_through_user_cache(user):
    """Write the changes on a user object directly to the cache
    and the database to reduce the number of calls needed.

    First save the user so that the changes are put into the db.
    Second, reload the user so that any changes made directly to
        to the db will be present in cache.
    Last, write the new user object directly to the cache.
    """

    user.save()
    user.reload()

    _func = _get_user
    cache_key = _func.make_cache_key(_func.uncached,
                                     user_id=user.user_id)
    cache.cache.set(cache_key, user)

    _func = _get_user_by_username
    cache_key = _func.make_cache_key(_func.uncached,
                                     str(user.username))
    cache.cache.set(cache_key, user)

    clear_get_facebook_user_cache(user.facebook_id)


def complete_account_verification_by_sms(user, token, number):
    """Verifies token and marks account as verified. 

    Arguments: user
    token
    number: must be the "clean" phone number that starts with +
    """
    if not user.temp_token:
        raise APIError('No verification code set.')

    assert_valid_temp_token(user, token)
    user.verified = True
    user.temp_token.used = get_usec_timestamp()
    # this should be unnecessary.
    user.phone = number
     
    user.save()
    # Always clear the cache after modifying a user object.
    clear_get_user_cache(user)


def confirm_password_reset(user, token, new_password):
    """Sets a new password for a user if the auth token matches"""
    assert_valid_temp_token(user, token)
    user.temp_token.used = get_usec_timestamp()
    user.set_password(new_password)
    user.save()
    # Always clear the cache after modifying a user object.
    clear_get_user_cache(user)


def assert_valid_temp_token(user, token):
    """Verifies a temporary token against what is stored in the user object"""
    if not user.temp_token:
        # Ensure the user has a token
        # TODO: Validate under what circumstance this can happen.
        raise APIError('Verification token missing.')

    elif token == user.temp_token.token:
        # Check if the token has already been used.
        if user.temp_token.used:
            raise APIError('Verification code already used.')

        # Check if the token has expired. The default expiration time should
        # be one day.
        if user.temp_token.expires < get_usec_timestamp():
            raise APIError('Verification code expired.')

    else:
        print '111111 ' + user.temp_token.token + ' ' + token
        raise APIError('Verification code incorrect.')

def make_valid_username(name):
    '''Ensures that a username will pass the validation regex in the form'''

    # if the username is already valid, don't mutate it.
    if re.match(USERNAME_REGEX, name):
        return name
    # convert to 7-bit ascii so that isalpha() and isalnum()
    # will behave themselves
    name = name.encode('ascii', 'ignore')
    first_letter_match = re.search('[A-Za-z]', name)
    if not first_letter_match:
        padding = random_number_string(length=6)
        username = '%s%s' % ('YOUSER', padding)
        return username
    f_l_index = first_letter_match.start(0)
    name = name[f_l_index:f_l_index + 50]
    username = ''.join([c.upper() for c in name if c.isalnum()])

    if not username:
        padding = random_number_string(length=6)
        username = '%s%s' % ('YOUSER', padding)
    return username

def make_username_unique(original_username, random_length=4, use_letters=False):
    username = make_valid_username(original_username)
    try:
        other_user = _get_user_by_username(username)
    # user not found
    except APIError:
        return username

    # If the user exists then generate a username with random numbers
    # appened at the end.
    if use_letters:
        padding = random_string(length=random_length).upper()
    else:
        padding = random_number_string(length=random_length)
    username = '%s%s' % (username[:50 - random_length], padding)

    return username

def link_facebook_account(token):
    """Links the facebook account provided via token to a user"""
    user = g.identity.user
    fields = ['id', 'email', 'first_name', 'last_name', 'name', 'gender',
              'age_range,' 'birthday']
    facebook_profile = facebook.get_profile(token, fields=fields)
    facebook_id = facebook_profile.get('id')
    if not facebook_id:
        raise APIError('Invalid facebook id')

    try:
        facebook_user = _get_facebook_user(facebook_id)
        if facebook_user != user:
            update_user(facebook_user, facebook_id=None,
                        ignore_permission=True)
    except DoesNotExist:
        pass

    full_name = facebook_profile.get('name', '')
    first_name = facebook_profile.get('first_name', '')
    last_name = facebook_profile.get('last_name', '')
    email = facebook_profile.get('email')
    name = full_name or '%s%s' % (first_name, last_name)
    birthday = facebook_profile.get('birthday')
    gender = facebook_profile.get('gender')
    age_range = facebook_profile.get('age_range')
    age_range_str = None
    if age_range:
        if age_range.get('min'):
            age_range_str = '%s+' % age_range.get('min')
        elif age_range.get('max'):
            age_range_str = '%s-' % age_range.get('max')
    image_data = None
    try:
        picture_data = facebook.get_profile_picture(token)
        if not picture_data.get('is_silhouette'):
            req = requests.get(picture_data.get('url'))
            if req.headers.get('content-type').startswith('image'):
                image_data = req.content
    except:
        # There seem to be some weird ssl issues here. For now
        # send an email but make sure the call succeeds.
        current_app.log_exception(sys.exc_info())

    return update_user(user, facebook_id=facebook_id,
                       name=full_name, email=email, first_name=first_name,
                       last_name=last_name, photo_data=image_data,
                       gender=gender, age_range=age_range_str,
                       birthday=birthday)


def find_users_by_numbers(numbers, country_code_if_missing='1',
                          user_phone=None, include_pseudo=False):
    """Returns contacts that match any of the given phone numbers

    Because contacts are often stored without a country code prefix, we add
    the user's own country code where applicable. This seems like a better
    method than matchin friends against local numbers since false positives
    are very likely to occur.

    Args:
        phone_numbers: An array of phone numbers.
    """
    number_map = {}
    for number in numbers:
        try:
            valid_number = clean_phone_number(number, country_code_if_missing,
                                              user_phone)
            number_map[valid_number] = number
        except NumberParseException:
            # Number invalid so we can't include it in the search.
            pass

    matches = User.objects(phone__in=number_map.keys(), verified=True)
    for user in matches:
        if not user.is_pseudo or include_pseudo:
            original_number = number_map[user.phone]
            yield original_number, user


def upsert_pseudo_user(phone_number, created_by_group=False):
    """Gets a user by phone number, or creates a psuedo user. 
    
    phone_number may be "dirty", and after cleaning will 
    start with + and include a country code.
    """
    user = None
    country_code_if_missing = g.identity.user.country_code or '1'
    try:
        phone_number = clean_phone_number(phone_number,
                                          country_code_if_missing,
                                          g.identity.user.phone)
    except NumberParseException:
        raise APIError('Invalid phone number')

    # find_users_by_numbers returns (phone number, user)
    users = [u[1] for u in find_users_by_numbers([phone_number],
                include_pseudo=True)]
    for u in users:
        if u.parent or u.in_store:
            continue
        if not user or u.last_seen_time > user.last_seen_time:
            user = u
    if not user:
        user = create_user(username=phone_number[1:], phone=phone_number,
                           is_pseudo=True, verified=True)

        event_data = {'event': 'pseudo_user_created',
                      'phone': phone_number,
                      'creator': g.identity.user.username,
                      'is_group': created_by_group}
        current_app.log_analytics(event_data)

    return user


def upsert_facebook_user(token):
    """Gets or creates a facebook user"""
    fields = ['id', 'email', 'first_name', 'last_name', 'name', 'gender',
              'age_range,' 'birthday']
    facebook_profile = facebook.get_profile(token, fields=fields)
    facebook_id = facebook_profile.get('id')
    if not facebook_id:
        raise APIError('Invalid facebook id')

    try:
        user = _get_facebook_user(facebook_id)
    except DoesNotExist:
        user = None

    full_name = facebook_profile.get('name', '')
    first_name = facebook_profile.get('first_name', '')
    last_name = facebook_profile.get('last_name', '')
    name = full_name or '%s%s' % (first_name, last_name)
    if user:
        username = user.username
    else:
        username = make_username_unique(name)

    email = facebook_profile.get('email')
    birthday = facebook_profile.get('birthday')
    gender = facebook_profile.get('gender')
    age_range = facebook_profile.get('age_range')
    age_range_str = None
    if age_range:
        if age_range.get('min'):
            age_range_str = '%s+' % age_range.get('min')
        elif age_range.get('max'):
            age_range_str = '%s-' % age_range.get('max')

    picture_data = facebook.get_profile_picture(token)
    image_data = None
    if picture_data and not picture_data.get('is_silhouette'):
        try:
            req = requests.get(picture_data.get('url'))

            if req.headers.get('content-type').startswith('image'):
                image_data = req.content
        except RequestException:
            url = picture_data.get('url')
            current_app.log_exception(sys.exc_info(),
                                      fb_picture_url=url)

    if user:
        return update_user(user, name=full_name, email=email,
                           first_name=first_name, last_name=last_name,
                           photo_data=image_data, gender=gender,
                           age_range=age_range_str, birthday=birthday,
                           ignore_permission=True)

    current_app.log_analytics({'event': 'facebook_user_created',
                               'username': username,
                               'facebook_id': facebook_id})

    return create_user(username=username, facebook_id=facebook_id,
                       name=full_name, email=email, first_name=first_name,
                       last_name=last_name, photo_data=image_data,
                       gender=gender, age_range=age_range_str,
                       birthday=birthday)


def create_user(**kwargs):
    """Registers a new user with the backend.

    Args:
        username: A username.
        password: A password.
        kwargs: Additional data to be stored with the account.
    Returns:
        A user object.
    """
    # If a password is provided then it should be set through a method hashing
    # it using bcrypt.
    password = kwargs.pop('password', None)

    # If we are setting a photo then we need to pop the image data before
    # creating the model.
    b64_image = None
    if 'photo' in kwargs:
        b64_image = kwargs.pop('photo')

    image_data = None
    if 'photo_data' in kwargs:
        image_data = kwargs.pop('photo_data')

    # Validate url's early
    if kwargs.get('welcome_link'):
        welcome_link = kwargs.get('welcome_link')
        kwargs.update({'welcome_link': UrlHelper(welcome_link).get_url()})

    # Validate url's early
    if kwargs.get('callback'):
        callback = kwargs.get('callback')
        kwargs.update({'callback': UrlHelper(callback).get_url()})

    # Create new user object.
    user = User(**kwargs)
    user.api_token = str(random_string(5)) if user.is_pseudo else str(uuid4())

    # Set password if it was provided.
    if password:
        user.set_password(password)

    # Save the new object and return. It is crucial that the unique index
    # constraint exists as the save will otherwise not throw an exception.
    # We avoid accidentally updating an existing user by specifying
    # force_insert, which raises an exception if the document already exists.
    try:
        # Signup with Parse while we're still using it for push.
        # api accounts don't require passwords
        password = password or str(uuid4())

        # Force insert avoids overwrites.
        user.save(force_insert=True)

        # Add as child to parent if parent exists.
        if user.parent:
            user.parent.update(push__children=user)
            # Always clear the cache after modifying a user object.
            clear_get_user_cache(user.parent)
    except NotUniqueError:
        raise APIError('User already exists.', 422)

    # This has to be done after the user has been saved since the function
    # needs the document id.
    try:
        if b64_image:
            kwargs['photo'] = set_profile_picture(user, b64_image,
                                                  save_model=True)
        if image_data:
            kwargs['photo'] = set_profile_picture(user, image_data=image_data,
                                                  save_model=True)
    except:
        current_app.log_exception(sys.exc_info())
        pass

    # Always clear the cache after modifying a user object.
    clear_get_user_cache(user)

    if kwargs.get('facebook_id'):
        clear_get_facebook_user_cache(kwargs.get('facebook_id'))

    return user


def delete_user(user, clear_parent_cache=True, ignore_permission=False):
    """Deletes a user from the user table as well as clears device
    registrations in parse.

    Args:
        user: The user being deleted
        clear_parent_cache: Prevents parent cache from being
                            cleared multiple times unnecessarily
                            for recursive calls
    """
    if not ignore_permission:
        assert_account_permission(user, 'No permission to delete user.')

    #if not user.parent:
    #    # Allow ONLY admins to delete un-parented accounts
    #    assert_admin_permission('Only Admins can delete primary accounts.')

    if user.parent and user in user.parent.children:
        user.parent.children.remove(user)
        if clear_parent_cache:
            clear_get_user_cache(user.parent)

    if user.children:
        for child in user.children:
            # Don't delete children that are groups.
            if child.is_group:
                child.parent = None
                child.save()
                clear_get_user_cache(child)
            else:
                delete_user(child, clear_parent_cache=False)
    if user.facebook_id:
        clear_get_facebook_user_cache(user.facebook_id)
    cached_objectid = ObjectId(user.user_id)
    cached_user = User(id=cached_objectid, username=user.username)
    user.delete()
    # Always clear the cache after modifying a user object.
    clear_get_user_cache(cached_user)

    # Delete user from parse.
    # Since we are no longer signing user up to parse we do not care if
    # either of these calls fail.
    try:
        parse_user = ParseUser.Query.get(username=cached_user.username)
        ParseUser.DELETE(parse_user._absolute_url)
    except:
        pass


def login(username=None, email=None, password=None, phone=None):
    """Validates the user by either username and password or session token.

    Args:
        username: An optionl username.
        password: A optional password.

    Returns:
        A bool indicator.
    """

    if email:
        users = User.objects(username__startswith='POLL', email=email).order_by('-created').limit(1)
        if len(users) == 0:
            raise APIError('No such user.', code=101, status_code=404)
        user = users[0]
        if user.parent:
            user = user.parent
    elif phone:
        phone = clean_phone_number(phone)
        users = User.objects(phone=phone, verified=True).order_by('-created').limit(1)
        if len(users) == 0:
            raise APIError('No such user.', code=101, status_code=404)
        user = users[0]
    else:
        user = get_user(username, ignore_permission=True)
    if user.verify_password(password):
        if not user.api_token:
            update_user(user, api_token=str(uuid4()), ignore_permission=True)
        return user
    else:
        raise APIError('Password incorrect.', code=101, status_code=401)


def find_users(**kwargs):
    assert_admin_permission('Unauthorized access. Admins only.')
    if not kwargs:
        raise APIError('no arguments to find_users')
    user_ids = find_user_ids(**kwargs)
    return [get_user(user_id=user_id) for user_id in user_ids]


def get_user(username=None, user_id=None, ignore_permission=False, **kwargs):
    """Gets a Yo user account by any combination of the following:
        * user_id
        * username
        * parse_id
        * api_token
        * email
        * phone
        * device_ids

    This is sensitive information so we need to be careful to protect this
    function with proper needs.

    The reason we call a private function here is because mongodb returns
    unicode strings and the endpoints often deal with regular byte strings.
    As a result, we would otherwise end up with different cached copies
    of the function response.

    Returns:
        A User object.
    """

    # lookup by username is cached so check this first

    if username:
        # We treat the username differently because clients still depend on
        # looking users up by username. Without a memoized function these
        # lookups would become costly.
        user = _get_user_by_username(str(username).upper())
        if not ignore_permission:
            # Make sure we can access this object.
            assert_view_permission(user, 'No permission to view user.')
        return user

    installation_id = kwargs.get('device_ids')

    user_id = user_id if user_id else find_user_id(**kwargs)
    if installation_id and not user_id:
        user_id = find_user_id_by_installation_id(installation_id)
    if not user_id:
        raise APIError('Unable to locate user', code=404, status_code=404)

    user = _get_user(user_id=str(user_id))

    if not ignore_permission:
        # Make sure we can access this object.
        assert_view_permission(user, 'No permission to view user.')

    return user


@cache.memoize()
def _get_facebook_user(facebook_id):
    """Memoized getter for user by facebook_id"""

    # This keeps us from accidentally returning all users
    # without a facebook id.
    if not facebook_id:
        raise DoesNotExist('Invalid facebook id')

    return User.objects(facebook_id=facebook_id).get()


@cache.memoize()
def _get_user_by_username(username):
    """Memoized getter for user by username"""
    user_id = find_user_id(username=username)
    return _get_user(user_id=str(user_id))


@cache.memoize()
def _get_user(user_id=None):
    try:
        user = User.objects(id=user_id).get()
        # Make sure we have permission to view the profile data.
        return user
    except DoesNotExist:
        raise APIError('User %s does not exist' % user_id, status_code=404)


def find_user_id(**kwargs):
    user_ids = find_user_ids(**kwargs)
    if not user_ids:
        raise APIError('No user found', status_code=404, code=404)
    # TODO: this is in place to restore the previous functionality
    # of using device_id for api_token
    #if len(user_ids) > 1 and 'api_token' not in kwargs:
    #    raise APIError('Multiple objects found', status_code=400, code=404)
    return user_ids[0]


def find_user_id_by_installation_id(installation_id):

    endpoints = NotificationEndpoint.objects.filter(installation_id=installation_id)
    if len(endpoints) > 0:
        endpoint = endpoints[0]
        if endpoint.owner:
            return endpoint.owner.user_id


def find_user_ids(**kwargs):
    """Finds and returns user ids

    There are times when lack the user id and need to look it up by any out
    of the following:

        * username
        * parse_id
        * api_token
        * email
        * phone
        * udid
    """
    # if called with no arguments, this will return all users. Stop it.
    if not kwargs:
        return []
    # Only ever use one criteria at a time.
    # this function doesn't check that you're only using one criteria
    criteria = None
    for key, value in kwargs.items():
        # TODO: this is in place to restore the previous functionality
        # of using device_id for api_token
        if key == 'api_token':
            criteria = Q(**{key: value}) | Q(device_ids__in=[value]) & criteria
        else:
            criteria = Q(**{key: value}) & criteria
    user_ids_found = User.objects(criteria).only('id').limit(50)

    return [user.user_id for user in user_ids_found]


def record_signup_location(user):
    """This is a stopgap solution to recording from where users sign up."""
    address = get_remote_addr(request)
    data = get_location_data(address)
    if not data:
        return

    if data.get('metro_code') is not None:
        data.update({'metro_code': str(data.get('metro_code'))})
    SignupLocation(user=user, **data).save()


def record_get_me_location(user):
    address = get_remote_addr(request)
    data = get_location_data(address)
    if not data:
        return

    user_data = {
        'last_ip': address
    }

    if data.get('city'):
        user_data.update({'city': data.get('city')})

    if data.get('region_name'):
        user_data.update({'region_name': data.get('region_name')})

    if data.get('country_name'):
        user_data.update({'country_name': data.get('country_name')})

    if data.get('latitude'):
        user_data.update({'latitude': data.get('latitude')})

    if data.get('longitude'):
        user_data.update({'longitude': data.get('longitude')})

    if data.get('zip_code'):
        user_data.update({'zip_code': data.get('zip_code')})

    if data.get('time_zone'):
        user_data.update({'timezone': data.get('time_zone')})
        try:
            tzinfo = pytz.timezone(data.get('time_zone'))
            offset_delta = tzinfo.utcoffset(datetime.now())
            offset_hours = offset_delta.total_seconds()/3600
            user_data.update({'utc_offset': offset_hours})
        except UnknownTimeZoneError:
            current_app.log_exception(sys.exc_info())

    # Only update the data if we have a valid timezone and country code.
    # Remove any existing data so that we don't keep partial incorrect info.
    if 'utc_offset' in user_data and 'country_name' in user_data:
        user_data.setdefault('city', None)
        user_data.setdefault('region_name', None)
        update_user(user, ignore_permission=True, **user_data)


def reset_password_by_sms(user):
    """Sends an password reset link by SMS"""
    if not user.phone:
        raise APIError('User %s has no assigned phone number.' % user.username)

    # AuthToken default expiry should be 1 day.
    token = AuthToken(token=random_string())
    user = update_user(user, temp_token=token)

    # TODO: figure out what exceptions this method can raise and handle them.
    link = 'http://recover.justyo.co/change.html?c=%s&u=%s' % (
        user.temp_token.token, user.username)
    message = 'Yo passcode reset: ' + link
    twilio.send(user.phone, message)


def set_profile_picture(user, b64_image=None, image_data=None,
                        save_model=True):
    """Sets profile picture for a user"""

    if not (b64_image or image_data):
            raise APIError('Invalid image data')

    if b64_image:
        try:
            image = b64decode(b64_image)
        except TypeError as err:
            # The b64 decoder will fail unless the data is b64 encoded.
            raise APIError('Invalid image data')
    if image_data:
        image = image_data

    filename = str(user.id) + str(uuid4())[:8] + '.jpg'

    url = s3.upload_image(filename, image)

    # Sometimes we want to avoid multiple saves, such as when updating the
    # full profile of a user. This flag seems like an easy way of avoiding
    # reduntant calls to mongodb.
    # Don't use an atomic update so that the object keeps the changes.
    if save_model:
        user.photo = filename
        user.save()

    # Always clear the cache after modifying a user object.
    clear_get_user_cache(user)

    return url


def start_password_recovery_by_email(user, email, ignore_on_file=False):
    """Sends an SMS to the user containing a reset link"""
    if not ignore_on_file:
        if not user.email:
            raise APIError('Can\'t reset password because no email is set.')
        elif user.email != email:
            raise APIError('The email on file does not match given email.')

    token = AuthToken(token=random_string())
    user = update_user(user, ignore_permission=True, temp_token=token)

    # Send the reset link.
    link = 'http://recover.justyo.co/change.html?c=%s&u=%s' % (
        user.temp_token.token, user.username)
    body = 'Yo ' + user.username + ',' +\
           '\nLooks like someone requested a password reset for your ' + \
           'Yo account.' + \
           '\nIf this was you, please visit the following address ' + \
           'to recover your password:' + \
           '\n' + link + \
           '\n'
    subject = 'Yo Password recovery'
    sendgrid.send_mail(recipient=email,
                       subject=subject,
                       body=body,
                       sender=current_app.config['RECOVERY_EMAIL_FROM'])


def start_password_recovery(user):
    """Sends an SMS to the user containing a reset link"""

    if user.phone:
        # Send the reset link to the user if we have not already sent one today.
        phone_key = '%s%s' % (sms_redis_prefix, user.phone)
        recovery_attempts = redis.incr(phone_key)

        if recovery_attempts == 1:
            token = AuthToken(token=random_string())
            user = update_user(user, ignore_permission=True, temp_token=token)

            redis.expire(phone_key, 86400)

            link = 'http://recover.justyo.co/change.html?c=%s&u=%s' % (
                user.temp_token.token, user.username)
            message = 'Yo! Passcode reset: ' + link
            twilio.send(user.phone, message)
            return 'Text sent'

    if user.email:
        start_password_recovery_by_email(user, user.email)
        return 'Email sent'

    if user.phone and recovery_attempts > 1:
        raise APIError('Already sent today.')

    raise APIError('No info available for account recovery.')


def start_password_recovery_by_sms(user, number, ignore_verified=False):
    """Sends an SMS to the user containing a reset link"""

    if not user.phone or not (ignore_verified or user.verified):
        raise APIError(
            'Can\'t reset password because no number is set and verified.')
    elif user.phone != number:
        raise APIError('The number on file does not match given number.')

    # Send the reset link to the user if we have not already sent one today.
    phone_key = '%s%s' % (sms_redis_prefix, user.phone)
    recovery_attempts = 2
    try:
        recovery_attempts = redis.incr(phone_key)
    except:
        # This will throw an exception if the key is not an integer
        # from when setnx was used
        redis.set(phone_key, 2)

    if recovery_attempts == 1:
        token = AuthToken(token=random_string())
        user = update_user(user, ignore_permission=True, temp_token=token)

        redis.expire(phone_key, 86400)

        link = 'http://recover.justyo.co/change.html?c=%s&u=%s' % (
            user.temp_token.token, user.username)
        message = 'Yo! Passcode reset: ' + link
        twilio.send(user.phone, message)
        return 'Text sent'

    raise APIError('Already sent today')


def start_account_verification_by_sms(user, phone_number):
    """Sends an account verification code used in the signup process"""

    # Ensure the phone number is valid
    try:
        phone_number = clean_phone_number(phone_number)
    except NumberParseException:
        raise APIError('Invalid phone number')

    if len(set(phone_number[1:])) == 1:
        raise APIError('Invalid phone number')

    # Send the code to the user.
    random_token = str(random.randint(1111, 9999))
    message = 'Yo! Enter the code: %s' % random_token
    twilio.send(phone_number, message)

    token = AuthToken(token=random_token)
    user = update_user(user, temp_token=token, phone=phone_number,
                       verified=False)


def start_account_verification_by_reverse_sms(user):

    token = str(uuid4())
    token = token.replace('-', '')
    auth_token = AuthToken(token=token)
    update_user(user, temp_token=auth_token)

    return token

def update_user(user=None, ignore_permission=False, **kwargs):
    """Updates an existing account.

    IMPORTANT: Only wtforms data dicts should be passed to this function
    since keywords are not filtered here.
    """

    if not ignore_permission:
        assert_account_permission(user, 'No permission modify user.')

    if 'photo' in kwargs:
        b64_image = kwargs.pop('photo')

        # We only overwrite existing profile pictures in this function.
        # Clearing a profile picture requires an explicit call to
        # set_profile_picture with no payload.
        if b64_image:
            kwargs['photo'] = set_profile_picture(user, b64_image,
                                                  save_model=False)
        else:
            clear_profile_picture(user)

    if kwargs.get('photo_data'):
        image_data = kwargs.pop('photo_data')
        kwargs['photo'] = set_profile_picture(user, image_data=image_data,
                                              save_model=False)

    # Set password if it was provided.
    if 'password' in kwargs:
        password = kwargs.pop('password')
        user.set_password(password)

    # Validate url's early
    if kwargs.get('welcome_link'):
        welcome_link = kwargs.get('welcome_link')
        kwargs.update({'welcome_link': UrlHelper(welcome_link).get_url()})

    # Validate url's early
    if kwargs.get('callback'):
        callback = kwargs.get('callback')
        kwargs.update({'callback': UrlHelper(callback).get_url()})

    if 'facebook_id' in kwargs:
        clear_get_facebook_user_cache(kwargs.get('facebook_id'))

    if kwargs.get('status'):
        kwargs.update({'status_last_updated': get_usec_timestamp()})

    for key, value in kwargs.items():
        if hasattr(user, key):
            setattr(user, key, value)

    # Always clear the cache after modifying a user object.
    # NOTE: This will also save the user.
    write_through_user_cache(user)

    return user


def user_exists(username):
    """Checks if a user exists."""
    return User.objects(username=username).count() > 0


def user_id_exists(user_id):
    """Checkes that the given user id exists"""
    try:
        User.objects(id=user_id).only('id').get()
    except DoesNotExist:
        return False

    return True
