# -*- coding: utf-8 -*-

"""Yo helpers package."""

import datetime
import json
import sys
import grequests

import requests
from flask import current_app, g, request
from mongoengine import DoesNotExist
from requests.exceptions import RequestException, Timeout
from .queries import (clear_get_favorite_yos_cache,
                      clear_get_unread_yos_cache,
                      clear_get_yo_count_cache, clear_get_yo_cache,
                      clear_get_yo_token_cache,
                      get_last_broadcast, get_yo_by_id, get_public_dict_for_yo_id)
from ..ab_test import log_ab_test_data
from ..async import async_job
from ..core import s3, mixpanel_yoapp, log_to_slack, sendgrid
from ..errors import (APIError, YoTokenExpiredError, YoTokenInvalidError,
                      YoTokenUsedError)
from ..headers import get_header_by_id, get_header
from ..helpers import get_usec_timestamp
from ..models import Yo
from ..notification_endpoints import endpoint_support_from_useragent
from ..notifications import notify_yo_status_update, send_silent_yo_opened
from ..permissions import assert_account_permission
from ..services import low_rq, redis_pubsub
from ..urltools import UrlHelper
from ..models.payload import YoPayload
from yoapi.accounts import _get_user
from yoapi.constants.yos import UNREAD_YOS_FETCH_LIMIT
from yoapi.contacts import get_contact_pair
from yoapi.groups import get_group_members
from yoapi.localization import get_region_by_name


YO_BUFFER_MAX = 10000


@async_job(rq=low_rq)
def acknowledge_yo_received(yo_id, status=None, from_push=False):
    """Acknowledges a Yo with the specified status.
    status: One of - received (default), read, dismissed.
    from_push: Was this triggered by interacting with a notification?
    """

    try:
        yo = get_yo_by_id(yo_id)
    except DoesNotExist:
        raise APIError('Yo not found')

    if yo.app_id == 'co.justyo.yopolls':
        clear_get_unread_yos_cache(yo.recipient.user_id, UNREAD_YOS_FETCH_LIMIT, app_id='co.justyo.yopolls')

    status = status or 'received'
    # TODO: Find a nicer way to do this. Perhaps with a permission assert.
    is_current_users_yo = yo.recipient and yo.recipient == g.identity.user
    current_priority = Yo.priority_for_status(yo.status)
    new_priority = Yo.priority_for_status(status)
    needs_update = new_priority > current_priority
    if is_current_users_yo and needs_update:

        if yo.sender and yo.recipient:

            if status == 'received':

                if yo.parent and yo.parent.sender.is_service or yo.sender.is_service:
                    mixpanel_yoapp.track(yo.recipient.user_id, 'News Yo Received')
                else:
                    mixpanel_yoapp.track(yo.recipient.user_id, 'Friend Yo Received')

                contact_object = get_contact_pair(yo.sender, yo.recipient)
                if contact_object:
                    contact_object.last_yo_state = 'Friend received'
                    contact_object.last_yo = get_usec_timestamp()
                    contact_object.save()

                contact_object = get_contact_pair(yo.recipient, yo.sender)
                if contact_object:
                    contact_object.last_yo_state = 'You received'
                    contact_object.last_yo = get_usec_timestamp()
                    contact_object.save()

            elif status == 'read':

                try:
                    if yo.parent and yo.parent.sender.is_service or yo.sender.is_service:
                        mixpanel_yoapp.track(yo.recipient.user_id, 'News Yo Opened')
                    else:
                        mixpanel_yoapp.track(yo.recipient.user_id, 'Friend Yo Opened')
                except:
                    pass

                contact_object = get_contact_pair(yo.sender, yo.recipient)
                if contact_object:
                    contact_object.last_yo_state = 'Friend opened'
                    contact_object.last_yo = get_usec_timestamp()
                    contact_object.save()

                contact_object = get_contact_pair(yo.recipient, yo.sender)
                if contact_object:
                    contact_object.last_yo_state = 'You opened'
                    contact_object.last_yo = get_usec_timestamp()
                    contact_object.save()

        yo.status = status
        yo.save()
        clear_get_yo_cache(yo_id)
        clear_get_unread_yos_cache(str(yo.recipient), UNREAD_YOS_FETCH_LIMIT)

        flattened_yo = yo.get_flattened_yo()
        support_dict = endpoint_support_from_useragent(request)
        payload = YoPayload(yo, support_dict)

        event_data = {'event': 'yo_acknowledged',
                      'yo_id': flattened_yo.yo_id,
                      'recipient': flattened_yo.recipient.username,
                      'sender': flattened_yo.sender.username,
                      'sender_in_store': bool(flattened_yo.sender.in_store),
                      'status': status,
                      'from_push': from_push,
                      'yo_type': payload.payload_type,
                      'group_yo': bool(flattened_yo.is_group_yo),
                      'sender_type': flattened_yo.sender.user_type,
                      'recipient_type': flattened_yo.recipient.user_type,
                      'yo_header': payload.get_push_text(),
                      'broadcast': bool(flattened_yo.broadcast)}
        current_app.log_analytics(event_data)

        header = get_header(yo.recipient, payload.payload_type,
                            bool(flattened_yo.group))
        if header:
            log_ab_test_data(yo.recipient, 'notification', header=header)

        # Group yos and broadcast yos should not notify of status changes.
        should_notify = not bool(yo.parent and yo.parent.has_children())
        should_notify = should_notify and not bool(yo.has_children())
        if should_notify:
            notify_yo_status_update(yo)

            if status == 'read':
                send_silent_yo_opened(yo)


