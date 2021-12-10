# -*- coding: utf-8 -*-

"""Account management endpoints."""

import md5
from datetime import datetime, timedelta
import sys

import emoji
from flask import request, g, current_app
from ..accounts import get_user, upsert_pseudo_user, record_get_me_location, update_user
from ..constants.limits import *
from ..contacts import get_followers_count
from ..core import limiter, twilio, mixpanel_yostatus, mixpanel_yoapp
from ..errors import APIError
from ..forms import BroadcastYoForm, YoFromApiAccountForm, SendYoForm
from ..helpers import make_json_response, get_image_url
from ..models import Yo, User
from ..notification_endpoints import endpoint_from_useragent, get_user_endpoints, IOS
from ..permissions import assert_account_permission
from twilio import twiml
from yoapi.blueprints import status
from yoapi.blueprints.polls import route_polls_reply
from yoapi.constants.yos import UNREAD_YOS_FETCH_LIMIT
from yoapi.groups import get_group_contacts
from yoapi.models.push_app import PushApp
from yoapi.notifications import send_push_with_text
from yoapi.status import update_status
from ..yoflask import Blueprint
from ..core import cache
from ..models.payload import YoPayload
from ..yos.helpers import acknowledge_yo_received, favorite_yo, send_slack_msg
from ..yos.queries import (get_broadcasts, get_favorite_yos, get_unread_yos,
                           get_yo_count, get_yo_by_id, get_unread_polls)
from ..yos.send import send_yo, upsert_yo_contact, send_response_yo



# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name


# Instantiate a YoFlask customized blueprint that supports JWT authentication.
yos_bp = Blueprint('yo', __name__, url_prefix='/rpc')


def get_limit_key():
    """Gets the key for the rate limiter."""
    # TODO: refactor to find a better way to handle this
    if request.method == 'OPTIONS':
        key = ''
    elif g.identity.user:
        to_username = request.json.get('to') or request.json.get('username')
        key = 'yo:%s:%s' % (g.identity.user.username, to_username)
    else:
        raise APIError(
            'User does not have permissions for this request', status_code=401)
    return str(key)


def get_yoall_link_key():
    """Gets the key for the rate limiter."""
    # TODO: refactor to find a better way to handle this
    if request.method == 'OPTIONS':
        key = ''
    elif g.identity.user:
        link = request.json.get('link')
        if link:
            link_hash = md5.new(link).hexdigest()
            from_username = request.json.get('username', g.identity.user.username)
            key = 'yoall:%s%s' % (from_username, link_hash)
        else:
            key = ''
    else:
        raise APIError(
            'User does not have permissions for this request', status_code=401)
    return str(key)


def get_yoall_key():
    """Gets the key for the rate limiter."""
    # TODO: refactor to find a better way to handle this
    if request.method == 'OPTIONS':
        key = ''
    elif g.identity.user:
        from_username = request.json.get('username', g.identity.user.username)
        key = 'yoall:%s' % from_username
    else:
        raise APIError(
            'User does not have permissions for this request', status_code=401)
    return str(key)


def get_yoall_limit():
    """Returns the limit string for the authenticated user"""
    if request.method == 'OPTIONS':
        return ''

    if (hasattr(g, 'identity') and hasattr(g.identity, 'user') and
            g.identity.user and g.identity.user.yoall_limits):
        return g.identity.user.yoall_limits

    return YOALL_LIMITS


def get_yoall_link_limit():
    """Returns the limit string based on whether or not the broadcast
    contains a link

    As of July 1 2015 it has been a while since we used this.
    """

    if request.method == 'OPTIONS':
        return ''

    if request.json.get('link'):
        if (hasattr(g, 'identity') and hasattr(g.identity, 'user') and
                g.identity.user and g.identity.user.yoall_limits):
            return g.identity.user.yoall_limits

        return YOALL_LINK_LIMITS
    else:
        return ''


@limiter.limit(get_yoall_limit, key_func=get_yoall_key,
               error_message=YO_LIMIT_ERROR_MSG)
