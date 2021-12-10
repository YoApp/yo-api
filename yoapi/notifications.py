# -*- coding: utf-8 -*-

"""Notification sending package."""
import json
import sys
from uuid import uuid4

from flask import g, current_app
from boto.exception import BotoServerError
from twilio.rest.exceptions import TwilioRestException
from .accounts import get_user
from .async import async_job
from .contacts import get_contact_pair
from .core import sns, twilio, log_to_slack, redis
from .notification_endpoints import get_user_endpoints, IOS, IOSBETA
from .services import low_rq, medium_rq
from .models.payload import Payload
from yoapi.models.notification_endpoint import IOSDEV


@async_job(rq=low_rq)
def _push_to_endpoint(endpoint_arn=None, sns_message=None,
                      phone=None, message=None, media_url=None):
    """Pushes a single Yo to a single endpoint or sms.
    This is done individually so that failures are retried at
    the endpoint level"""

    if endpoint_arn and sns_message:
        try:
            sns.set_endpoint_attributes(endpoint_arn, {'Enabled': True})
            sns.publish(target_arn=endpoint_arn, message=sns_message)
        except BotoServerError as err:
            log_to_slack('Exception: ' + endpoint_arn + ' - ' + err.message)
            if err.code in sns.REMOVE_ON_FAILURE_TYPES:
                log_to_slack('Endpoint signaled to be removed: {} {}'.format(err.message, endpoint_arn))
                #remove_disabled_endpoint(endpoint_arn)

                return 'Endpoint removed: %s' % err.message

            return err.message

    # Most of the time this will only fail if the person has replied STOP
    # so don't retry these sms's.
    if phone and message:
        try:

            if redis.get('yo:' + phone) is None:
                redis.set('yo:' + phone, 60*60*24*356)
                twilio.send(phone, message, media_url)
            else:
                pass
                #log_to_slack('Cancelled SMS to {}: {}'.format(phone, message))

        except TwilioRestException as err:
            error = 'Could not send message to %s. code %s. message %s'
            return error % (phone, err.code, message)


def _send_notification_to_user(user, payload, app_id=None):
    # Send a payload to a particular user's endpoints if the endpoint
    # is supported by the payload

    if app_id:
        endpoints = get_user_endpoints(user=user, app_id=app_id, ignore_permissions=True)
    else:
        endpoints = get_user_endpoints(user, ignore_permissions=True)

    for endpoint in endpoints:
        if (payload.requires_invisible_push() and
                not endpoint.handles_invisible_push):
            continue

        if payload.requires_any_text() and not endpoint.handles_any_text:
            continue

        if not payload.should_send_to_legacy() and endpoint.is_legacy:
            continue

        if not payload.supports_platform(endpoint.platform):
            continue

        if not payload.supports_version(endpoint.version):
            continue

        _push_to_endpoint.delay(endpoint.arn,
                                sns_message=payload.to_sns(endpoint))


@async_job(rq=low_rq)
def _send_action_to_user(user_id, data_dict):
    user = get_user(user_id=user_id)
    if 'category' not in data_dict:
        data_dict.update({'category': 'ACTION'})
    if 'action' not in data_dict:
        data_dict.update({'action': 'default'})
    payload = Payload(None, None, **data_dict)
    payload.must_handle_invisible_push = True
    _send_notification_to_user(user, payload)


def notify_yo_status_update(yo):
    update_data = yo.get_status_dict(user=yo.sender)
    if not update_data:
        return
    update_data.update({'action': 'update_yo_status'})

    flattened_yo = yo.get_flattened_yo()
    _send_action_to_user.delay(flattened_yo.sender.user_id, update_data)


@async_job(rq=low_rq)
def _send_notification_to_users(user_ids, payload_support,
                                payload_args, payload_kwargs):
    users = [get_user(user_id=user_id) for user_id in user_ids]
    payload = Payload(*payload_args, **payload_kwargs)
    for item in payload_support:
        if hasattr(payload, item[0]):
            setattr(payload, item[0], item[1])

    for user in users:
        _send_notification_to_user(user, payload)


@async_job(rq=low_rq)
def announce_sign_up_to_contacts(contact_ids, is_yostatus):
    # Sends contacts a notification that their friend has joined yo

    user = g.identity.user

    params = (user.first_name, user.last_name)
    if is_yostatus:
        push_text = (u'\U0001f38a\U0001f389\U0001f38a\U0001f389 '
                     u'%s %s joined Yo Status! \U0001f38a\U0001f389\U0001f38a\U0001f389') % params
    else:
        push_text = (u'\U0001f38a\U0001f389\U0001f38a\U0001f389 '
                     u'%s %s joined Yo! \U0001f38a\U0001f389\U0001f38a\U0001f389') % params

    announcement_payload = Payload(push_text, None, sender=user.username,
                                   action='just_joined')

    # Disable sending to legacy devices.
    announcement_payload.legacy_enabled = False
    announcement_payload.must_handle_any_text = True

    # Disable sending to Android.
    announcement_payload.supported_platforms = [IOS, IOSBETA, IOSDEV]

    # Restrict these announcments to version 2.0.3 or better.
    announcement_payload.version_support = '>=2.0.3'

    for contact_id in contact_ids:
        friend = get_user(user_id=contact_id, ignore_permission=True)
        already_contact = bool(get_contact_pair(friend, user))
        user_blocked = friend.has_blocked(user)
        user_blocked = user_blocked or user.has_blocked(friend)

        if not (already_contact or user_blocked):
            if is_yostatus:
                _send_notification_to_user(friend, announcement_payload, 'co.justyo.yostatus')
            else:
                _send_notification_to_user(friend, announcement_payload)