def assert_valid_yo_token(yo_token):
    """Verifies a token against what is stored"""
    # Check that the auth_token exists.
    if not yo_token.auth_token:
        raise YoTokenInvalidError

    # Check if the token has already been used.
    if yo_token.auth_token.used:
        raise YoTokenUsedError

    # Check if the token has expired.
    # The default expiration time should be one day.
    if yo_token.auth_token.expires < get_usec_timestamp():
        raise YoTokenExpiredError

    yo_token.auth_token.used = get_usec_timestamp()
    yo_token.used = True
    yo_token.save()
    clear_get_yo_token_cache(yo_token.auth_token.token)


def favorite_yo(user_id, yo_id, favorite=True):
    """Allows users to favorite and unfavorite a yo they received
    IF they are indeed the recipient"""

    try:
        yo = get_yo_by_id(yo_id)
    except DoesNotExist:
        raise APIError('Yo not found')

    if yo.recipient and yo.recipient.user_id == user_id:
        yo.is_favorite = favorite
        yo.save()
        clear_get_yo_cache(yo_id)
        clear_get_favorite_yos_cache(user_id)


def increment_count_in(user):
    """Incrementes the received Yo counter for a user

    The reason we need an explicit function for this is because we increment
    it both in the database and clear the cache
    """
    user.update(inc__count_in=1)
    clear_get_yo_count_cache(user)


def increment_count_out(user):
    """Incrementes the received Yo counter for a user

    The reason we need an explicit function for this is because we increment
    it both in the database and under a redis key.
    """
    user.update(inc__count_out=1)