@yos_bp.route('/yo_all')
def route_yo_all():
    """The same as `broadcast_from_api`"""
    return route_broadcast_from_api_account()


@limiter.limit(get_yoall_limit, key_func=get_yoall_key,
               error_message=YO_LIMIT_ERROR_MSG)
@yos_bp.route('/yoall')
def route_yoall():
    """The same as `broadcast_from_api`"""
    return route_broadcast_from_api_account()


@limiter.limit(get_yoall_limit, key_func=get_yoall_key,
               error_message=YO_LIMIT_ERROR_MSG)
@yos_bp.route('/broadcast_from_api_account')
def route_broadcast_from_api_account():
    """Sends a Yo!

    We can defer sender lookup to the Yo class since it should be obtained
    from the request context. Requiring an authenticated user reduces the
    likelihood of accidental impersonation of senders.
    """
    form_args = request.json
    form = BroadcastYoForm.from_json(form_args)
    form.validate()

    if form.username.data:
        from_user = get_user(form.username.data)
        assert_account_permission(from_user,
                                  'No permission to send Yo from this account')
    else:
        from_user = g.identity.user

    cover = request.json.get('cover')
    photo = request.json.get('photo')
    response_pair = request.json.get('response_pair')
    text = request.json.get('text')
    left_link = request.json.get('left_link')
    right_link = request.json.get('right_link')

    yo = send_yo(sender=from_user, broadcast=True,
                 sound=form.sound.data, link=form.link.data,
                 location=form.location.data, header=form.header.data,
                 yo_id=form.yo_id.data, context=form.context.data,
                 cover=cover, photo=photo, text=text, response_pair=response_pair,
                 left_link=left_link, right_link=right_link)

    return make_json_response({'success': True, 'yo_id': yo.yo_id})


@limiter.limit(get_yoall_limit, key_func=get_yoall_key,
               error_message=YO_LIMIT_ERROR_MSG)
@yos_bp.route('/test_queue')
def route_test_queue():
    send_slack_msg.delay()
    return make_json_response({'success': True})


@yos_bp.route('/get_unread_yos', pseudo_forbidden=False)
def route_get_unread_yos():
    """Get unread yos for a user.

    Note that if no username argument is passed, then favorites
    from the currently authenticated user will be returned.
    """
    # Check for explicit target username before using the currently
    # authenticated user.
    username = request.json.get('username')
    if username:
        user = get_user(username)
    else:
        user = g.identity.user

    if not user:
        raise APIError('Can\'t yos without specifying a user')

    try:
        count = int(request.json.get('count'))
        count = count if count > 0 else UNREAD_YOS_FETCH_LIMIT
    except:
        count = UNREAD_YOS_FETCH_LIMIT

    if request.headers.get('X-APP-ID'):
        app_id = request.headers.get('X-APP-ID')
    else:
        app_id = None

    yos = get_unread_yos(user,
                         limit=count,
                         age_limit=timedelta(days=-2),
                         app_id=app_id)

    results = []
    endpoint = endpoint_from_useragent(request)
    if endpoint.platform and not 'polls' in request.user_agent.string:
        endpoint_support_dict = endpoint.get_payload_support_dict()
    else:
        endpoint_support_dict = endpoint.perfect_payload_support_dict()

    last_yo_type = None
    last_yo_header = None
    for yo in yos:
        payload = YoPayload(yo, endpoint_support_dict)
        category = payload.category
        apns_payload = payload.get_apns_payload()
        apns_payload.update({'status': yo.status,
                             'category': category})

        if yo.sender:
            sender_object = apns_payload.get('sender_object')
            sender_photo = get_image_url(yo.sender.photo)
            sender_object.update({'photo_url': sender_photo})

        # aps is not needed.
        apns_payload.pop('aps', None)
        results.append(apns_payload)

        if not last_yo_type:
            last_yo_type = payload.payload_type
        if not last_yo_header:
            last_yo_header = payload.get_push_text()

    if g.identity.user.is_pseudo and g.identity.auth_type == 'API':
        current_app.log_analytics({'event': 'pseudo_user_login',
                                   'phone': g.identity.user.phone,
                                   'last_yo_type': last_yo_type,
                                   'last_yo_header': last_yo_header})

    return make_json_response(unread_yos=results)


