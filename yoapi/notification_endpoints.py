# -*- coding: utf-8 -*-

"""Device management package."""

import hashlib
import random
import string
import sys
from urllib2 import URLError
from uuid import uuid4

from flask import current_app, request, json
from mongoengine import DoesNotExist, Q, MultipleObjectsReturned
from boto.exception import BotoServerError
from parse_rest.core import ParseError
from .accounts import get_user, create_user, record_get_me_location
from .async import async_job
from .errors import APIError
from .permissions import assert_account_permission
from .core import parse, sns, redis
from .models import Device, NotificationEndpoint, User
from .services import low_rq
from .constants.regex import ANDROID_RE, IOS_RE, WINPHONE_RE


# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name
from yoapi.constants.sns import APP_ID_TO_ARN_IDS
from yoapi.models.notification_endpoint import IOSDEV
from yoapi.push_apps import enable_all_polls_for_user, create_first_polls_for_user

WINPHONE = 'winphone'
ANDROID = 'android'
IOS = 'ios'
IOSBETA = 'ios-beta'
FLASHPOLLSBETADEV = 'com.flashpolls.beta.dev'
FLASHPOLLSBETAPROD = 'com.flashpolls.beta.prod'
FLASHPOLLSDEV = 'com.flashpolls.flashpolls.dev'
FLASHPOLLSPROD = 'com.flashpolls.flashpolls.prod'
FLASHPOLLSBETA = 'com.flashpolls.beta'  # for old beta prod


def clear_get_user_endpoints_cache(user):
    pass
    #cache.delete_memoized(_get_user_endpoints, user.user_id)


@async_job(rq=low_rq)
def delete_user_endpoints(user):
    if isinstance(user, User):
        user_id = user.user_id
    else:
        user_id = user

    devices = Device.objects(owner=user_id)
    for device in devices:
        parse.unsubscribe(None, device.token)

    devices.update(unset__owner=True)

    endpoints = NotificationEndpoint.objects(owner=user_id)
    endpoints.update(unset__owner=True)

    clear_get_user_endpoints_cache(user)


def get_user_endpoints(user, app_id=None, ignore_permissions=False):
    """Returns the user endpoints"""

    if not ignore_permissions:
        assert_account_permission(user, 'No permission to access user.')
    return _get_user_endpoints(user.user_id, app_id)


#@cache.memoize()
def _get_user_endpoints(user_id, app_id=None):
    if app_id:
        sns_app_ids = APP_ID_TO_ARN_IDS[app_id]
        endpoints = NotificationEndpoint.objects(owner=user_id, platform__in=sns_app_ids)
    else:
        endpoints = NotificationEndpoint.objects(owner=user_id)
    return list(endpoints)


@async_job(rq=low_rq)
def register_device(user_id, device_type, token, installation_id):
    """Registers a new device for the specified user

    Args:
        owner: The device owner username.
        device_type: Device type, such as ios, android, winphone.
        token: The register id or apns token.

    """
    # Restore the user since we pass in user_id's to async functions.
    user = get_user(user_id=user_id)
    assert_account_permission(user, 'No permission modify user.')

    # Prevent empty string installation id
    installation_id = installation_id if installation_id else None

    # Register ios and windows devices to SNS
    profile = get_useragent_profile()
    version = profile.get('app_version')
    endpoint_sns_enabled = sns_enabled_for(device_type, version)
    if installation_id is None:
        installation_id = str(uuid4())
    if endpoint_sns_enabled and installation_id:
        subscribe(user_id, device_type, token, installation_id)
        return

    # Devices should be deleted when a user logs out since the endpoint maps
    # an app instance to a phone. As a precaution, delete any device already
    # registered under given token. The reverse_delete rule for a User pulls
    # it from the devices list.
    if installation_id:
        Device.objects(installation_id=installation_id).delete()
    Device.objects(token=token).delete()

    # Create new device.
    device = Device(token=token, owner=user, device_type=device_type,
                    installation_id=installation_id)
    device.save()
    clear_get_user_endpoints_cache(user)

    # TODO: this is a bug fix related to iOS not using the parse SDK for
    # subscribing and unsubscribing. There are also cases where this is
    # called multiple times in quick succession causing duplication errors.
    # This can also fail if parse is down or has an error and in those
    # cases, we need to be notified via email
    if not (endpoint_sns_enabled or device_type in (ANDROID, WINPHONE)):
        parse.subscribe(user, device_type, token)


def sns_enabled_for(platform, version):
    if platform == ANDROID:
        return version >= '111064067'
    if platform == IOSBETA:
        return True
    if platform == IOS:
        return True
    if platform == IOSDEV:
        return True
    if platform == WINPHONE:
        return True
    if platform and 'polls' in platform:
        return True
    if platform and 'status' in platform:
        return True
    if platform and 'ios' in platform:
        return True
    return False