def construct_yo(sender=None, recipients=None, sound=None, link=None,
                 location=None, broadcast=False, ignore_permission=False,
                 header=None, link_content_type=None, origin_yo=None,
                 is_group_yo=None, context=None, cover_datauri=None,
                 photo_datauri=None, yo_token=None, context_id=None,
                 response_pair=None, oauth_client=None, reply_to=None,
                 text=None, left_link=None, right_link=None, is_poll=False,
                 app_id=None, is_push_only=False,
                 region_name=None):
    if not ignore_permission:
        if sender:
            assert_account_permission(sender, 'No permission to send Yo')

        if header and header.user:
            assert_account_permission(header.user,
                                      'No permission to use header')

    sender = sender if sender else None
    sound = sound if sound else 'yo.mp3'
    if sound == 'silent':
        sound = ''

    if region_name:
        region = get_region_by_name(region_name)
    else:
        region = None

    # We separate the link here to prevent validation errors
    # if the link is blank.
    link = link if link else None

    # We separate the location here to prevent validation errors
    # if the location is blank.
    location = location if location else None

    # This is migrating from old parameter name 'context' to
    # new parameter name 'text'
    # In the old scheme, 'context' was what was shown in the push header
    # In the new scheme, 'text' is shown, and 'context' is never shown
    # but is used by the developers alone
    if context and not text:
        text = context

    context = context if context else None
    text = text if text else None
    left_link = left_link if left_link else None
    right_link = right_link if right_link else None

    # We separate the context id here to prevent validation errors
    # if the context id is blank.
    context_id = context_id if context_id else None

    response_pair = response_pair if response_pair else None

    # Split location into a tuple so we can store it as a GeoPointField.
    if location:
        if ';' in location and ',' in location:
            location_parts = location.split(';')
            location_parts[0] = location_parts[0].replace(',', '.')
            location_parts[1] = location_parts[1].replace(',', '.')
        elif ';' in location:
            location_parts = location.split(';')
        elif ',' in location:
            location_parts = location.split(',')
        else:
            # This request must have somehow skipped form validation
            raise APIError('Improper location format. Use: 0.0, 0.0')

        location = (float(location_parts[0]), float(location_parts[1]))

    cover = None
    photo = None
    if cover_datauri:
        cover = s3.upload_photo(cover_datauri, sender)
        link_content_type = link_content_type or 'text/html'
    if photo_datauri:
        link_content_type = link_content_type or photo_datauri.mimetype
        photo = s3.upload_photo(photo_datauri, sender)

    # if there is a origin yo, replace the new yo's parameters
    if origin_yo:
        sound = origin_yo.sound
        link = origin_yo.link
        context = origin_yo.context
        text = origin_yo.text
        cover = origin_yo.cover
        photo = origin_yo.photo
        link_content_type = origin_yo.link_content_type
        short_link = origin_yo.short_link
        location = origin_yo.location
        left_link = origin_yo.left_link
        right_link = origin_yo.right_link

    # Raise an APIError if the hostname has been blocked
    # Fixes issue #17
    short_link = None
    if link:
        try:
            UrlHelper(link).raise_for_hostname()
        except ValueError:
            raise APIError('Invalid URL')

        # Prepare link
        urlhelper = UrlHelper(link, bitly=sender.bitly)
        link = urlhelper.get_url()
        if broadcast:
            short_link = urlhelper.get_short_url()

    # If the Yo is a broadcast then we need special different parameters from
    # a normal one.
    if broadcast or is_group_yo:
        recipient = None
        if is_group_yo and recipients and recipients[0].is_group:
            recipient = recipients[0]
            # send a silent push for group yos if the group has sent a yo
            # in the past hour. Pseudo users will still receive a normal SMS.
            one_hour_ago = get_usec_timestamp(datetime.timedelta(hours=-1))
            if recipient.last_yo_time > one_hour_ago:
                sound = ''

        yo = Yo(sender=sender,
                broadcast=broadcast or None,
                context=context,
                context_id=context_id,
                cover=cover,
                photo=photo,
                is_group_yo=bool(is_group_yo) or None,
                link=link,
                link_content_type=link_content_type,
                location=location,
                origin_yo=origin_yo,
                sent_location=bool(location) or None,
                recipient=recipient,
                short_link=short_link,
                header=header,
                sound=sound,
                response_pair=response_pair,
                oauth_client=oauth_client,
                reply_to=reply_to,
                text=text,
                left_link=left_link,
                right_link=right_link,
                is_poll=is_poll,
                region_name=region,
                app_id=app_id,
                is_push_only=is_push_only)

        if recipient and recipient.is_group:
            members = get_group_members(recipient)
            yo.not_on_yo = []
            for member in members:
                if member.is_pseudo:
                    yo.not_on_yo.append(member.phone)

    elif len(recipients) > 1:
        yo = Yo(sender=sender,
                context=context,
                context_id=context_id,
                cover=cover,
                photo=photo,
                link=link,
                link_content_type=link_content_type,
                location=location,
                origin_yo=origin_yo,
                sent_location=bool(location) or None,
                recipients=recipients,
                recipient_count=1,
                sound=sound,
                header=header,
                status='pending',
                yo_token=yo_token,
                response_pair=response_pair,
                oauth_client=oauth_client,
                reply_to=reply_to,
                text=text,
                left_link=left_link,
                right_link=right_link,
                is_poll=is_poll,
                region_name=region,
                app_id=app_id,
                is_push_only=is_push_only)
    else:
        yo = Yo(sender=sender,
                context=context,
                context_id=context_id,
                cover=cover,
                photo=photo,
                link=link,
                link_content_type=link_content_type,
                location=location,
                origin_yo=origin_yo,
                sent_location=bool(location) or None,
                recipient=recipients[0],
                recipient_count=1,
                sound=sound,
                header=header,
                status='pending',
                yo_token=yo_token,
                response_pair=response_pair,
                oauth_client=oauth_client,
                reply_to=reply_to,
                text=text,
                left_link=left_link,
                right_link=right_link,
                is_poll=is_poll,
                region=region,
                app_id=app_id,
                is_push_only=is_push_only)

    # We use to check if the payload was too large but instead just
    # check the link and shorten it if necessary.
    if yo.link and not yo.short_link and len(link) > 512:
        yo.short_link = UrlHelper(link).get_short_url()

    # Don't save the yo until we know it passes validation.
    yo.save()

    return yo