@yos_bp.route('/get_yo', pseudo_forbidden=False)
def route_get_yo():
    username = request.json.get('username')
    if username:
        user = get_user(username)
    else:
        user = g.identity.user

    if not user:
        raise APIError('Can\'t yos without specifying a user')

    yo = get_yo_by_id(request.json.get('yo_id'))
    yo.reload()
    endpoint = endpoint_from_useragent(request)
    endpoint_support_dict = endpoint.perfect_payload_support_dict()
    payload = YoPayload(yo, endpoint_support_dict)
    category = payload.category
    apns_payload = payload.get_apns_payload()
    apns_payload.update({'status': yo.status,
                         'category': category})

    if yo.sender:
        sender_object = apns_payload.get('sender_object')
        sender_photo = get_image_url(yo.sender.photo)
        sender_object.update({'photo_url': sender_photo})

    if yo.thumbnail_url:
        apns_payload.update({'thumbnail': yo.thumbnail_url})

    if yo.text:
        apns_payload.update({'text': yo.text})

    if yo.left_replies_count:
        apns_payload.update({'left_replies_count': yo.left_replies_count})

    if yo.right_replies_count:
        apns_payload.update({'right_replies_count': yo.right_replies_count})

    if yo.left_reply:
        apns_payload.update({'left_reply': yo.left_reply})

    if yo.right_reply:
        apns_payload.update({'right_reply': yo.right_reply})

    if yo.question:
        apns_payload.update({'question': yo.question})

    # aps is not needed.
    apns_payload.pop('aps', None)

    return make_json_response(apns_payload)


@yos_bp.route('/get_favorite_yos')
def route_get_favorite_yos():
    """Get favorite yos for a user.

    Note that if no username argument is passed, then favorites
    from the currently authenticated user will be returned.
    """
    # Check for explicit target username before using the currently
    # authenticated user.
    username = request.json.get('username')
    if username:
        user = get_user(username)
    else:
        user = g.identity.user

    if not user:
        raise APIError('Can\'t yos without specifying a user')

    yos = get_favorite_yos(user)
    yos = [yo.get_flattened_dict() for yo in yos]
    return make_json_response(favorites=yos)


@yos_bp.route('/get_broadcasts')
def route_get_broadcasts():
    """Returns broadcast yos by a user.

    Note: that if no username argument is passed, then broadcasts
    from the currently authenticated user will be returned.
    Because this is mainly used for the dashboard only broadcasts
    with links are returned.
    """
    # Check for explicit target username before using the currently
    # authenticated user.
    username = request.json.get('username')
    if username:
        user = get_user(username)
    else:
        user = g.identity.user

    if not user:
        raise APIError('Can\'t list broadcasts without specifying a user')

    yos = get_broadcasts(user)
    response_dict = [yo.get_flattened_dict() for yo in yos]
    return make_json_response(yos=response_dict)


@yos_bp.route('/list_broadcasted_links')
def route_list_broadcasted_links():
    """List links broadcasted by a user.

    Note that if no username argument is passed, then broadcasted links
    from the currently authenticated user will be returned.
    """
    # Check for explicit target username before using the currently
    # authenticated user.
    username = request.json.get('username')
    if username:
        user = get_user(username)
    else:
        user = g.identity.user

    if not user:
        raise APIError('Can\'t list broadcasts without specifying a user')

    yos = get_broadcasts(user)
    follower_count = get_followers_count(user)
    # TODO: this response should use standard lower case variables with
    # underscores. This change requires the dashboard be updated at the
    # same time.
    response_dict = []
    for yo in yos:
        date_str = datetime.fromtimestamp(int(yo.created) / 1e6).strftime(
            '%Y-%m-%dT%H:%M:%S.%fZ')
        response_dict.append({
            'createdAt': date_str,
            'link': yo.short_link,
            'from': yo.sender.username,
            'originalLink': yo.link,
            'objectId': yo.id,
            'updatedAt': date_str,
            'subscribersCount': follower_count,
            'sentCount': yo.sent_count or 0,
            'toCount': yo.recipient_count or 0})
    return make_json_response(links=response_dict)