def endpoint_from_useragent(req):
    profile = get_useragent_profile(req)
    version = profile.get('app_version')
    os_version = profile.get('os_version')
    sdk_version = profile.get('sdk_version')
    platform = profile.get('platform')

    return NotificationEndpoint(platform=platform, version=version,
                                os_version=os_version, sdk_version=sdk_version)

def endpoint_support_from_useragent(req):
    profile = get_useragent_profile(req)
    version = profile.get('app_version')
    os_version = profile.get('os_version')
    sdk_version = profile.get('sdk_version')
    platform = profile.get('platform')

    endpoint = NotificationEndpoint(platform=platform, version=version,
                                    os_version=os_version,
                                    sdk_version=sdk_version)
    return endpoint.get_payload_support_dict()

def get_auto_follow_data(req):
    fingerprint = make_fingerprint_for_request(req)
    data = redis.get(fingerprint)
    if not data:
        return None

    redis.delete(fingerprint)
    try:
        data_object = json.loads(data)
        username = data_object.get('username')
        source = data_object.get('source')
    except ValueError:
        """If the data isn't stored as json its probably legacy
        from justyo.co."""
        username = data
        source = 'justyo'

    try:
        user = get_user(username=username, ignore_permission=True)
        current_app.logger.info({'Event': 'AutoFollow', 'source': source,
                                 'username': username})
        return user
    except APIError:
        return None


def make_fingerprint_for_request(req):
    os_name_map = {'ios': 'iOS', 'android': 'Linux', 'winphone': 'iOS'}

    profile = get_useragent_profile(req)
    os_name = profile.get('platform')
    os_version = profile.get('os_version')
    if not (os_name or os_version):
        return None

    # For some reason the user agent parser thinks all windows phones
    # are using iOS v 7.0.3
    if os_name == WINPHONE:
        os_version = '7.0.3'

    os_name = os_name_map.get(os_name)
    fingerprint = '%s;%s;%s' % (req.remote_addr, os_name, os_version)
    return hashlib.sha224(fingerprint).hexdigest()


def get_useragent_profile(req=None):
    """Returns the endpoint platform and version from the useragent"""
    req = req if req else request
    ua_str = str(req.user_agent)

    android_match = ANDROID_RE.match(ua_str)
    if android_match:
        return {
            'is_beta': android_match.group(1) == 'YoBeta',
            'app_version': android_match.group(2),
            'device_name': android_match.group(3),
            'sdk_version': android_match.group(4),
            'os_version': android_match.group(5),
            'platform': ANDROID
        }

    ios_match = IOS_RE.match(ua_str)
    if ios_match:
        return {
            'is_beta': ios_match.group(1) == 'YoBeta',
            'app_version': ios_match.group(2),
            'device_name': ios_match.group(3),
            'os_version': ios_match.group(4),
            'platform': IOSBETA if ios_match.group(1) == 'YoBeta' else IOS
        }

    winphone_match = WINPHONE_RE.match(ua_str)
    # Previous builds of windown phone send the ua NativeHost
    if winphone_match or ua_str == 'NativeHost':
        if winphone_match:
            return {
                'is_beta': winphone_match.group(1) == 'YoBeta',
                'app_version': winphone_match.group(2),
                'device_name': winphone_match.group(3),
                'os_version': winphone_match.group(4),
                'platform': WINPHONE
            }
        else:
            return {
                'is_beta': False,
                'app_version': None,
                'device_name': None,
                'os_version': None,
                'platform': WINPHONE
            }

    # If we can't determine what this is, it is probably best to mark it
    # is_beta=False in case this is an old android.
    return {
        'is_beta': False,
        'app_version': None,
        'device_name': None,
        'os_version': None,
        'platform': None
    }


class PlatformMismatchError(Exception):
    """Error raised when a device tries to register an exiting token
    for a different platform"""
    pass