@async_job(rq=low_rq)
def send_silent_yo_opened(yo):
    return

    '''flattened_yo = yo.get_flattened_yo()
    yo_sender = flattened_yo.sender

    key = 'sent.viewed.yo' + ':' + yo_sender.username
    if redis.get(key):
        return

    redis.set(key, True, 60)

    if yo.recipient.first_name:
        recipient = flattened_yo.recipient.first_name
    else:
        recipient = flattened_yo.recipient.username

    payload_type = YoPayload.get_yo_payload_type(flattened_yo,
                                                 use_full_support=True)
    if payload_type == YoPayloadConst.GIF_YO:
        action_text = 'just viewed your gif'
    elif payload_type == YoPayloadConst.PHOTO_YO:
        action_text = 'just viewed your photo'
    elif payload_type == YoPayloadConst.LOCATION_YO:
        action_text = 'just viewed your location'
    elif payload_type in YoPayloadConst.LINK_YO_TYPES:
        action_text = 'just opened your link'
    else:
        action_text = 'just opened your Yo'

    params = (recipient, action_text)
    push_text = u'%s %s \U0001f440' % params

    announcement_payload = Payload(push_text, None, sender=yo.recipient.username,
                                   action='just_opened')

    # Disable sending to legacy devices.
    announcement_payload.legacy_enabled = False
    announcement_payload.must_handle_any_text = True

    # Disable sending to Android.
    announcement_payload.supported_platforms = [IOS, IOSBETA]

    # Restrict these announcments to version 2.0.3 or better.
    announcement_payload.version_support = '>=2.0.3'

    _send_notification_to_user(yo_sender, announcement_payload)
    '''


def send_command(endpoint, command, args, context):
    command_payload = {
        'id': uuid4().hex,
        'command': command,
        'context': context,
        'args': args
    }

    apns_payload = {
        'aps': {
            'content-available': '1',
        }
    }

    apns_payload.update(command_payload)

    sns_payload = {
        'default': '',
    }

    if endpoint.platform in [IOSBETA, IOS] or 'polls' in endpoint.platform and 'prod' in endpoint.platform:
        sns_payload['apns'] = json.dumps(apns_payload)
    elif endpoint.platform in [IOSDEV] or 'polls' in endpoint.platform and 'dev' in endpoint.platform:
        sns_payload['apns_sandbox'] = json.dumps(apns_payload)

    _push_to_endpoint(endpoint.arn, sns_message=json.dumps(sns_payload))


def send_clear_notifications(endpoint):

    apns_payload = {
        'aps': {
            'content-available': '1',
        }
    }

    sns_payload = {
        'default': '',
    }

    if endpoint.platform in [IOSBETA, IOS] or 'polls' in endpoint.platform and 'prod' in endpoint.platform:
        sns_payload['apns'] = json.dumps(apns_payload)
    elif endpoint.platform in [IOSDEV] or 'polls' in endpoint.platform and 'dev' in endpoint.platform:
        sns_payload['apns_sandbox'] = json.dumps(apns_payload)

    _push_to_endpoint(endpoint.arn, sns_message=json.dumps(sns_payload))


def send_command_add_response(endpoint, yo):
    try:

        response_pair = yo.response_pair

        right_title = response_pair.split('.')[1]
        left_title = response_pair.split('.')[0]

        left_is_background = True if yo.left_link is None else False
        right_is_background = True if yo.right_link is None else False

        send_command(endpoint=endpoint,
                     command='add_response',
                     args=[
                         {
                             'identifier': response_pair,
                             'actions': [
                                 {
                                     'title': right_title,
                                     'identifier': right_title,
                                     'is_background': right_is_background,
                                     'is_destructive': False
                                 },
                                 {
                                     'title': left_title,
                                     'identifier': left_title,
                                     'is_background': left_is_background,
                                     'is_destructive': False
                                 }
                             ]
                         }
                     ],
                     context={
                         'yo_id': yo.yo_id
                     })
    except:
        current_app.log_exception(sys.exc_info())


def send_push_to_user(user, app_id, text):

    sound = 'yo.mp3'
    if app_id == 'co.justyo.yostatus':
        sound = 'status.mp3'

    endpoints = get_user_endpoints(user, app_id, ignore_permissions=True)
    for endpoint in endpoints:
        send_push_with_text(endpoint, text, category='', sound=sound)


def send_push_with_text(endpoint, text, user_info={}, category='reply', sound=''):

    sns_payload = {
        'default': text,
    }

    if 'ios' in endpoint.platform:
        apns_payload = {
            'aps': {
                'content-available': '1',
                'sound': sound,
                'category': category
            }
        }

        if text:
            apns_payload['aps']['alert'] = text

        apns_payload.update(user_info)

        if 'dev' in endpoint.platform:
            sns_payload['apns_sandbox'] = json.dumps(apns_payload)
        else:
            sns_payload['apns'] = json.dumps(apns_payload)

    elif 'android' in endpoint.platform:

        if text:

            payload = {
                'data': {
                    'message': text
                }
            }

            sns_payload['gcm'] = json.dumps(payload)

    _push_to_endpoint(endpoint.arn, sns_message=json.dumps(sns_payload))
