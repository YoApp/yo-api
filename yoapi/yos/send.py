# -*- coding: utf-8 -*-

"""Yo sending package."""

import sys
from uuid import uuid4
import cStringIO
from datetime import timedelta

import gevent
from flask import current_app, request, g
from haversine import haversine
from mongoengine import DoesNotExist
from pygeocoder import GeocoderError
import requests
from requests.exceptions import RequestException
from .helpers import (_create_child_yos, assert_valid_yo_token,
                      construct_yo, increment_count_out, increment_count_in,
                      trigger_callback, publish_to_pubsub, acknowledge_yo_received)
from .queries import (clear_get_unread_yos_cache, clear_get_yo_cache,
                      clear_get_yos_received_cache, clear_get_yos_sent_cache,
                      get_child_yos, get_last_broadcast,
                      get_yo_by_id)
from ..ab_test import log_ab_test_data
from ..accounts import get_user, update_user
from ..async import async_job
from ..constants.yos import *
from ..contacts import get_followers, upsert_contact, get_contact_pair
from ..core import geocoder, parse, s3, log_to_slack
from ..datauri import DataURI
from ..errors import APIError
from ..groups import (get_group_followers, fix_old_group,
                      get_group_contacts)
from ..headers import get_header_by_id
from ..helpers import (partition_list, get_usec_timestamp,
                       copy_current_request_context, get_link_content_type)
from ..models import User, Yo, NotificationEndpoint
from ..notification_endpoints import get_user_endpoints, IOS, IOSBETA
from ..notifications import _push_to_endpoint, _send_notification_to_user, send_command_add_response
from ..security import load_identity
from ..urltools import UrlHelper
from ..models.payload import YoPayload
from yoapi.constants.emojis import EMOJI_TO_PNG
from yoapi.constants.sns import APP_ID_TO_ARN_IDS
from yoapi.helpers import generate_thumbnail_from_url, generate_thumbnail_from_image
from yoapi.models.integration import Integration
from yoapi.models.notification_endpoint import IOSDEV
from yoapi.services import low_rq, medium_rq


@async_job(rq=low_rq)
def send_response_yo(parent_yo_id, use_welcome_link=False):
    """When sending a single yo, if the recipient does not have a callback
    respond with the recipient's welcome link or last broadcast yo"""

    yo = get_yo_by_id(parent_yo_id)
    recipient = yo.recipient

    # If not explicitly told to use the welcome link,
    # try and send the last broadcast
    if not use_welcome_link:
        last_broadcast = get_last_broadcast(recipient,
                                            ignore_permission=True)
        response_link = last_broadcast.link or last_broadcast.short_link \
            if last_broadcast else None

    if use_welcome_link or not response_link:
        response_link = recipient.welcome_link

    if not response_link:
        return

    response_yo = Yo(sender=recipient,
                     link=response_link,
                     parent=yo,
                     sound=yo.sound,
                     recipient=yo.sender,
                     status='pending').save()
    response_job = _send_yo.delay(yo_id=response_yo.yo_id)
    # This type of impersonation should be used carefully.
    response_job.meta['request_environ']['REMOTE_USER'] = \
        recipient.user_id
    response_job.save()
    clear_get_yos_sent_cache(recipient)
    clear_get_yos_received_cache(yo.sender)


