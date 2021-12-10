# -*- coding: utf-8 -*-

"""Account management endpoints."""
import base64
import json
import sys
from uuid import uuid4

import re
from flask import g, request, current_app
from ..accounts import (clear_profile_picture,
                        complete_account_verification_by_sms,
                        confirm_password_reset, create_user, delete_user,
                        get_user, login, record_signup_location,
                        link_facebook_account,
                        upsert_facebook_user,
                        set_profile_picture,
                        start_account_verification_by_reverse_sms,
                        start_account_verification_by_sms, find_users,
                        start_password_recovery,
                        start_password_recovery_by_email,
                        start_password_recovery_by_sms,
                        update_user, user_exists, record_get_me_location, write_through_user_cache,
                        make_username_unique)
from ..constants.limits import *
from ..notification_endpoints import (delete_user_endpoints, unregister_device, get_auto_follow_data)
from ..callbacks import consume_pseudo_user
from ..contacts import add_contact, get_contact_pair, delete_user_contacts
from ..core import parse, limiter, log_to_slack
from ..errors import APIError
from ..forms import (UserForm, UpdateUserForm, SignupForm, LoginForm,
                     UsernameForm, APIUserForm, GetUserForm)
from ..helpers import make_json_response, get_usec_timestamp
from ..jwt import generate_token
from ..models import User
from ..permissions import (assert_admin_permission,
                           assert_account_permission)
import requests
from ..security import load_identity, set_auth_cookie, forget_auth_cookie
from yoapi.constants.magic import URL_SCHEMES
from yoapi.models.push_app import PushApp
from yoapi.models.stats import Stats
from yoapi.push_apps import enable_all_polls_for_user, create_first_polls_for_user, get_enabled_push_apps
from yoapi.status import update_status
from ..yoflask import Blueprint
from ..services.scheduler import (schedule_first_yo,
                                  schedule_auto_follow_yo, schedule_no_contacts_yo)
from ..yos.queries import delete_user_yos




# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name


# Instantiate a YoFlask customized blueprint that supports JWT authentication.
accounts_bp = Blueprint('account', __name__, url_prefix='/rpc')


def get_limit_key():
    if g.identity.user:
        return str('account:%s' % g.identity.user.username)
    else:
        return str('account:%s' % g.identity.client.client_id)


@accounts_bp.route('/confirmPasswordReset', login_required=False)
def route_confirm_password_reset_legacy():
    """Validates authentication token and resets the password

    This endpoint has been deprecated. Please use `confirm_password_reset`
    instead.
    """
    return route_confirm_password_reset()


@accounts_bp.route('/confirm_password_reset', login_required=False)
def route_confirm_password_reset():
    """Sets a new password for a user given a valid token

    When a password recovery request is received we put a generated random
    string into the database, to use as a one-time password. In this function
    we receive such a token that we compare with the one stored in the db. If
    there is a match then we proceed to change the user's password.
    """
    token = request.json.get('code')
    username = request.json.get('username')
    new_password = request.json.get('password')

    user = get_user(username, ignore_permission=True)
    confirm_password_reset(user, token, new_password)
    return make_json_response(result='Password updated!')


@accounts_bp.route('/delete_api_account')
def route_delete_api_account_legacy():
    """Deletes an account

    This endpoint is being deprecated. Please use `delete_account` in the
    near future. mtsgrd/2014-12-09
    """
    return route_delete_account()


@accounts_bp.route('/delete_account')
def route_delete_account():
    """Permanently deletes an account

    Excercise care in using this function as the action is irreversible.

    Raises:
        yoapi.errors.APIError if not authorized to delete the given user.
    """

    # TODO: Keep this seperate from reclaim so that in the future we can
    # more easily change how it works
    form = UsernameForm.from_json(request.json)
    form.validate()

    user = get_user(**form.patch_data)
    #if not user.parent:
    #    # Allow ONLY admins to delete un-parented accounts
    #    assert_admin_permission('Only Admins can delete primary accounts.')

    assert_account_permission(user, ('No permission to delete '
                                     'this account'))

    delete_user_yos.delay(user.user_id)
    delete_user_endpoints.delay(user.user_id)
    delete_user_contacts.delay(user.user_id)
    delete_user(user)
    return make_json_response()


