# -*- coding: utf-8 -*-

"""Administrative API endpoints"""

# pylint: disable=invalid-name

from flask import request, g

from ..accounts import (get_user, start_password_recovery_by_sms,
                        start_password_recovery_by_email, find_users,
                        clear_get_user_cache, clear_get_facebook_user_cache)
from ..contacts import (clear_get_contacts_cache,
                        clear_get_contacts_last_yo_cache,
                        clear_get_followers_cache)
from ..errors import APIError
from ..forms import GetUserForm, FindUserForm
from ..helpers import make_json_response
from ..permissions import assert_admin_permission
from ..notification_endpoints import clear_get_user_endpoints_cache
from yoapi.constants.yos import UNREAD_YOS_FETCH_LIMIT
from ..yoflask import Blueprint

from ..yos.queries import get_yos_sent, clear_get_unread_yos_cache

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/recover')
def route_recover():
    """Starts account recovery either by sms or email
        Use the email from the request if provided
    """

    assert_admin_permission('Unauthorized')

    user_id = request.json.get('user_id')
    email = request.json.get('email')
    phone = request.json.get('phone')

    if not user_id:
        raise APIError('Must specify user_id')

    user = get_user(user_id=user_id)

    # Use the provided phone regardless of whether or not its on file
    if phone:
        start_password_recovery_by_sms(user, phone, ignore_verified=True)
        return make_json_response(result='Text sent')

    # Use the provided email regardless of whether or not its on file
    if email:
        start_password_recovery_by_email(user, email, ignore_on_file=True)
        return make_json_response(result='Email sent')

    # Otherwise, raise an error informing the client that recovery cannot be
    # initiated.
    raise APIError('No info provided for account recovery.')


@admin_bp.route('/get_profile')
def route_admin_get_profile():
    """Allows admins to retreive profiles"""

    assert_admin_permission('Unauthorized')

    # Remove the admin api_token to prevent improper lookups
    api_token = request.json.get('api_token')
    if api_token and api_token == g.identity.user.api_token:
        api_token = request.json.pop('api_token')

    form = GetUserForm.from_json(request.json)
    form.validate()
    user = get_user(**form.patch_data)

    # Add the last yo time here to prevent circular dependencies in the
    # yo model.
    user_public_dict = user.get_public_dict(field_list='admin')
    user_public_dict.update({'device_ids': user.device_ids})

    return make_json_response(user_public_dict)


@admin_bp.route('/find_users')
def route_admin_find_users():
    """Allows admins to retreive profiles"""

    assert_admin_permission('Unauthorized')

    # Remove the admin api_token to prevent improper lookups
    api_token = request.json.get('api_token')
    if api_token and api_token == g.identity.user.api_token:
        api_token = request.json.pop('api_token')

    form = FindUserForm.from_json(request.json)
    form.validate()
    has_valid_query = False
    for _, val in form.patch_data.items():
        if val:
            has_valid_query = True
            break

    if not has_valid_query:
        raise APIError('Expected one of the following fields to be present: '
                       'username, username__startswith, username__endswith, '
                       'username__contains, device_ids, user_id, parse_id, '
                       'api_token, phone, email')

    if 'user_id' in form.patch_data:
        user_id = form.patch_data.pop('user_id')
        users = find_users(id=user_id, **form.patch_data)
    else:
        users = find_users(**form.patch_data)

    # Add the last yo time here to prevent circular dependencies in the
    # yo model
    results = []
    for user in users:
        user_public_dict = user.get_public_dict(field_list='admin')
        last_yos = get_yos_sent(user)
        if last_yos:
            last_yo = last_yos[0]
            user_public_dict.update({'last_yo_time': last_yo.created})
        else:
            user_public_dict.update({'last_yo_time': None})

        results.append(user_public_dict)

    return make_json_response(results=results)

@admin_bp.route('/clear_cache')
def route_admin_clear_cache():
    """Allows admins to clear user's cache"""

    assert_admin_permission('Unauthorized')

    usernames = request.json.get('usernames', [])
    username = request.json.get('username')
    user_ids = request.json.get('user_ids', [])
    user_id = request.json.get('user_id')

    if not isinstance(usernames, list):
        usernames = []

    if username and username not in usernames:
        usernames.append(username)

    if not isinstance(user_ids, list):
        user_ids = []

    if user_id and user_id not in user_ids:
        user_ids.append(user_id)

    def _clear_cache(user_obj):
        clear_get_user_cache(user_obj)

        if request.json.get('clear_contacts'):
            clear_get_contacts_cache(user_obj)
            clear_get_contacts_last_yo_cache(user_obj)

        if request.json.get('clear_followers'):
            clear_get_followers_cache(user_obj)

        if request.json.get('clear_yo_inbox'):
            clear_get_unread_yos_cache(user_obj.user_id, UNREAD_YOS_FETCH_LIMIT)

        if request.json.get('clear_endpoints'):
            clear_get_user_endpoints_cache(user_obj)

    failures = []
    for username in usernames:
        try:
            user = get_user(username=username)
        except APIError:
            failures.append(username)
            continue
        _clear_cache(user)

    for user_id in user_ids:
        try:
            user = get_user(user_id=user_id)
        except APIError:
            failures.append(user_id)
            continue
        _clear_cache(user)

    if request.json.get('facebook_id'):
        clear_get_facebook_user_cache(request.json.get('facebook_id'))

    return make_json_response(failures=failures)