@async_job(rq=low_rq)
def _push_to_recipient(yo_id, protocol='sns', add_response_acked=False):
    """Pushes a single Yo to a single recipient

    The required steps to sending a Yo are as follows:

        1) Check if recipient has blocked sender.
        2) Send the Yo!
        5) Establish the sender as a follower of the receiver.
        6) Log the Yo in Parse.
        7) Unset location when it is no longer necessary.*

    * This is done for privacy reasons. Location data is sensitive and we
    refrain from storing it.
    """

    try:
        yo = get_yo_by_id(yo_id)
    except DoesNotExist as err:
        # Yo deleted, abort push.
        raise APIError('Job terminated because Yo has been deleted',
                       status_code=404)

    flattened_yo = yo.get_flattened_yo()

    # Get the sender from the parent.
    sender = flattened_yo.sender

    if yo.recipient.has_blocked(sender):
        return 'Yo canceled because sender has been blocked'

    if yo.recipient.has_blocked(sender):
        return 'Yo canceled because sender has been blocked'

    if yo.region:
        if yo.recipient.latitude and yo.recipient.longitude:
            user_location = (yo.recipient.latitude, yo.recipient.longitude)
            region_center = (yo.region.latitude, yo.region.longitude)
            distance = haversine(user_location,
                                 region_center,
                                 miles=True)
            if distance > yo.region.radius:
                return 'Yo canceled because recipient is not in region'

    # Increment the count_in for the recipient.
    if not flattened_yo.broadcast:
        increment_count_in(yo.recipient)
        clear_get_yos_received_cache(yo.recipient)

    clear_get_unread_yos_cache(yo.recipient.user_id, UNREAD_YOS_FETCH_LIMIT)

    # Don't send yos already marked as 'sent'.
    # This would most likely mean the yo was muted.
    if yo.status == 'sent':
        #if yo.recipient and yo.recipient.is_beta_tester:
        #    log_to_slack('Yo as muted')
        return 'Yo muted'

    if protocol == 'sms':

        if yo.app_id == 'co.justyo.noapp':
            message = '{} sent you a No'.format(yo.sender.display_name)
            _push_to_endpoint.delay(phone=yo.recipient.phone, message=message)
            return
        # update in tests/payload_test when changing
        sms_support_dict = {
            'handles_any_text': True,
            'handles_invisible_push': False,
            'handles_display_names': True,
            'handles_long_text': True,
            'handles_response_category': True,
            'is_legacy': False,
            'platform': IOS,
            'handles_unicode': False,
            }

        if yo.parent:
            yo.parent.update(inc__sent_count=1)
            clear_get_yo_cache(yo.parent.yo_id)

        # If the Yo is a group yo we know this is a YoGoupPayload.
        payload = YoPayload(yo, sms_support_dict, log_enrolled=True)

        if flattened_yo.is_group_yo and flattened_yo.group:
            group_contacts = get_group_contacts(flattened_yo.group)
            payload.set_yo_social_text(flattened_yo, group_contacts)

        push_text = payload.get_yo_sms_text(flattened_yo, max_length=160)
        message = push_text.encode('ascii', 'ignore')
        max_sms_size = 160 + sys.getsizeof('')
        if sys.getsizeof(message) > max_sms_size:
            current_app.logger.warning('Sending bad SMS: %s' % message)

        if (yo.recipient.phone.startswith('+1') and
                flattened_yo.link_content_type and
                flattened_yo.link_content_type.startswith('image')):
            _push_to_endpoint.delay(phone=yo.recipient.phone, message=message, media_url=flattened_yo.link)
        elif yo.location:
            location_str = '%s,%s' % (yo.location[0], yo.location[1])
            link = 'http://maps.googleapis.com/maps/api/staticmap?center={0}&zoom=17&scale=false&size=600x600&' \
                   'maptype=roadmap&format=png&markers=icon:http://goo.gl/PImFNW%7C{1}'.format(location_str, \
                                                                                               location_str)
            _push_to_endpoint.delay(phone=yo.recipient.phone, message=message, media_url=link)
        else:
            _push_to_endpoint.delay(phone=yo.recipient.phone, message=message)

        event_data = {'event': 'pseudo_yo_delivered',
                      'recipient': flattened_yo.recipient.username,
                      'phone': flattened_yo.recipient.phone,
                      'sender': flattened_yo.sender.username,
                      'yo_type': payload.payload_type,
                      'group_yo': bool(flattened_yo.group),
                      'yo_header': message,
                      'yo_id': flattened_yo.yo_id}
        current_app.log_analytics(event_data)

        if not yo.recipient.count_in:
            _push_to_endpoint.delay(phone=yo.recipient.phone,
                                    message=WELCOME_MESSAGE_COPY)

        yo.status = 'sent'
        yo.save()
        clear_get_yo_cache(yo.yo_id)

    if protocol == 'sns':

        #if yo.recipient and yo.recipient.is_beta_tester:
        #    log_to_slack('Sending Yo to ' + yo.recipient.username + '  ' + yo.yo_id)

        endpoints = get_user_endpoints(yo.recipient, ignore_permissions=True)

        #if yo.recipient and yo.recipient.is_beta_tester:
        #    if endpoints:
        #        log_to_slack('There are ' + str(len(endpoints)) + ' endpoints')
        #    else:
        #        log_to_slack('There are no endpoints')

        if endpoints:
            event_data = {'event': 'yo_delivered',
                          'username': flattened_yo.recipient.username,
                          'sender': flattened_yo.sender.username,
                          'yo_id': flattened_yo.yo_id}
            current_app.log_analytics(event_data)

            if yo.parent:
                yo.parent.update(inc__sent_count=1)
                clear_get_yo_cache(yo.parent.yo_id)

        for i, endpoint in enumerate(endpoints):

            #  @or: check if endpoint belongs to the app that sent the Yo
            if yo.app_id and endpoint.platform not in APP_ID_TO_ARN_IDS[yo.app_id]:
                #if yo.recipient and yo.recipient.is_beta_tester:
                #    log_to_slack('Endpoint not of Yo app:' + endpoint.platform)
                continue

            if yo.app_id is None and endpoint.platform not in APP_ID_TO_ARN_IDS['co.justyo.yoapp']:
                #if yo.recipient and yo.recipient.is_beta_tester:
                #    log_to_slack('Endpoint not of Yo app2:' + endpoint.platform)
                continue

            #if yo.recipient and yo.recipient.is_beta_tester:
            #    log_to_slack('Sending to endpoint: ' + str(endpoint.id))

            payload = YoPayload(yo, endpoint.get_payload_support_dict(),
                                log_enrolled=bool(i == 0))

            _push_to_endpoint(endpoint.arn,
                              sns_message=payload.to_sns(endpoint))

        #if yo.recipient and yo.recipient.is_beta_tester:
        #    log_to_slack('Marking Yo as send')
        yo.status = 'sent'
        yo.save()
        clear_get_yo_cache(yo.yo_id)

    if protocol == 'parse':

        pass

    if protocol in ['sns', 'sms']:
        # Update the user last in case it fails.
        # NOTE: APIErrors are not retried.
        if yo.recipient:
            update_user(yo.recipient, last_yo_time=get_usec_timestamp(),
                        ignore_permission=True)
            update_user(yo.recipient, last_received_time=get_usec_timestamp(),
                        ignore_permission=True)