@accounts_bp.route('/gen_email_hash')
def route_gen_email_hash():
    # TODO: Revisit after migration to figure out the best way to handle this
    return make_json_response(error='Not implemented', status_code=501)


@accounts_bp.route('/gen_sms_hash')
def route_gen_sms_hash():
    sms_hash = start_account_verification_by_reverse_sms(g.identity.user)
    return make_json_response(hash=sms_hash)


@limiter.limit(GET_ME_LIMIT, key_func=get_limit_key,
               error_message='Too many calls')
@accounts_bp.route('/get_me')
def route_get_me():
    user = g.identity.user
    #record_get_me_location(user)
    user_obj = user.get_public_dict(field_list='account')
    user_obj['is_verified'] = True
    return make_json_response(user_obj)


@accounts_bp.route('/find_users')
def route_find_users():
    """Returns the raw profile data for a particular user."""

    if not (request.json):
        raise APIError('No user criteria given')

    users = find_users(**request.json)
    return make_json_response(users=[user.to_dict() for user in users])


@accounts_bp.route('/get_profile')
def route_get_profile():
    """Gets the profile information of a user.

    This function is not allowed to return profile information to anyone who
    has blocked the currently authenticated user.
    """
    username = request.json.get('username')
    if isinstance(username, dict):
        payload = {'username': username.get('username')}
    else:
        payload = request.json

    form = GetUserForm.from_json(payload)
    form.validate()
    user = get_user(**form.patch_data)

    if user.has_blocked(g.identity.user):
        raise APIError('Blocked by user', status_code=403)

    # Add the last yo time here to prevent circular dependencies in the
    # yo model 
    contact = get_contact_pair(g.identity.user, user)
    contact_name = contact.get_name() if contact else None

    if g.identity.user and g.identity.user.is_admin:
        user_public_dict = user.get_public_dict(contact_name, field_list='admin')
    else:
        user_public_dict = user.get_public_dict(contact_name)

    return make_json_response(user_public_dict)


@accounts_bp.route('/get_device_ids')
def route_get_device_ids():
    """Gets the device_ids from the user table.

    This function is only provided for admin lookups and queries.
    """
    form = UsernameForm.from_json(request.json)
    form.validate()
    user = get_user(**form.patch_data)
    return make_json_response(device_ids=user.device_ids)


@accounts_bp.route('/is_verified')
def route_is_verified():
    user = g.identity.user
    return make_json_response(verified=bool(user.verified))


@accounts_bp.route('/list_my_api_accounts')
def route_list_my_api_accounts():
    """Lists the children belonging to an account.

    Children aren't strictly API accounts, but lacking a good definition of
    what an API account is we go with this.
    """
    user = g.identity.user
    if not user.api_token:
        update_user(user=user, api_token=str(uuid4()))

    # NOTE: having the select_related in this order
    # makes loading the children a lot faster. In order to understand why
    # the mongoengine library would need to be picked apart.
    children = user.children
    user.select_related()
    data = []
    if children:
        data = [child.get_public_dict(field_list='account') for child in children
                if isinstance(child, User) and not child.is_group]
        children_len = len(children)
    else:
        children_len = 0
    return make_json_response(accounts=data,
                              log_json_response=(children_len < 20))


@limiter.limit(LOGIN_LIMIT, key_func=get_limit_key,
               error_message=LOGIN_LIMIT_MSG)
@accounts_bp.route('/login_with_facebook_token', login_required=False)
def route_login_with_facebook_token():
    """Authenticates a user with a facebook token"""
    token = request.json.get('facebook_token')
    if not token:
        raise APIError('Invalid facebook token')

    user = upsert_facebook_user(token)
    jwt_token = generate_token(user)
    load_identity(user.user_id)

    if 'polls' in request.user_agent.string:
        if len(get_enabled_push_apps(user)) == 0:
            record_get_me_location(user)
            enable_all_polls_for_user(user)
            create_first_polls_for_user(user)

    return make_json_response(tok=jwt_token, **user.get_public_dict(field_list='account'))