@yos_bp.route('/user_yo_count')
def route_user_yo_count():
    return make_json_response(count=get_yo_count(g.identity.user))


@limiter.limit(YO_LIMITS, key_func=get_limit_key,
               error_message=YO_LIMIT_ERROR_MSG)
@yos_bp.route('/yo', login_required=True, pseudo_forbidden=False)
def route_yo(oauth_client=None):
    """Sends a Yo!

    We can defer sender lookup to the Yo class since it should be obtained
    from the request context. Requiring an authenticated user reduces the
    likelihood of accidental impersonation of senders.

    Creating pseudo users is handled here. It should be limited to only 
    users on the app, as soon as we figure out how to do that.
    """

    if 'polls' in request.user_agent.string.lower():
        return route_polls_reply()

    if 'status' in request.user_agent.string.lower():
        return status.route_reply()

    # TODO: since we weren't recording udids at signup
    # record it here if provided. In the future this needs
    # to be removed as it can pose a security risk.
    user = g.identity.user
    phone = request.json.get('phone_number')
    recipients = request.json.get('to') or request.json.get('username')
    if phone and not recipients:
        to_user = upsert_pseudo_user(phone)
        recipients = to_user.username if to_user else None

    form_args = {'context': request.json.get('context') or None,
                 'header': request.json.get('header') or None,
                 'link': request.json.get('link') or None,
                 'location': request.json.get('location') or None,
                 'recipients': recipients,
                 'sound': request.json.get('sound'),
                 'yo_id': request.json.get('yo_id') or None
    }

    form = SendYoForm.from_json(form_args)
    form.validate()

    cover = request.json.get('cover')
    photo = request.json.get('photo')
    context_id = request.json.get('context_identifier')
    reply_to = request.json.get('reply_to')
    response_pair = request.json.get('response_pair')
    text = request.json.get('text')
    left_link = request.json.get('left_link')
    right_link = request.json.get('right_link')
    is_poll = request.json.get('is_poll')
    region_name = request.json.get('region_name')
    is_push_only = request.json.get('is_push_only')

    if request.headers.get('X-APP-ID'):
        app_id = request.headers.get('X-APP-ID')
        sound = 'no.mp3'
    else:
        app_id = 'co.justyo.yoapp'
        sound = form.sound.data

    yo = send_yo(sender=user, recipients=form.recipients.data,
                 sound=sound, link=form.link.data,
                 location=form.location.data, header=form.header.data,
                 yo_id=form.yo_id.data, context=form.context.data,
                 cover=cover, photo=photo, context_id=context_id,
                 reply_to=reply_to, response_pair=response_pair,
                 oauth_client=oauth_client, text=text,
                 left_link=left_link, right_link=right_link,
                 is_poll=is_poll, region_name=region_name,
                 app_id=app_id, is_push_only=is_push_only)

    contact, is_first_yo = upsert_yo_contact(yo)

    #if context_id:
    #    mixpanel_yoapp.track(yo.recipient.user_id, 'Yo Sent', {'Type': context_id})

    # Send response yo if needed.
    # NOTE: By leaving this as-is groups are allowed to send
    # welcome links.
    if reply_to is None:
        if is_first_yo and yo.recipient.welcome_link:
            send_response_yo.delay(yo.yo_id, use_welcome_link=True)
        elif yo.should_trigger_response():
            send_response_yo.delay(yo.yo_id)

    response = {'success': True, 'yo_id': yo.yo_id}
    if yo.recipient:
        recipient_dict = yo.recipient.get_public_dict(contact.get_name())
        response.update({'recipient': recipient_dict})

    if yo.not_on_yo:
        response.update({'not_on_yo': yo.not_on_yo})

    return make_json_response(response)