@async_job(rq=low_rq)
def _apply_callback(yo_id):
    try:
        yo = get_yo_by_id(yo_id)
    except DoesNotExist as err:
        # Yo deleted, abort push.
        raise APIError('Job terminated because Yo has been deleted',
                       status_code=404)

    flattened_yo = yo.get_flattened_yo()

    # Get the sender from the parent.
    sender = flattened_yo.sender

    if yo.recipient:
        publish_to_pubsub(yo)

    # Trigger callback.
    if yo.should_trigger_callback():

        if yo.recipient:
            if yo.recipient.callback:
                trigger_callback(sender.id,
                                 yo.recipient.callback,
                                 yo_id)

            if yo.recipient.callbacks:
                for callback_url in yo.recipient.callbacks:
                    trigger_callback(sender.id,
                                 callback_url,
                                 yo_id)

        elif yo.reply_to:

            if yo.reply_to.parent:

                if yo.reply_to.parent.sender.callback:
                    trigger_callback(sender.id,
                                     yo.reply_to.parent.sender.callback,
                                     yo_id)

                if yo.reply_to.parent.sender.callbacks:
                    for callback_url in yo.reply_to.parent.sender.callbacks:
                        trigger_callback(sender.id,
                                         callback_url,
                                         yo_id)
            else:
                if yo.reply_to.sender.callback:
                    trigger_callback(sender.id,
                                     yo.reply_to.sender.callback,
                                     yo_id)

                if yo.reply_to.sender.callbacks:
                    for callback_url in yo.reply_to.sender.callbacks:
                        trigger_callback(sender.id,
                                         callback_url,
                                         yo_id)

    try:
        if yo.should_trigger_oauth_callback():
            trigger_callback.delay(sender,
                                   yo.reply_to.oauth_client.callback_url,
                                   yo_id)
    except Exception as e:
        pass

    try:
        if yo.recipient:
            recipient_id = yo.recipient.parent.id if yo.recipient.parent else yo.recipient.id
            integrations = Integration.objects.filter(user_id=str(recipient_id))
            for integration in integrations:
                if integration.callback_url:
                    try:
                        trigger_callback.delay(sender,
                                               integration.callback_url,
                                               yo_id)
                    except Exception as e:
                        pass
    except Exception as e:
        pass