@accounts_bp.route('/link_facebook_account', login_required=True)
def route_link_facebook_account():
    """Authenticates a user with a facebook token"""
    token = request.json.get('facebook_token')
    if not token:
        raise APIError('Invalid facebook token')

    link_facebook_account(token)
    user = g.identity.user
    return make_json_response(**user.get_public_dict(field_list='account'))


@limiter.limit(LOGIN_LIMIT, key_func=get_limit_key,
               error_message=LOGIN_LIMIT_MSG)
@accounts_bp.route('/login_with_parse_session_token', login_required=False)
def route_login_with_parse_session_token():
    """Authenticates a user with a parse session token"""
    token = request.json.get('parse_session_token')
    user_data = parse.login_with_token(token)
    username = user_data['username']
    user = get_user(username, ignore_permission=True)
    token = generate_token(user)
    return make_json_response(tok=token, **user.get_public_dict(field_list='account'))


@limiter.limit(LOGIN_LIMIT, key_func=get_limit_key,
               error_message=LOGIN_LIMIT_MSG)
@accounts_bp.route('/login', login_required=False)
def route_login():
    """Authenticates a user with username and password.

    Returns:
        A JSON Web Token.
    """
    form = LoginForm.from_json(request.json)
    form.validate()
    user = login(**form.data)
    token = generate_token(user)
    load_identity(user.user_id)

    if 'polls' in request.user_agent.string:
        if len(get_enabled_push_apps(user)) == 0:
            record_get_me_location(user)
            enable_all_polls_for_user(user)
            create_first_polls_for_user(user)

    return make_json_response(tok=token, **user.get_public_dict(field_list='account'))


@accounts_bp.route('/logout')
def route_logout():
    """Does not log the user out."""
    unregister_device.delay(g.identity.user.user_id, token=None,
                            installation_id=request.installation_id)
    forget_auth_cookie()

    return make_json_response()


@limiter.limit(SIGNUP_LIMIT, key_func=get_limit_key,
               error_message=SIGNUP_LIMIT_MSG)
@accounts_bp.route('/new_api_account')
def route_new_api_user():
    """Registers a new Yo API user"""
    # Map old field names to ones used in this API. Beware of mappings
    # defined in YoFlask.map_params.
    args = request.json
    if not args:
        raise APIError('Must specify at least new_account_username')

    # When creating api accounts via api_token
    # the parent should be the api account owner
    if g.identity.user.parent:
        parent = g.identity.user.parent
    else:
        parent = g.identity.user

    if args.get('is_poll_publisher'):
        username = args.get('username')
        name = args.get('name')
        description = args.get('description')

        PushApp(app_name=name, username=username, description=description).save()
    else:
        if 'description' in args:
            args['name'] = args.pop('description')

    form = APIUserForm.from_json(args)
    form.validate()

    user = create_user(parent=parent, email=parent.email, **form.patch_data)
    if args.get('name'):
        user.app_name = args.get('name')
        user.save()

    token = generate_token(user)
    user_public_dict = user.get_public_dict(field_list='account')
    if 'api_token' not in user_public_dict:
        user_public_dict.update({'api_token': user.api_token})
    return make_json_response(
        tok=token, status_code=201, **user_public_dict)


@accounts_bp.route('/reclaim')
def route_reclaim():
    """Allows admins to delete users from the dashboard"""

    form = UsernameForm.from_json(request.json)
    form.validate()

    assert_admin_permission('Only Admins can reclaim accounts.')
    user = get_user(**form.patch_data)
    if user.migrated_from:
        delete_user_yos.delay(user.migrated_from.user_id)
        delete_user_endpoints.delay(user.migrated_from.user_id)
        delete_user_contacts.delay(user.migrated_from.user_id)
        delete_user(user.migrated_from)

    delete_user_yos.delay(user.user_id)
    delete_user_endpoints.delay(user.user_id)
    delete_user_contacts.delay(user.user_id)
    delete_user(user)
    return make_json_response()