def construct_auto_follow_yo(user, auto_follow_user):
    if auto_follow_user.welcome_link:
        link = auto_follow_user.welcome_link
    else:
        last_yo = get_last_broadcast(auto_follow_user,
                                     ignore_permission=True)
        # Prefer the bitly link to increase brands ctr
        link = last_yo.short_link or last_yo.link if last_yo else None
        if not link:
            return None

    yo = construct_yo(sender=auto_follow_user, recipients=[user], link=link,
                      ignore_permission=True)

    return yo


def construct_first_yo(user, first_yo_from):
    first_yo_link = current_app.config.get('FIRST_YO_LINK')
    first_yo_location = current_app.config.get('FIRST_YO_LOCATION')
    first_yo_delay = current_app.config.get('FIRST_YO_DELAY')
    first_yo_delay = first_yo_delay.replace(' ', '').split(',')

    first_yo_link_delay = int(first_yo_delay[0])
    first_yo_location_delay = int(first_yo_delay[1])

    location_header = get_header_by_id('54de9ecba17351c1d85a55aa')
    link_header = get_header_by_id('54dd6939a17351c1d859692e')

    yo_link = construct_yo(sender=first_yo_from, recipients=[user],
                           link=first_yo_link, ignore_permission=True,
                           header=link_header, link_content_type='text/html')

    yo_location = construct_yo(sender=first_yo_from, recipients=[user],
                               location=first_yo_location,
                               ignore_permission=True, header=location_header)

    return yo_link, yo_location


def get_params_for_callback(sender_id, yo_id):
    sender = _get_user(sender_id)
    yo = get_yo_by_id(yo_id)

    # Parameters we want to attach.
    params = {'username': sender.username,
              'display_name': sender.display_name,
              'user_ip': request.remote_addr}

    if yo.link:
        params.update({'link': yo.link})

    if yo.location:
        location_str = '%s;%s' % (yo.location[0], yo.location[1])
        params.update({'location': location_str})

    if yo.context:
        params.update({'context': yo.context})

    if yo.reply_to and yo.reply_to.text:
        params.update({'reply_to': get_public_dict_for_yo_id(yo.reply_to.yo_id)})

        if yo.text and yo.reply_to.response_pair:
            reply_text = yo.reply_to.left_reply if yo.text == yo.reply_to.response_pair.split('.')[
                0] else yo.reply_to.right_reply
            params.update({
                'reply': {
                    'sender_city': sender.city or sender.region_name,
                    'text': reply_text
                }})

        if yo.reply_to.sender.parent:
            params.update({'publisher_username': yo.reply_to.sender.parent.username})

    elif yo.reply_to and yo.reply_to.parent and yo.reply_to.parent.text:
        params.update({'reply_to': get_public_dict_for_yo_id(yo.reply_to.parent.yo_id)})

        if yo.reply_to.parent.sender.parent:
            params.update({'publisher_username': yo.reply_to.parent.sender.parent.username})

    return params