@async_job(rq=low_rq)
def _push_to_recipient_partition(yo_id, recipient_ids):
    """Pushes a Yo to a group of recipients

    The required steps to sending a Yo are as follows:

        1) Check if recipient has blocked sender.
        2) Send the Yo!
        3) Log the Yo in Parse.

    """

    # Check if the Yo exists before getting all the users
    parent_yo = get_yo_by_id(yo_id)
    yos = Yo.objects(parent=yo_id, recipient__in=recipient_ids)

    if not (parent_yo and yos):
        # Yo deleted, abort push.
        raise APIError('Job terminated because Yo has been deleted',
                       status_code=404)

    # Create a payload from one of the child yos
    endpoint_support_dict = {
        'handles_any_text': False,
        'handles_long_text': False,
        'handles_response_category': False,
        'is_legacy': True
    }
    payload = YoPayload(yos[0], endpoint_support_dict)

    # We load the user from the id here because the job can be delayed. We
    # therefore need to know about e.g. blocked users at time on sending
    # instead of time queued.

    # If the recipient is blocked just continue to the next.
    usernames = [yo.recipient.username for yo in yos
                 if not yo.recipient.has_blocked(yo.parent.sender)]

    # Push payload to parse user.
    # We no longer really care about what parse does.
    try:
        parse.push(usernames, payload.to_parse())
    except:
        pass

    # It is important as a general rule to always push to parse last
    # so that we know we can mutate the yo.
    for yo in yos:
        yo.status = 'sent'
        yo.save()
        clear_get_yo_cache(yo.yo_id)

    parent_yo.update(inc__sent_count=len(recipient_ids))
    clear_get_yo_cache(yo.parent.yo_id)