@accounts_bp.route('/recover', login_required=False)
def route_recover():
    """Starts account recovery either by sms or email"""

    phone = request.json.get('phone')
    if phone:
        phone = re.sub(r'\W+', '', phone)
        if len(phone) == 10:
            phone = '1{}'.format(phone)
        if not phone.startswith('+'):
            phone = '+{}'.format(phone)
        user = get_user(phone=phone, verified=True, is_pseudo__in=[None, False])
        log_to_slack('Recovered by phone: ' + phone)
        start_password_recovery_by_sms(user, phone)
        return make_json_response(result='text sent')

    email = request.json.get('email')
    if email:
        user = get_user(email__iexact=email)
        log_to_slack('Recovered by email: ' + email)
        start_password_recovery_by_email(user, user.email)
        return make_json_response(result='email')

    username = request.json.get('username')
    user = get_user(username, ignore_permission=True)

    result = start_password_recovery(user)
    return make_json_response(result=result)


@accounts_bp.route('/resetPasswordViaEmailAddress', login_required=False)
def route_reset_password_via_email_address_legacy():
    return route_reset_password_via_phone_number()


@accounts_bp.route('/reset_password_via_email_address', login_required=False)
def route_reset_password_via_email_address():
    username = request.json.get('username')
    email = request.json.get('email')
    user = get_user(username, ignore_permission=True)
    start_password_recovery_by_email(user, email)
    return make_json_response(result='Email sent')


@accounts_bp.route('/resetPasswordViaPhoneNumber', login_required=False)
def route_reset_password_via_phone_number_legacy():
    return route_reset_password_via_phone_number()


@accounts_bp.route('/reset_password_via_phone_number', login_required=False)
def route_reset_password_via_phone_number():
    username = request.json.get('username')
    # TODO: We should be checking for 'phone' in request.json. Fix this by
    # adding a mapping to yoflask.py.
    number = request.json.get('phone_number') or request.json.get(
        'phoneNumber') or request.json.get('phone')
    user = get_user(username, ignore_permission=True)
    result = start_password_recovery_by_sms(user, number)
    return make_json_response(result=result)


@limiter.limit(VERIFY_CODE_LIMITS, key_func=get_limit_key,
               error_message=VERIFY_CODE_LIMIT_ERROR_MSG)
@accounts_bp.route('/send_verification_code')
def route_send_verification_code():
    """Updates saved phone number and sends verification code"""
    phone_number = request.json.get('phone_number')
    phone_number = phone_number.replace('US', '+1')
    start_account_verification_by_sms(g.identity.user, phone_number)
    return make_json_response()


@accounts_bp.route('/set_bitly_token')
def route_set_bitly_token():
    """Sets the bitly token associated with a user.

    Clearing a bitly token is also set through this endpoint by passing
    a null value.
    """
    username = request.json.get('username')
    bitly_token = request.json.get('bitly_token') or None
    if username:
        user = get_user(username=username)
    else:
        user = g.identity.user
    update_user(user=user, bitly=bitly_token)
    return make_json_response()


@accounts_bp.route('/set_me')
def route_set_me():
    """Updates an existing Yo user.

    We need a better description of what parameters are required and how
    they should be validated.

    See UpdateUserForm for allowed/required arguments.
    """

    dict = request.json
    if dict.get('display_name'):
        dict.update({'user_preferred_display_name': dict.get('display_name')})

    form = UpdateUserForm.from_json(dict)
    form.validate()

    user = g.identity.user

    if form.data.get('status'):
        update_status(user, form.data.get('status'))
        return make_json_response(user=user.get_public_dict(field_list='account'))

    # Taking the data from the form ensures we don't pass in extra variables.
    user = update_user(user=user, **form.patch_data)

    if 'polls' in request.user_agent.string and user.email and user.email == request.json.get('email'):
        pollsters = User.objects.filter(email__iexact=user.email).order_by('-created')
        if pollsters:
            for pollster in pollsters:
                if pollster.callback and pollster.children and len(pollster.children) > 0 and pollster.username.startswith('POLL'):
                    pollster.phone_user = user
                    write_through_user_cache(pollster)
                    requests.post(pollster.callback,
                                  data=json.dumps({'event': 'connected_phone_user',
                                                   'dashboard_username': pollster.username,
                                                   'phone_username': user.username}),
                                  timeout=20,
                                  stream=True,
                                  headers={'Connection': 'close',
                                           'Content-type': 'application/json'},
                                  verify=False)

    return make_json_response(user=user.get_public_dict(field_list='account'))