@limiter.limit(YO_LIMITS, key_func=get_limit_key,
               error_message=YO_LIMIT_ERROR_MSG)
@yos_bp.route('/yo_from_api_account', login_required=True,
              pseudo_forbidden=False)
def route_yo_from_api_account():
    """Sends a Yo!

    We can defer sender lookup to the Yo class since it should be obtained
    from the request context. Requiring an authenticated user reduces the
    likelihood of accidental impersonation of senders.
    """
    # Don't use the 'username' field for recipients in this endpoint.
    recipients = request.json.get('to')

    form_args = {'context': request.json.get('context') or None,
                 'header': request.json.get('header') or None,
                 'link': request.json.get('link') or None,
                 'location': request.json.get('location') or None,
                 'recipients': recipients,
                 'sender': request.json.get('username'),
                 'sound': request.json.get('sound'),
                 'yo_id': request.json.get('yo_id') or None}

    form = YoFromApiAccountForm.from_json(form_args)

    form.validate()

    from_username = form.sender.data
    from_user = get_user(from_username)
    assert_account_permission(from_user,
                              'No permission to send Yo from this account')

    cover = request.json.get('cover')
    photo = request.json.get('photo')
    response_pair = request.json.get('response_pair')
    text = request.json.get('text')
    left_link = request.json.get('left_link')
    right_link = request.json.get('right_link')
    region_name = request.json.get('region_name')

    yo = send_yo(sender=from_user, recipients=form.recipients.data,
                 sound=form.sound.data, link=form.link.data,
                 location=form.location.data, header=form.header.data,
                 yo_id=form.yo_id.data, context=form.context.data,
                 cover=cover, photo=photo, text=text, response_pair=response_pair,
                 left_link=left_link, right_link=right_link,
                 region_name=region_name)

    upsert_yo_contact(yo)

    dic = {
        'id': yo.id,
        'created_at': yo.created,
        'text': yo.text,
        'category': yo.response_pair,
        'left_reply': yo.left_reply,
        'right_reply': yo.right_reply,
        'question': yo.question
    }

    return make_json_response({'success': True,
                               'yo_id': yo.yo_id,
                               'yo': dic})


@yos_bp.route('/yo_ack', login_required=True, pseudo_forbidden=False)
def route_yo_ack():
    """Acknowledges a yo has been opened by a particular user"""

    yo_id = request.json.get('yo_id')
    yo_ids = request.json.get('yo_ids', [])
    status = request.json.get('status', 'received')
    from_push = request.json.get('from_push', False)
    user = g.identity.user

    if 'polls' in request.user_agent.string:
        if not user.is_done_polls_onboarding:
            user.is_done_polls_onboarding = True
            update_user(user=user, ignore_permission=True, is_done_polls_onboarding=True)

    if yo_id:
        yo_ids.append(yo_id)

    for yo_id in yo_ids:
        acknowledge_yo_received(yo_id, status=status, from_push=from_push)

    return make_json_response()


@yos_bp.route('/favorite_yo', login_required=True)
def route_favorite_yo():
    """Favorite a yo"""

    user = g.identity.user
    yo_id = request.json.get('yo_id')
    if not yo_id:
        raise APIError('Must provide yo_id')
    favorite_yo(user.user_id, yo_id)

    return make_json_response()


@yos_bp.route('/unfavorite_yo', login_required=True)
def route_unfavorite_yo():
    """unfavorite a yo"""

    user = g.identity.user
    yo_id = request.json.get('yo_id')
    if not yo_id:
        raise APIError('Must provide yo_id')
    favorite_yo(user.user_id, yo_id, favorite=False)

    return make_json_response()