@async_job(rq=low_rq)
def _push_to_recipients(parent_yo_id):
    """Pushes Yo's to a list of recipients"""

    parent_yo = get_yo_by_id(parent_yo_id)
    yos = get_child_yos(parent_yo.yo_id)
    # Any broadcasts with a recipient count lower than this cutoff will be sent
    # through the regular worker channel.
    queue_lbound = current_app.config.get('SEPARATE_QUEUE_LBOUND', 500)

    if parent_yo.recipient_count >= queue_lbound:
        custom_queue = parent_yo.sender.username

        # Since broadcasts are relatively low frequency, we use this
        # opportunity to clear empty queues from RQ.
        low_rq.clear_empty_queues()
    else:
        custom_queue = None

    # Apply the custom queue decorator
    __push_to_recipient = _push_to_recipient.original_func
    __push_to_recipient_partition = _push_to_recipient_partition.original_func
    custom_async_job = async_job(rq=low_rq, custom_queue=custom_queue)
    push_to_recipient_custom = custom_async_job(__push_to_recipient)
    push_to_partition_custom = custom_async_job(__push_to_recipient_partition)

    # Send the Yo to SNS and parse.
    # Push to sns separately so that if parse fails sns
    # won't be retried.

    queuing_pool = gevent.pool.Pool(QUEUING_WORKERS)
    recipients = []

    def push_to_partition_worker(parent_yo, partition):
        """Queues parse recipient partitions in parallel"""
        try:
            push_to_partition_custom.delay(parent_yo.yo_id, partition)
        except Exception as err:
            current_app.log_exception(sys.exc_info())

    def push_to_recipient_worker(yo, protocol='sns'):
        """Pulls Yo's from the iterator in parallel to speed up queuing.
        Uses a lock to ensure there are no cursor collisions"""

        try:
            push_to_recipient_custom.delay(yo.yo_id,
                                           protocol=protocol)
        except Exception as err:
            current_app.log_exception(sys.exc_info())

    # Get the first yo or an empty array.
    test_child_yo = yos[0:1]
    if test_child_yo:
        support_dict = NotificationEndpoint.perfect_payload_support_dict()
        payload = YoPayload(test_child_yo[0], support_dict)
        if payload.payload_too_large():
            message = 'Trying to send a payload that is over 2KB'
            current_app.log_error(message, payload_type=payload.payload_type,
                                  sender=parent_yo.sender.username,
                                  yo_id=parent_yo.yo_id)

        recipient_type = None
        recipient = None
        if parent_yo.is_group_yo:
            recipient_type = 'legacy_group'
            if parent_yo.recipient:
                recipient_type = 'group'
                recipient = parent_yo.recipient.username
        elif parent_yo.broadcast:
            recipient_type = 'broadcast'

        event_data = {'event': 'yo_sent',
                      'yo_id': parent_yo.yo_id,
                      'recipient': recipient,
                      'sender': parent_yo.sender.username,
                      'sender_in_store': bool(parent_yo.sender.in_store),
                      'yo_type': payload.payload_type,
                      'group_yo': bool(parent_yo.is_group_yo),
                      'sender_type': parent_yo.sender.user_type,
                      'recipient_type': recipient_type,
                      'yo_header': payload.get_push_text(),
                      'broadcast': bool(parent_yo.broadcast)}
        current_app.log_analytics(event_data)

    # continue queuing until no yos are available.
    for yo in yos:
        # Skip yos where the recipient is no longer valid.
        if yo.has_dbrefs():
            continue

        # Dont send to sender for group yos.
        if parent_yo.is_group_yo and yo.recipient == parent_yo.sender:
            continue

        # build the recipients array for parse.
        protocol = 'sms'
        if not yo.recipient.is_pseudo:
            protocol = 'sns'
            recipients.append(yo.recipient.user_id)

        wrapped_worker = copy_current_request_context(push_to_recipient_worker)
        queuing_pool.spawn(wrapped_worker, yo, protocol)

    # Do not push if there aren't any recipients.
    if recipients:
        # Always push to parse because push registration for android was
        # previously handled on the device.
        # Always push to parse last so that the yo can be mutated.
        # Since parse is being deprecated always push in bulk.
        follower_partitions = partition_list(recipients, PARTITION_SIZE)
        for partition in follower_partitions:
            wrapped_worker = copy_current_request_context(push_to_partition_worker)
            queuing_pool.spawn(wrapped_worker, parent_yo, partition)

    queuing_pool.join()


def generate_thumbnail_url(yo):
    thumbnail_url = None

    if yo.link or yo.photo:

        if 'video' in yo.link_content_type:
            thumbnail_url = 'https://yoapp.s3.amazonaws.com/yo/emoji_objects-24.png'

        elif yo.photo or yo.link_content_type.startswith('image'):

            if 'gif' in yo.link_content_type:
                thumbnail_url = yo.link
            else:
                url = yo.photo.make_full_url() if yo.photo else yo.link
                response = requests.get(url)
                file = cStringIO.StringIO(response.content)
                thumbnail_data = generate_thumbnail_from_image(file)
                filename = str(str(uuid4())[:32] + '.png')
                thumbnail_url = s3.upload_image(filename, thumbnail_data)

        else:
            thumbnail_url = generate_thumbnail_from_url(yo.link)

    elif yo.location:
        location_str = '%s,%s' % (yo.location[0], yo.location[1])
        thumbnail_url = 'http://maps.googleapis.com/maps/api/staticmap?center={0}&zoom=17&scale=false&size=178x178&' \
                        'maptype=roadmap&format=png&markers=icon:http://goo.gl/PImFNW%7C{1}'.format(location_str,
                                                                                                    location_str)

    elif yo.context:
        if EMOJI_TO_PNG.get(yo.context):
            thumbnail_url = EMOJI_TO_PNG.get(yo.context)

    #if len(thumbnail_url) > 40:
    #    thumbnail_url = UrlHelper(thumbnail_url).get_short_url()

    return thumbnail_url