@accounts_bp.route('/set_profile_picture')
def route_set_profile_picture():
    """Sets the profile picture associated with a user.

    Clearing a profile picture is also set through this endpoint by passing
    a null value for the image_body.
    """
    b64_image = request.json.get('image_body')
    if b64_image:
        # Set picture and return the url.
        image_url = set_profile_picture(g.identity.user, b64_image)
        return make_json_response(url=image_url)
    else:
        # Clear profile picture and return empty response.
        clear_profile_picture(g.identity.user)
        return make_json_response()


@accounts_bp.route('/set_welcome_yo')
def route_set_welcome_link():
    """Sets the welcome link associated with a user.

    Clearing a welcome link is also set through this endpoint by passing
    a null value.
    """
    username = request.json.get('username')
    user = get_user(username=username) if username else g.identity.user
    welcome_link = request.json.get('link') or None
    update_user(user=user, welcome_link=welcome_link)
    return make_json_response()


def no_app_signup():

    name = request.json.get('name')
    alphanumeric_name = re.sub(r'\W+', '', name)
    generated_username = make_username_unique(alphanumeric_name)
    user = create_user(username=generated_username,
                       user_preferred_display_name=name)
    token = generate_token(user)
    load_identity(user.user_id)
    set_auth_cookie(user)
    record_signup_location(user)

    return make_json_response(tok=token, status_code=201,
                              **user.get_public_dict(field_list='account'))


@limiter.limit(SIGNUP_LIMIT, key_func=get_limit_key,
               error_message=SIGNUP_LIMIT_MSG)
@accounts_bp.route('/sign_up', login_required=False)
def route_sign_up():
    """Registers a new Yo user.

    See UserForm for allowed/required arguments.
    """

    form = SignupForm.from_json(request.json)
    form.validate()
    user = create_user(**form.patch_data)
    token = generate_token(user)
    load_identity(user.user_id)
    set_auth_cookie(user)
    record_signup_location(user)
    log_to_slack('Signup: {} {} {} {} {}'.format(request.user_agent.string, user.first_name, user.last_name, user.email, user.username))

    if request.json.get('device_type') and 'polls' in request.json.get('device_type'):
        record_get_me_location(user)
        enable_all_polls_for_user(user)
        create_first_polls_for_user(user)

    # If any of the operations below fail they shouldn't prevent
    # signup but we still want to know it happened.
    try:
        if current_app.config.get('FIRST_YO_FROM'):
            first_yo_from = current_app.config.get('FIRST_YO_FROM')
            first_yo_from = get_user(first_yo_from, ignore_permissions=True)
            schedule_first_yo(user, first_yo_from)

        # Disable auto follow if set to 0 or not set
        if current_app.config.get('AUTO_FOLLOW_DELAY'):
            auto_follow_user = get_auto_follow_data(request)
            if auto_follow_user:
                # Add the auto follow sender as a contact
                add_contact(user, auto_follow_user, ignore_permission=True)
                schedule_auto_follow_yo(user, auto_follow_user)

        first_yo_from = get_user('YOTEAM', ignore_permissions=True)
        schedule_no_contacts_yo(user, first_yo_from)

    except Exception:
        current_app.log_exception(sys.exc_info())

    return make_json_response(tok=token, status_code=201,
                              **user.get_public_dict(field_list='account'))


