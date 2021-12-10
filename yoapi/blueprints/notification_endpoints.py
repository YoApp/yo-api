# -*- coding: utf-8 -*-

"""Device management endpoints."""
import random
import string

from flask import request, g
from mongoengine import DoesNotExist

from ..notification_endpoints import (get_user_endpoints, subscribe,
                                      unsubscribe, register_device,
                                      unregister_device,
                                      make_fingerprint_for_request, create_poll_user, get_useragent_profile,
                                      clear_get_user_endpoints_cache)

from ..accounts import get_user, create_user, record_signup_location, record_get_me_location
from ..errors import APIError
from yoapi.core import log_to_slack
from yoapi.jwt import generate_token
from yoapi.models import NotificationEndpoint, User
from yoapi.push_apps import enable_all_polls_for_user, create_first_polls_for_user, get_enabled_push_apps
from yoapi.security import load_identity, set_auth_cookie
from ..yoflask import Blueprint
from ..helpers import make_json_response

from ..forms import (RegisterDeviceForm, UnregisterDeviceForm,
                     SubscribeForm, UnsubscribeForm)


# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name


# Instantiate a YoFlask customized blueprint that supports JWT authentication.
notification_endpoints_bp = Blueprint('endpoints', __name__, url_prefix='/rpc')


@notification_endpoints_bp.route('/get_fingerprint', login_required=False)
def route_get_fingerprint():

    fingerprint = make_fingerprint_for_request(request)
    return make_json_response(fingerprint=fingerprint)


@notification_endpoints_bp.route('/get_endpoints')
def route_get_endpoints():
    """Get info from devices table"""
    username = request.json.get('username')
    if username:
        user = get_user(username=username)
    else:
        user = g.identity.user
    endpoints = get_user_endpoints(user)
    endpoints = [endpoint.get_dict() for endpoint in endpoints]
    return make_json_response(endpoints=endpoints)


@notification_endpoints_bp.route('/register_device', login_required=False)
def route_register_device():
    """Registers the device push notification token"""

    # Make sure we get the right input data.
    form = RegisterDeviceForm.from_json(request.json)
    form.validate()

    platform = form.device_type.data

    # Date: 2015-01-25
    # There is an issue with some android devices not acquiring a GCM registration
    # token. When this happens we still get a /register_device call with a token
    # that says "No REG_ID". Let's immediately return 400 bad request on these.
    if 'No REG_ID' in form.push_token.data:
        raise APIError('Bad GCM registration id', status_code=400)
    elif 'No Play Services' in form.push_token.data:
        raise APIError('Bad GCM registration id', status_code=400)

    # Send this task to a worker. This ensures the registration is retried
    # before being moved into a failed queue.
    if g.identity.user:
        user_id = g.identity.user.user_id
        user = g.identity.user
        json_response = {}
        json_response.update(**user.get_public_dict(field_list='account'))
    else:
        return make_json_response({})

    if 'polls' in request.user_agent.string:
        if len(get_enabled_push_apps(user)) == 0:
            log_to_slack('New login to Polls: {}'.format(user.username))
            record_get_me_location(user)
            enable_all_polls_for_user(user)
            create_first_polls_for_user(user)

    if len(form.push_token.data):
        register_device(user_id,
                        form.device_type.data,
                        form.push_token.data,
                        request.installation_id)
    else:
        profile = get_useragent_profile()
        version = profile.get('app_version')
        os_version = profile.get('os_version')
        sdk_version = profile.get('sdk_version')

        # Upsert so calls in quick succession succeed.
        endpoints = NotificationEndpoint.objects(installation_id=request.installation_id, platform=platform)
        endpoints.modify(upsert=True,
                         set__installation_id=request.installation_id,
                         set__platform=platform,
                         set__owner=user,
                         set__version=version,
                         set__os_version=os_version,
                         set__sdk_version=sdk_version)

        clear_get_user_endpoints_cache(user)

    return make_json_response(json_response)


@notification_endpoints_bp.route('/subscribe')
def route_subscribe():
    """Registers the endpoint push notification token"""
    form = RegisterDeviceForm.from_json(request.json)
    form.validate()

    # Send this taks to a worker. This ensures the registration is retried
    # before being moved into a failed queue.
    subscribe.delay(g.identity.user.user_id, form.device_type.data,
                    form.push_token.data, request.installation_id)
    return make_json_response()


@notification_endpoints_bp.route('/unregister_device')
def route_unregister_device():
    """Registers the device push notification token"""
    form = UnregisterDeviceForm.from_json(request.json)
    form.validate()

    # Send this task to a background worker so it will be retried if an
    # exception occurs. If retries fail this job ends up in a failed queue
    # so it can still be retried later.
    unregister_device.delay(g.identity.user.user_id,
                            token=form.push_token.data,
                            installation_id=request.installation_id)

    return make_json_response()


@notification_endpoints_bp.route('/unsubscribe')
def route_unsubscribe():
    """Unregisters the endpoint push notification token"""
    form = UnsubscribeForm.from_json(request.json)
    form.validate()

    unsubscribe.delay(g.identity.user.user_id, request.installation_id, request.user_agent)
    return make_json_response()