@async_job(rq=low_rq)
def _send_yo(yo_id=None, recipient_ids=None,
             reply_to=None):
    """Either sends or broadcasts a Yo

    This function can either be delayed and relayed to a background
    worker or executed synchronously.
    """
    # pylint: disable=invalid-name
    yo = get_yo_by_id(yo_id)
    ten_min_ago = get_usec_timestamp(timedelta(minutes=-10))

    update_user(yo.sender, last_sent_time=get_usec_timestamp(),
                ignore_permission=True)

    if reply_to:
        acknowledge_yo_received(reply_to, status='read', from_push=False)

    if yo.reply_to and yo.reply_to.parent:
        yo.reply_to = Yo(id=str(yo.reply_to.parent.id))
        reply_to = yo.reply_to

    if yo.link and yo.link_content_type is None:
        try:
            yo.link_content_type = get_link_content_type(yo.link)

        except RequestException as err:
            yo.link_content_type = 'application/unknown'
            # Instead of making assumptions about
            # why an error occurred here, let these through

    image = yo.photo or yo.cover
    if image and not image.yo:
        image.yo = yo

        urlhelper = UrlHelper(image.make_full_url(), bitly=yo.sender.bitly)
        try:
            image.short_link = urlhelper.get_short_url()
        except APIError:
            # The underlying request exception is already sent to us.
            # If the bitly link is bad or the request is malformed we likely
            # don't need to be informed.
            pass

        image.save()

    # Change the scheduling status.
    if yo.status == 'started':
        yo.status = 'sending'

    # If this is a broadcast attach the recipients from get_followers.
    # If the recipient_count has already been populated or the
    # recipient_ids have been supplied, do not use the followers.
    if yo.broadcast and yo.recipient_count is None and recipient_ids is None:
        recipient_ids = get_followers(yo.sender)

    elif yo.is_group_yo and yo.recipient and yo.recipient.is_group:
        group = yo.recipient
        update_user(group, last_yo_time=get_usec_timestamp(),
                    ignore_permission=True)
        contacts = get_group_followers(group)
        current_time = get_usec_timestamp()
        recipient_ids = []
        # If the member has muted the group, set the status to 'sent'
        # so that it won't be sent but will show up in the inbox.
        for contact in contacts:
            member = contact.owner
            last_yo_was_recent = (member.last_yo_time and
                                  member.last_yo_time >= ten_min_ago)
            logged_in_after_last_yo = (member.last_seen_time and
                                       member.last_seen_time > member.last_yo_time)
            if contact.mute_until > current_time:
                recipient_ids.append((member.user_id, 'sent'))
            elif (member.is_pseudo and last_yo_was_recent and
                      not logged_in_after_last_yo):
                recipient_ids.append((member.user_id, 'sent'))
            elif member.is_pseudo:
                recipient_ids.append((member.user_id, 'sent'))
            else:
                recipient_ids.append(member.user_id)

    elif yo.recipients and len(yo.recipients) > 1:
        recipient_ids = []
        for recipient in yo.recipients:
            if not recipient.is_pseudo:
                recipient_ids.append(recipient.user_id)

    if yo.has_children() and recipient_ids:
        yo.recipient_count = _create_child_yos(yo, recipient_ids)

    if yo.location and not (yo.location_city or yo.header):
        try:
            location = yo.location
            formatted_addresses = geocoder.reverse_geocode(location[0],
                                                           location[1])
            if formatted_addresses.count == 0:
                raise GeocoderError('Invalid count')

            yo.location_city = formatted_addresses[0].city or None
        except Exception as err:
            pass
            """
            TODO: revisit increasing our rate limit for this. When it is hit
            a OVER_QUERY_LIMIT error is thrown. For now, silence the error
            emails.
            if err.status not in ['ZERO_RESULTS', 'UNKNOWN_ERROR']:
                current_app.log_exception(sys.exc_info())
            """

    try:
        yo.thumbnail_url = generate_thumbnail_url(yo)
    except:
        current_app.log_exception(sys.exc_info())

    if yo.recipient and not yo.recipient.is_group:
        user = yo.recipient
        contact = get_contact_pair(user, yo.sender)
        if contact and contact.mute_until > get_usec_timestamp():
            yo.status = 'sent'

        last_yo_was_recent = (user.last_yo_time and
                              user.last_yo_time >= ten_min_ago)
        logged_in_after_last_yo = (user.last_seen_time and
                                   user.last_seen_time > user.last_yo_time)

        if (user.is_pseudo and last_yo_was_recent and
                not logged_in_after_last_yo):
            yo.status = 'sent'

    if yo._changed_fields:
        yo.save()
        clear_get_yo_cache(yo.yo_id)

    if yo.has_children():
        _push_to_recipients.delay(yo.yo_id)

    # If this is a single yo and the recipient is not private or not a
    # group send it now.
    if yo.recipient and not yo.recipient.is_group:
        support_dict = NotificationEndpoint.perfect_payload_support_dict()
        payload = YoPayload(yo, support_dict)
        if payload.payload_too_large():
            message = 'Trying to send a payload that is over 2KB'
            current_app.log_error(message,
                                  yo_id=yo_id,
                                  sender=yo.sender.username,
                                  payload_type=payload.payload_type)

        if not yo.recipient.is_private and yo.recipient.is_pseudo:
            _push_to_recipient.delay(yo.yo_id, protocol='sms')
        elif not yo.recipient.is_private:
            # Always push to sns so we can push to endpoints.
            _push_to_recipient(yo.yo_id, protocol='sns')

        event_data = {'event': 'yo_sent',
                      'yo_id': yo.yo_id,
                      'recipient': yo.recipient.username,
                      'context_id': yo.context_id,
                      'reply_to_yo_id': reply_to,
                      'sender': yo.sender.username,
                      'sender_in_store': bool(yo.sender.in_store),
                      'yo_type': payload.payload_type,
                      'group_yo': False,
                      'sender_type': yo.sender.user_type,
                      'recipient_type': yo.recipient.user_type,
                      'yo_header': payload.get_push_text(),
                      'broadcast': False}
        current_app.log_analytics(event_data)

    if yo.context_id:
        log_ab_test_data(yo.sender, 'context', context_id=yo.context_id)