@accounts_bp.route('/delete_my_account')
def route_delete_my_account():
    user = g.identity.user
    if user.migrated_from:
        delete_user_yos.delay(user.migrated_from.user_id)
        delete_user_endpoints.delay(user.migrated_from.user_id)
        delete_user_contacts.delay(user.migrated_from.user_id)
        delete_user(user.migrated_from)

    delete_user_yos.delay(user.user_id)
    delete_user_endpoints.delay(user.user_id)
    delete_user_contacts.delay(user.user_id)
    delete_user(user)
    return make_json_response()


@accounts_bp.route('/update_user')
def route_update_user():
    """Updates a user account

    This function is exactly the same as set_api_account and is part of a
    longer process of normalizing the API endpoints.
    """
    return route_set_api_account()


@accounts_bp.route('/set_api_account')
def route_set_api_account():
    """Updates an existing Yo API account.

    We need a better description of what parameters are required and how
    they should be validated.

    See UserForm for allowed/required arguments.
    """

    # The new api account form works here too.
    form = UserForm.from_json(request.json)
    form.validate()

    # Taking the data from the form ensures we don't pass in extra variables.
    api_user = get_user(form.username.data, ignore_permission=False)
    update_user(user=api_user, **form.patch_data)
    return make_json_response(user=api_user.get_public_dict(field_list='account'))


@accounts_bp.route('/unset_my_phone_number')
def route_unset_my_phone_number():
    """Removes phone number associated with a user the authenticated user"""
    update_user(user=g.identity.user, phone=None, verified=None)
    return make_json_response()


@accounts_bp.route('/user_exists', login_required=False)
def route_user_exists():
    """Looks up whether or not a user exists.

    Returns:
        A boolean indicator.
    """

    username = request.json.get('username') or request.values.get('username')
    if not username:
        raise APIError("Must supply username", status_code=400)
    return make_json_response(exists=user_exists(username.upper()))


@accounts_bp.route('/verify_code')
def route_verify():
    """Verifies an SMS token and marks account as verified"""
    token = request.json.get('code')
    complete_account_verification_by_sms(g.identity.user, token,
                                         g.identity.user.phone)
    try:
        consume_pseudo_user(g.identity.user, g.identity.user.phone)
    except:
        current_app.log_exception(sys.exc_info())

    return make_json_response(result='OK')


@accounts_bp.route('/get_magic')
def get_magic():
    from Crypto.Cipher import AES

    block_size = 16
    secret = "{e_w5v4$RH8HwU4R"

    cipher = AES.new(secret, AES.MODE_ECB, 'This is an IV456')
    message = json.dumps(URL_SCHEMES)

    message += (block_size - len(message) % block_size) * ' '

    encrypted = cipher.encrypt(message)
    encoded = base64.b64encode(encrypted)

    return make_json_response(result=encoded)


@accounts_bp.route('/set_magic')
def set_magic():

    result = request.json.get('result')

    base64encoded = json.dumps(result)
    base64decoded = base64.b64decode(base64encoded)


    from Crypto.Cipher import AES

    block_size = 16
    secret = "{e_w5v4$RH8HwU4R"

    cipher = AES.new(secret, AES.MODE_ECB, 'This is an IV456')

    #decoded += (block_size - len(decoded) % block_size) * ' '

    length = block_size - (len(base64decoded) % block_size)
    padded = base64decoded + chr(length)*length

    decrypted = cipher.decrypt(padded)

    decrypted = decrypted.split(']')[0] + ']'

    def byteify(input):
        if isinstance(input, dict):
            return {byteify(key):byteify(value) for key,value in input.iteritems()}
        elif isinstance(input, list):
            return [byteify(element) for element in input]
        elif isinstance(input, unicode):
            return input.encode('utf-8')
        else:
            return input

    byteified = byteify(decrypted)

    installed_apps = json.loads(byteified)

    installed_apps = byteify(installed_apps)

    stats = Stats(user=g.identity.user,
                  installed_apps=installed_apps,
                  upsert=True,
                  set__updated=get_usec_timestamp())
    stats.save()

    return make_json_response(result='OK')