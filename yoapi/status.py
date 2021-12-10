# -*- coding: utf-8 -*-
import hashlib

import emoji
import requests
from yoapi.accounts import update_user, get_user
from yoapi.async import async_job
from yoapi.constants.emojis import UNESCAPED_EMOJI_MAP, REVERSE_EMOJI_MAP
from yoapi.contacts import _get_follower_contacts, get_contact_pair
from yoapi.core import mixpanel_yostatus, redis, cache, log_to_slack
from yoapi.errors import APIError
from yoapi.helpers import get_usec_timestamp
from yoapi.models.status import Status
from yoapi.models.subscription import Subscription
from yoapi.notification_endpoints import get_user_endpoints
from yoapi.notifications import send_push_with_text
from yoapi.services import low_rq, redis_pubsub
from yoapi.yos.send import send_yo


@async_job(rq=low_rq)
def send_user_updated_webhooks(user):

    subscriptions = Subscription.objects(target=user)
    for subscription in subscriptions:
        try:
            params = {
                'event_type': 'status.updated',
                'user': {
                    'id': user.user_id,
                    'status': user.status,
                    'username': user.username,
                    'display_name': user.display_name,
                }
            }
            if subscription.token:
                params['token'] = subscription.token

            requests.post(url=subscription.webhook_url,
                          json=params,
                          headers={'Connection': 'close'},
                          timeout=5)
        except Exception as e:
            try:
                log_to_slack(e.message + ' : ' + str(subscription.id))
            except:
                pass


@async_job(rq=low_rq)
def send_user_updated_push_notifications(user, status, silent=False):

    followers = _get_follower_contacts(user.user_id)
    for follower in followers:

        if follower.owner.user_id == user.user_id:
            continue

        if follower.is_status_push_disabled:
            continue

        if silent:
            message = None
        else:
            name = follower.contact_name
            if name is None:
                name = user.display_name
            message = u'{} new status: {}'.format(name, status)

        endpoints = get_user_endpoints(follower.owner, 'co.justyo.yostatus', ignore_permissions=True)
        if len(endpoints):
            for endpoint in endpoints:
                if endpoint.platform.startswith('co.justyo.status.ios'):
                    send_push_with_text(endpoint=endpoint,
                                        text=message,
                                        user_info={
                                            'event_type': 'status.update',
                                            'action': 'update_yo_status',
                                            'user': {
                                                'id': user.user_id,
                                                'status': user.status,
                                                'username': user.username,
                                                'display_name': user.display_name
                                            }})
        #else:
        #    if not silent:
        #        message = u'new status {}'.format(status)
        #        send_yo(sender=user,
        #                recipients=[follower.owner],
        #                link='https://yostat.us/' + user.username,
        #                text=message,
        #                ignore_permission=True)

        #if not silent and follower.is_status_push_disabled is None:
        #    send_confirmation_push(user, follower.owner)
        #    follower.is_status_push_disabled = False  # @or: this is to send only the question only once
        #    follower.save()
        #    cache.delete_memoized(_get_follower_contacts, user.user_id)
        #    cache.delete_memoized(get_contact_pair, follower, user)


def update_status(user, status=None, status_hex=None):

    if status is None and status_hex is None:
        raise APIError('Missing status parameter')

    if status_hex:
        shortname = UNESCAPED_EMOJI_MAP.get(status_hex)
        status = REVERSE_EMOJI_MAP.get(shortname)
    else:
        if status and ':' in status:
            result = emoji.emojize(status, use_aliases=True)
            if not result:
                raise APIError(u'Unrecognized emoji: ' + result)
            else:
                status = result

    is_valid_emoji = emoji.demojize(status) != status
    if not is_valid_emoji:
        raise APIError(u'Unrecognized emoji: ' + status)

    #if status == user.status:
    #    return None

    hash_object = hashlib.sha1('@' + user.username.lower())
    hex_dig = hash_object.hexdigest()

    update_user(user=user,
                status=status,
                sha1_username=hex_dig,
                status_last_updated=get_usec_timestamp(),
                ignore_permission=True)

    status_update = Status(user=user,
                           status=status).save()

    mixpanel_yostatus.track(user.user_id, 'Updated Status')
    mixpanel_yostatus.people_set(user.user_id, {
        '$first_name': user.first_name,
        '$last_name': user.last_name,
        'display_name': user.display_name,
        'username': user.username
    })

    try:
        is_sent_recently = redis.get('did.send.update.status.push:' + user.username)
        if is_sent_recently:
            send_user_updated_push_notifications.delay(user, status, silent=True)
        else:
            send_user_updated_push_notifications.delay(user, status)
            redis.set('did.send.update.status.push:' + user.username, True, 60)

    except Exception as e:
        print e.message

    try:
        send_user_updated_webhooks.delay(user)
    except Exception as e:
        print e.message

    redis_pubsub.publish({'cmd': 'message',
                          'event_type': 'status.update',
                          'user': {
                              'id': user.user_id,
                              'status': user.status,
                              'username': user.username,
                              'display_name': user.display_name
                          }
                         },
                          channel='status.update:' + user.username.lower())

    redis_pubsub.publish({'cmd': 'message',
                          'event_type': 'status.update',
                          'user': {
                              'status': user.status,
                              'sha1_username': hex_dig,
                              'display_name': user.display_name
                          }
                         },
                          channel='status.update:' + hex_dig)

    return status_update


def send_confirmation_push(user, follower):

    text = u'Do want to get push updates for {}?'.format(user.display_name)

    user_info = {'event_type': 'status.update',  # only here to suppress in app dialog
                 'type': 'push.confirmation',
                 'owner': user.user_id,
                 'target': follower.user_id,
                 }

    category = u'👎.👍'

    endpoints = get_user_endpoints(follower, app_id='co.justyo.yostatus', ignore_permissions=True)
    for endpoint in endpoints:
        if endpoint.platform.startswith('co.justyo.status.ios'):
            if endpoint.os_version.startswith('9'):
                send_push_with_text(endpoint, text, user_info)
            elif endpoint.os_version.startswith('8'):
                yo_status = get_user(username='YOSTATUS')
                yo = send_yo(sender=yo_status,
                             sound='silent',
                             recipients=[follower],
                             text=text,
                             response_pair=category,
                             ignore_permission=True,
                             app_id='co.justyo.yostatus')

                yo.user_info = {'type': 'push.confirmation',
                                'owner': user.user_id,
                                'target': follower.user_id}
                yo.save()


def process_push_confirmation_reply(reply_sender, push_originator, did_approve):
    owner = push_originator
    target = reply_sender

    contact_pair = get_contact_pair(target, owner)

    if did_approve:
        text = 'Awesome! you will keep getting push updates about {}'.format(owner.display_name)
        is_status_push_disabled = False
    else:
        text = 'Cool! you won\'t be getting push updates about {}'.format(owner.display_name)
        is_status_push_disabled = True

    contact_pair.is_status_push_disabled = is_status_push_disabled
    contact_pair.save()
    cache.delete_memoized(_get_follower_contacts, owner.user_id)
    cache.delete_memoized(get_contact_pair, target, owner)

    endpoints = get_user_endpoints(reply_sender, 'co.justyo.yostatus', ignore_permissions=True)
    for endpoint in endpoints:
        send_push_with_text(endpoint=endpoint,
                            text=text,
                            category='')