def send_yo(sender=None, recipients=None, sound=None, link=None,
            location=None, broadcast=False, header=None, yo_id=None,
            context=None, cover=None, photo=None, context_id=None,
            reply_to=None, response_pair=None, oauth_client=None,
            text=None, left_link=None, right_link=None,
            disable_send=False, is_poll=False, region_name=None,
            app_id=None, is_push_only=False,
            ignore_permission=False):
    """A helper function to prepare and send a Yo"""

    # Set the sender if one isn't provided.
    sender = sender if sender else g.identity.user

    # Turn recipient str into a list of usernames.
    recipient_usernames = None
    if recipients:
        if type(recipients) is str or type(recipients) is unicode:
            recipient_usernames = recipients.split('+')
            recipient_usernames = [r.strip() for r in recipient_usernames if r.strip()]

    # groups are not allowed to send yosß or do anything really.
    # they are merely wrappers for functionality.
    if sender.is_group:
        raise APIError('Groups cannot send yos.')

    if not (recipients or recipient_usernames or broadcast):
        raise APIError('Can\'t send Yo without a recipient.')

    if link and location:
        raise APIError('Can\'t send Yo with location and link.')

    if cover and photo:
        raise APIError('Can\'t send Yo with cover image and photo.')

    if cover and location:
        raise APIError('Can\'t send Yo with cover image and location.')

    # If YOALL is in the list then clear recipients to turn this Yo into a
    # broadcast.
    if recipient_usernames and 'YOALL' in recipient_usernames:
        recipient_usernames = []
        broadcast = True

    is_group_yo = recipient_usernames and len(recipient_usernames) > 1

    recipient_username_set = None
    if recipient_usernames:
        recipient_username_set = set()
        recipients = []
        for recipient_username in recipient_usernames:
            # Don't allow duplicates.
            if recipient_username.upper() in recipient_username_set:
                continue

            # Get user will error if the user is not found.
            recipient = get_user(username=recipient_username)
            if recipient.is_pseudo and recipient.migrated_to:
                recipient = recipient.migrated_to

            # If the user was deleted but is still cached it will be a DBRef.
            if not isinstance(recipient, User):
                raise APIError('User not found.', status_code=404)

            if recipient.has_blocked(sender):
                raise APIError('Blocked by user.', status_code=403)

            # Prevent users from sending a yo to a group AND other users.
            # Only consider this a group yo based on a group being the recipient
            # if there is only one recipient and the sender is in that group.
            if recipient.is_group:
                if (recipient.created < 1434350930750436 and
                            recipient.updated < 1434350930750436):
                    fix_old_group(recipient)

                #if not is_user_in_group(recipient, sender):
                #    raise APIError('You are not in that group.', status_code=403)

                if not is_group_yo:
                    is_group_yo = True
                else:
                    continue

            recipient_username_set.add(recipient.username)
            recipients.append(recipient)

    # If for some reason no recipients were added throw an error.
    if not (recipients or broadcast):
        raise APIError('Error sending yo.', status_code=404)

    if not broadcast and recipient_username_set and len(recipient_username_set) < 1:
        raise APIError('Can\'t send Yo without a recipient.')

    # If a yo is forwarded, a yo_id will be sent with the request.
    # Forwarded yo's should only care about the parent if the parent
    # is a broadcast.
    yo_id = yo_id or None
    origin_yo = None
    if yo_id:
        origin_yo = get_yo_by_id(yo_id)
        if not isinstance(origin_yo, Yo):
            raise APIError('Error sending Yo')

        if origin_yo.parent and origin_yo.parent.has_children():
            origin_yo = origin_yo.parent

        if not origin_yo.link:
            raise APIError('Only Yo\'s with content can be forwarded')

    try:
        cover_datauri = DataURI(cover) if cover else None
        photo_datauri = DataURI(photo) if photo else None
    except ValueError:
        raise APIError('Improper image provided')

    # Since headers are a hidden feature, we don't care about errors here.
    header = header or None
    if header:
        try:
            header = get_header_by_id(header)
        except:
            header = None

    yo = construct_yo(sender=sender, recipients=recipients, sound=sound,
                      link=link, location=location, broadcast=broadcast,
                      header=header, origin_yo=origin_yo, context=context,
                      is_group_yo=is_group_yo, cover_datauri=cover_datauri,
                      photo_datauri=photo_datauri, context_id=context_id,
                      response_pair=response_pair, oauth_client=oauth_client,
                      reply_to=reply_to, text=text, left_link=left_link,
                      right_link=right_link, is_poll=is_poll,region_name=region_name,
                      app_id=app_id, is_push_only=is_push_only,
                      ignore_permission=ignore_permission)

    increment_count_out(yo.sender)
    clear_get_yos_sent_cache(yo.sender)

    if recipients:
        recipient_ids = [r.user_id for r in recipients]
    else:
        recipient_ids = None

    if not disable_send:
        if not broadcast and len(recipient_ids) == 1:
            _send_yo(yo_id=yo.yo_id,
                     recipient_ids=recipient_ids,
                     reply_to=reply_to)
        else:
            _send_yo.delay(yo_id=yo.yo_id,
                           recipient_ids=recipient_ids,
                           reply_to=reply_to)

    _apply_callback.delay(yo.yo_id)

    # Return Yo so we can pass the yo_id back to the client.
    return yo


def upsert_yo_contact(yo, contact_name=None):
    # Don't upsert contact if sending on behalf of someone else.
    if yo.sender == g.identity.user and yo.recipient:
        contact, is_first_yo = upsert_contact(yo.sender, yo.recipient,
                                              last_yo=yo,
                                              contact_name=contact_name)
        return contact, is_first_yo
    else:
        return None, False


def send_yo_with_token(yo_token):
    """Sends a yo using a valid YoToken
    
    This function is not currently being used. (11 June 2015) 
    """

    assert_valid_yo_token(yo_token)

    yo = construct_yo(recipients=[yo_token.recipient], yo_token=yo_token)
    endpoint_support_dict = {
        'handles_any_text': True,
        'handles_long_text': True,
        'handles_response_category': True,
        'is_legacy': False
    }
    yo_payload = YoPayload(yo, endpoint_support_dict)
    yo_payload.legacy_enabled = False
    yo_payload.must_handle_any_text = True
    yo_payload.supported_platforms = [IOS, IOSBETA, IOSDEV]

    load_identity(yo_token.recipient.user_id)
    _send_notification_to_user(yo_token.recipient, yo_payload)

    return yo