@yos_bp.route('/get_interactive_yos', login_required=True)
def route_get_interactive_yos():
    from_username = request.json.get('username')
    from_user = get_user(from_username)
    assert_account_permission(from_user,
                              'No permission for this account')

    interactive_yos = Yo.objects.filter(sender=from_user, response_pair__exists=True).order_by('-_id').limit(10)
    public_data_only = []
    for item in interactive_yos:
        yo = get_yo_by_id(item.yo_id)
        replies_texts = yo.response_pair.split('.')
        left_reply_text = replies_texts[0]
        right_reply_text = replies_texts[1]
        reply_count = Yo.objects.filter(reply_to=yo).count()
        left_reply_count = Yo.objects.filter(reply_to=yo, text=left_reply_text).count()
        right_reply_count = Yo.objects.filter(reply_to=yo, text=right_reply_text).count()

        public_data_only.append({
            'id': yo.id,
            'created_at': yo.created,
            'text': yo.text,
            #'file_id': item.file_id,
            'reply_count': reply_count,
            'left_reply_text': left_reply_text,
            'left_reply_count': left_reply_count,
            'right_reply_text': right_reply_text,
            'right_reply_count': right_reply_count,
        })
    return make_json_response({'results': public_data_only})


@yos_bp.route('/get_polls', login_required=True)
def route_get_polls():
    username = request.json.get('username')
    app_id = request.json.get('app_id')

    if username:
        from_user = get_user(username=username)
        polls = Yo.objects.filter(sender=from_user, is_poll=True).order_by('-_id').limit(10)
    elif app_id:
        app = PushApp.objects.get(id=app_id)
        from_user = get_user(username=app.username)
        polls = Yo.objects.filter(sender=from_user, is_poll=True).order_by('-_id').limit(10)
    else:
        raise APIError('Please provide app id or username', status_code=400)

    public_data_only = []
    for poll in polls:

        left_replies_count = poll.left_replies_count or 0
        right_replies_count = poll.right_replies_count or 0

        public_data_only.append({
            'id': poll.id,
            'created_at': poll.created,
            'text': poll.text,
            'category': poll.response_pair,
            'reply_count': left_replies_count + right_replies_count,
            'left_reply': poll.left_reply,
            'left_replies_count': left_replies_count,
            'right_reply': poll.right_reply,
            'right_replies_count': right_replies_count,
            'question': poll.question,
        })
    return make_json_response({'results': public_data_only})


@yos_bp.route('/get_poll_replies', login_required=True)
def route_get_poll_replies():
    poll_id = request.json.get('yo_id')
    poll = get_yo_by_id(poll_id)
    replies = Yo.objects.filter(reply_to=poll_id).order_by('created').limit(50)

    results = []
    for reply in replies:
        dic = {
            'created_at': reply.created,
            'sender_object': {
                'username': reply.sender.username,
                'display_name': reply.sender.display_name,
                'city': reply.sender.city or reply.sender.region
            },
            'text': poll.left_reply if reply.text == poll.response_pair.split('.')[0] else poll.right_reply
        }

        results.append(dic)

    return make_json_response(results=results)


@yos_bp.route('/get_recent_polls', login_required=True)
def route_get_recent_polls():
    user = g.identity.user
    if not user:
        raise APIError('Can\'t yos without specifying a user')

    record_get_me_location(user)

    if not user.is_done_polls_onboarding:
        raise APIError('Hotfix')

    try:
        count = int(request.json.get('count'))
        count = count if count > 0 else UNREAD_YOS_FETCH_LIMIT
    except:
        count = UNREAD_YOS_FETCH_LIMIT

    yos = get_unread_polls(user, limit=count, age_limit=None)
    results = []
    endpoint = endpoint_from_useragent(request)
    endpoint_support_dict = endpoint.perfect_payload_support_dict()

    for yo in yos:
        try:
            payload = YoPayload(yo, endpoint_support_dict)
            category = payload.category
            apns_payload = payload.get_apns_payload()
            apns_payload.update({'status': yo.status,
                                 'category': category})

            apns_payload.pop('aps', None)
            results.append(apns_payload)
        except:
            current_app.log_exception(sys.exc_info())

    return make_json_response({'results': results})