@async_job(rq=low_rq)
def subscribe(user_id, platform, token, installation_id):
    """Registers a new endpoint for the specified user

    Args:
        owner: The device owner username.
        platform: Device type, such as ios, android, winphone.
        token: The register id or apns token.
    """

    # Verify valid installation_id
    if not (installation_id or platform == WINPHONE):
        raise APIError('No installation id provided.')

    user = get_user(user_id=user_id)

    # If the token is in the device table, it needs to be removed
    # from parse
    devices = Device.objects(token=token).all()
    if devices:
        # Delete the device so that we don't have to do this again
        devices.delete()
        try:
            parse.unsubscribe(user, token)
        except (ParseError, URLError):
            current_app.log_exception(sys.exc_info())

    # If an endpoint already exists for the given token we simply
    # update the owner.
    # create_endpoint is only idempotent if the attributes are the same.
    # This includes the disabled attribute. Because of this, set the endpoint
    # attributes to make sure this token is now active. ref: goo.gl/NH8jmI
    # Whenever deleting endpoints from the database, also delete them
    # from sns. If the platform does not match, re-create the endpoint
    # to prevent ios-beta/ios push discrepencies.
    # If a BotoServerError is thrown we assume the arn was removed from
    # sns but not our database. (fixed in df41d28)
    arn = None
    endpoints = NotificationEndpoint.objects(
        (Q(installation_id=installation_id) & Q(platform=platform)) | Q(token=token))
    try:
        endpoint = endpoints.get()
        if endpoint.platform != platform:
            raise PlatformMismatchError()

        sns.set_endpoint(endpoint.arn, {'Token': token, 'Enabled': True})
        arn = endpoint.arn
    except (MultipleObjectsReturned, PlatformMismatchError, BotoServerError):
        # In case there are multiples delete all.
        for endpoint in endpoints:
            sns.delete_endpoint(endpoint_arn=endpoint.arn)
        endpoints.delete()
    except DoesNotExist:
        pass

    arn = arn or sns.create_endpoint(platform, token)

    profile = get_useragent_profile()
    version = profile.get('app_version')
    os_version = profile.get('os_version')
    sdk_version = profile.get('sdk_version')

    # Upsert so calls in quick succession succeed.
    endpoints.modify(upsert=True,
                     set__token=token,
                     set__installation_id=installation_id,
                     set__platform=platform,
                     set__owner=user,
                     set__arn=arn,
                     set__version=version,
                     set__os_version=os_version,
                     set__sdk_version=sdk_version)

    clear_get_user_endpoints_cache(user)


def _subscribe_endpoint_to_topic(endpoint, topic_arn):
    """Subscribes an endpoint to a topic

    In addition to subscribing an endpoint to a topic, we also use this
    function to enforce a restriction of one subscription per device. This
    rule is subject to change in the future.

    Note that this function alters only the in memory state of an endpoint
    object without saving it to the database.
    """
    _unsubscribe_subscriptions(endpoint.subscriptions)
    try:
        subscription_arn = sns.subscribe(topic_arn, endpoint.arn)
        subscription = Subscription.objects(arn=subscription_arn).modify(
            upsert=True,
            new=True,
            set__topic_arn=topic_arn,
            set__endpoint_arn=endpoint.arn)
        endpoint.subscriptions = [subscription]
    except BotoServerError:
        message = 'Subscribing invalid topic arn %s. Username: %s. ' + \
                  'Endpoint.arn: %s. Device token: %s.'
        message = message % (topic_arn, endpoint.owner.username,
                             endpoint.arn, endpoint.token)
        current_app.log_exception(sys.exc_info())

@async_job(rq=low_rq)
def unregister_device(user_id, token=None, installation_id=None):
    """Registers a new device for the specified user."""
    # Restore the user since we pass in user_id's to async functions.
    user = get_user(user_id=user_id)
    assert_account_permission(user, 'No permission modify user.')

    profile = get_useragent_profile()
    platform = profile.get('platform')
    version = profile.get('app_version')
    endpoint_sns_enabled = sns_enabled_for(platform, version)
    if endpoint_sns_enabled and installation_id:
        unsubscribe(user_id, installation_id, request.user_agent)
        return

    if installation_id:
        device = Device.objects(installation_id=installation_id)
        device = device.modify(unset__owner=True, new=True)

    if token:
        device = Device.objects(token=token)
        device = device.modify(unset__owner=True, new=True)

    clear_get_user_endpoints_cache(user)

    # TODO: this is a bug fix related to iOS not using the parse SDK for
    # subscribing and unsubscribing. We're enclosing this in a try statement
    # to avoid negative side effects while investigating the issue further.
    if not endpoint_sns_enabled and device:
        parse.unsubscribe(user, device.token)


@async_job(rq=low_rq)
def unsubscribe(user_id, installation_id, user_agent):
    """Unregisters a endpoint for the specified user."""

    user = get_user(user_id=user_id)
    assert_account_permission(user, 'No permission modify user.')

    profile = get_useragent_profile()
    platform = profile.get('platform')

    try:
        endpoint = NotificationEndpoint.objects(installation_id=installation_id,
                                                platform=platform).get()
        if endpoint:
            endpoint.update(unset__owner=True)
            clear_get_user_endpoints_cache(user)
    except DoesNotExist:
        pass


def _unsubscribe_subscriptions(subscriptions):
    """Unsubscribes subscriptions"""
    if subscriptions:
        for subscription in subscriptions:
            sns.unsubscribe(subscription.arn)
            subscription.delete()


def create_poll_user():
    suffix = ''.join(random.choice(string.digits) for _ in range(6))
    generated_username = 'GUEST' + suffix
    user = create_user(username=generated_username,
                       is_guest=True)
    record_get_me_location(user)
    enable_all_polls_for_user(user)
    create_first_polls_for_user(user)
    return user