@async_job(rq=low_rq)
def trigger_callback(sender_id, callback, yo_id):
    """Augment the callback URL and trigger it."""

    params = get_params_for_callback(sender_id, yo_id)

    try:
        # Set stream to true so that we don't actually download the response
        # Similarly, we set connection close so that the connection doesn't
        # stay open.

        # Since get requests have issues with emojis, all new callbacks that need
        # reply or reply_to will be in POST
        url = None
        if params.get('reply') or params.get('reply_to'):
            requests.post(callback, data=json.dumps(params),
                          timeout=3,
                          stream=True,
                          headers={'Connection': 'close',
                                   'Content-type': 'application/json'},
                          verify=False)

        else:
            params.pop('display_name')
            if params.get('context'):
                params.pop('context')
            helper = UrlHelper(callback, params=params)
            url = helper.get_url()
            requests.get(url,
                         timeout=3,
                         stream=True,
                         headers={'Connection': 'close'},
                         verify=False)


    except Exception as e:
        if url:
            yo = get_yo_by_id(yo_id)
            user = yo.recipient
            body = 'Hi there! We\'ve experienced an issue with the callback URL specified on Yo username:' \
                   '{}.\n' \
                   'The user received a Yo and subsequently we\'ve sent a request to: {}\n' \
                   'which resulted in the error: {}'.format(user.username, url, str(e.message))
            sendgrid.send_mail(recipient=user.email,
                               subject='Yo Callback Failure',
                               body=body,
                               sender='api@justyo.co')
            log_to_slack('sent to {}: {}'.format(user.email, body))
        else:
            log_to_slack(str(e.message))


def publish_to_pubsub(yo):
    try:
        params = get_params_for_callback(yo.sender.user_id, yo.yo_id)
        redis_pubsub.publish({'cmd': 'message',
                              'type': 'yo',
                              'data': params},
                             channel=str(yo.recipient.id))
    except (ValueError, RequestException, Timeout) as err:
        current_app.log_warning(sys.exc_info(), message='redis_pubsub error: ' + err)


def ping_live_counter():
    """Pings the live Yo counter."""

    headers = {'Auth-Token': current_app.config['LIVE_COUNTER_AUTH_TOKEN'],
               'Connection': 'close'}
    try:
        requests.get(current_app.config['LIVE_COUNTER_URL'], stream=True,
                     headers=headers, timeout=20)
    except:
        current_app.logger.warning('Live counter not available')


def _create_child_yos(yo, recipients):
    """Creates the child yos for use with broadcasting.
       Each child yo represents an individual recipient."""

    children = []
    recipient_count = 0
    for i, recipient in enumerate(recipients):
        recipient_count += 1
        status = 'pending'
        # When yos are muted, they come in with a status already provided.
        if isinstance(recipient, tuple):
            recipient, status = recipient

        child_yo = Yo(parent=yo,
                      recipient=recipient,
                      status=status,
                      created=get_usec_timestamp(),
                      is_poll=yo.is_poll,
                      left_link=yo.left_link,
                      right_link=yo.right_link,
                      app_id=yo.app_id)
        children.append(child_yo)

        if i > 0 and i % YO_BUFFER_MAX == 0:
            Yo.objects.insert(children, load_bulk=False)
            children = []

    # Set load_bulk to False so that only ObjectId's are returned
    # Yo cannot insert an empty list
    if children:
        Yo.objects.insert(children, load_bulk=False)

    return recipient_count


@async_job(rq=low_rq)
def send_slack_msg():
    log_to_slack('Yo')