@yos_bp.route('/send_to_all_flashpolls_users', login_required=True)
def route_send_to_all_flashpolls_users():
    from_username = request.json.get('username')
    text = request.json.get('text')

    from_user = get_user(from_username)
    assert_account_permission(from_user, 'No permission for this account')

    #flashpolls_users = User.objects.filter(is_guest=True, username='GUEST095679')
    flashpolls_users = User.objects.filter(is_guest=True)

    yo = send_yo(sender=from_user, recipients=flashpolls_users, text=text, response_pair='👎.👍')

    return make_json_response({'success': True, 'yo_id': yo.yo_id})


@yos_bp.route('/request_status', login_required=True)
def route_request_status():
    src_user = g.identity.user
    src_user = get_user(user_id=src_user.user_id)  # to reload object
    dst_username = request.json.get('username')
    target_user = get_user(dst_username)
    phone = target_user.phone

    if src_user.display_name:
        name = src_user.display_name
    else:
        name = src_user.username

    if phone:
        cache.cache.set('yo.status.request.sender.name:' + phone, name, 999)
        cache.cache.set('yo.status.request.target.username:' + phone, dst_username, 999)

    cache.cache.set('yo.status.request.sender.username:' + dst_username, src_user.username, 999)

    endpoints = get_user_endpoints(target_user, 'co.justyo.yostatus', ignore_permissions=True)

    if len(endpoints) == 0:

        message = u'{0}\'s emoji status is {1}. They\'ve just requested your status.' \
                  u' reply here with single emoji to set yours'.format(
            name,
            src_user.status
        )
        twilio.send(phone, message, sender='+14152369198')

        mixpanel_yostatus.track(src_user.user_id, 'Sent SMS Status Request')
        mixpanel_yostatus.track(target_user.user_id, 'Received SMS Status Request')

    else:

        for endpoint in endpoints:

            if endpoint.os_version and endpoint.os_version.startswith('9'):

                message = '{} asked for your status. reply here with a single emoji'.format(name)

            else:

                message = '{} asked for your current status.'.format(name)

            send_push_with_text(endpoint=endpoint, text=message, user_info={'event_type': 'status.request'})

            mixpanel_yostatus.track(src_user.user_id, 'Sent Push Status Request')
            mixpanel_yostatus.track(target_user.user_id, 'Received Push Status Request')

    return make_json_response({'success': True})


@yos_bp.route('/incoming_yo_status', login_required=False)
def route_incoming_yo_status():

    from_number = request.form.get('From')
    if from_number == '+14152369198':
        return
    body = request.form.get('Body').strip()

    is_valid_emoji = emoji.demojize(body) != body
    if not is_valid_emoji:

        sender_name = cache.cache.get('yo.status.request.sender.name:' + from_number)

        if sender_name:

            message = u'Your friend {} has asked for your status. Reply with a single emoji here or get the app ' \
                      u'here {}'.format(
            sender_name,
            u'https://yostat.us/')
            twilio.send(from_number, message, sender='+14152369198')

        else:

            message = u'To set your status reply with a single emoji here or get the app ' \
                      u'here {}'.format(
            u'https://yostat.us/')
            twilio.send(from_number, message, sender='+14152369198')

    else:

        try:

            target_username = cache.cache.get('yo.status.request.target.username:' + from_number)
            if not target_username:

                message = u'To set your status reply with a single emoji here or get the app ' \
                          u'here {}'.format(
                u'https://yostat.us/')
                twilio.send(from_number, message, sender='+14152369198')

            else:

                src_user = get_user(target_username)
                update_status(src_user, body)

                message = u'Great! Your Yo Status is now {}. download Yo Status app to see your friends\' statuses: {}'.format(
                    body,
                    u'https://yostat.us/'
                )
                twilio.send(from_number, message, sender='+14152369198')

        except Exception as e:

                if target_username:
                    message = u'Your friend {} has asked for your status. You can reply with a single emoji here or get the app ' \
                              u'here {}'.format(
                                target_username,
                                u'https://yostat.us/')
                else:
                    message = u'Your friend has asked for your status. You can reply with a single emoji here or get the app ' \
                              u'here {}'.format(
                                u'https://yostat.us/')
                twilio.send(from_number, message, sender='+14152369198')

    resp = twiml.Response()
    return str(resp)