# -*- coding: utf-8 -*-
from flask import request, g
from yoapi.accounts import update_user, get_user
from yoapi.blueprints.contacts import route_add_contact, route_delete
from yoapi.constants.emojis import REVERSE_EMOJI_MAP, EMOJI_RE, UNESCAPED_EMOJI_MAP
from yoapi.contacts import get_contacts_with_status, get_contact_pair, _get_follower_contacts
from yoapi.core import cache, log_to_slack
from yoapi.errors import APIError
from yoapi.helpers import make_json_response, get_usec_timestamp
from yoapi.jsonp import jsonp
from yoapi.models import User
from yoapi.models.status import Status
from yoapi.notification_endpoints import get_user_endpoints
from yoapi.notifications import send_push_with_text
from yoapi.status import update_status, process_push_confirmation_reply
from yoapi.yoflask import Blueprint
from yoapi.yos.queries import get_yo_by_id

status_bp = Blueprint('status', __name__)


@status_bp.route('/status/me/history/', methods=['GET'], pseudo_forbidden=False)
@status_bp.route('/status/me/history', methods=['GET'], pseudo_forbidden=False)
def route_history():

    user = g.identity.user
    if request.json.get('distinct'):
        emojis = []
        statuses = Status.objects.filter(user=user).order_by('-created')
        for status in statuses:
            if status.status not in emojis:
                emojis.append(status.status)
        return make_json_response(results=emojis)
    else:
        statuses = Status.objects.filter(user=user).order_by('-created')
    statuses_public = [status.get_public_dict() for status in statuses]

    return make_json_response(results=statuses_public)



@status_bp.route('/status/me/contacts/', methods=['GET', 'POST', 'DELETE'], pseudo_forbidden=False)
@status_bp.route('/status/me/contacts', methods=['GET', 'POST', 'DELETE'], pseudo_forbidden=False)
def route_status_contacts():

    if request.method == 'GET':

        user = g.identity.user

        contact_objects = get_contacts_with_status(user)

        user_dicts = []
        is_self_in_list = False
        for c in contact_objects:
            if c.target.user_id == user.user_id:
                is_self_in_list = True
            user_dicts.append(c.target.get_public_dict(c.contact_name))

        if not is_self_in_list:
            user_dicts.append(user.get_public_dict())

        user_dicts = sorted(user_dicts, key=lambda user_dict: user_dict.get('status_last_updated'), reverse=True)

        return make_json_response(results=user_dicts)

    elif request.method == 'POST':
        return route_add_contact()

    elif request.method == 'DELETE':
        return route_delete()


@status_bp.route('/status/friends/', methods=['POST'], pseudo_forbidden=False)
@status_bp.route('/status/friends', methods=['POST'], pseudo_forbidden=False)
def route_status_friends():

    user = g.identity.user

    contact_objects = get_contacts_with_status(user)

    user_dicts = []
    is_self_in_list = False
    for c in contact_objects:
        if c.target.user_id == user.user_id:
            is_self_in_list = True
        user_dicts.append(c.target.get_public_dict(c.contact_name))

    if not is_self_in_list:
        user_dicts.append(user.get_public_dict())

    user_dicts = sorted(user_dicts, key=lambda user_dict: user_dict.get('status_last_updated'), reverse=True)

    return make_json_response(results=user_dicts)


@status_bp.route('/status/sha1/u/<sha1_username>', methods=['GET'], login_required=False)
@status_bp.route('/status/sha1/u/<sha1_username>/', methods=['GET'], login_required=False)
@jsonp
def route_sha1_username_status(sha1_username):

    user = get_user(sha1_username=sha1_username, ignore_permission=True)
    return make_json_response({'status': user.status})


@status_bp.route('/status/', methods=['GET', 'POST'], login_required=False)
@status_bp.route('/status', methods=['GET', 'POST'], login_required=False)
def route_status():

    user = g.identity.user
    if request.method == 'GET':

        if not request.json.get('username'):
            raise APIError('Missing username parameter')

        username = request.args.get('username')
        user = get_user(username)
        return make_json_response({'status': user.status})

    elif request.method == 'POST':

        if not user:
            raise APIError('Unauthorized', status_code=401)

        update_status(user, request.json.get('status'), request.json.get('status_hex'))

        return make_json_response({'status': user.status})


@status_bp.route('/status/<username>/', methods=['GET'], login_required=False)
@status_bp.route('/status/<username>', methods=['GET'], login_required=False)
def route_get_status(username):
    if ',' in username:
        usernames = username.split(',')
        results = []
        for username in usernames:
            try:
                user = get_user(username=username)
                results.append({
                    'username': user.username,
                    'display_name': user.display_name,
                    'status': user.status,
                    'status_last_updated': user.status_last_updated
                })
            except:
                continue

        return make_json_response({'results': results})
    else:
        user = get_user(username=username)
        return make_json_response({
            'username': user.username,
            'display_name': user.display_name,
            'status': user.status,
            'status_last_updated': user.status_last_updated
        })


@status_bp.route('/reply/', methods=['GET', 'POST'])
@status_bp.route('/reply', methods=['GET', 'POST'])
def route_reply():

    user = g.identity.user

    if request.json.get('to') == 'YOSTATUS':  # iOS 8 hotfix

        original_yo_id = request.json.get('reply_to')
        original_yo = get_yo_by_id(original_yo_id)

        if original_yo.user_info.get('type') == 'push.confirmation':

            push_originator = get_user(user_id=original_yo.user_info.get('owner'))
            reply_text = request.json.get('context')
            did_approve = reply_text == u'👍'

            process_push_confirmation_reply(reply_sender=user,
                                            push_originator=push_originator,
                                            did_approve=did_approve)

            return make_json_response({})

    if request.json.get('user_info') and \
                    request.json.get('user_info').get('type') == 'push.confirmation':

        owner_id = request.json.get('user_info').get('owner')
        push_originator = get_user(user_id=owner_id)
        reply_text = request.json.get('text')
        did_approve = 'yes' in reply_text.lower()

        process_push_confirmation_reply(reply_sender=user,
                                        push_originator=push_originator,
                                        did_approve=did_approve)

        return make_json_response({})

    elif request.json.get('user_info') == 'request_status' or \
            request.json.get('user_info') and request.json.get('user_info').get('event_type') == 'status.request':
        status = request.json.get('text')
        user = g.identity.user

        update_status(user, status)

        endpoints = get_user_endpoints(user, 'co.justyo.yostatus', ignore_permissions=True)
        for endpoint in endpoints:
            send_push_with_text(endpoint=endpoint,
                                text='Your status is now: ' + status,
                                category='')

        return make_json_response({})

    sender = g.identity.user

    if not request.json.get('text'):
        raise APIError('Missing "text" parameter')

    target_id = request.json.get('target_id')
    if target_id:
        user_id = get_user(user_id=target_id)
    else:
        user_id = request.json.get('user_info').get('user').get('id')

    target_user = get_user(user_id=user_id)

    text = request.json.get('text')

    try:
        contact_pair = get_contact_pair(target_user, sender)
        name = contact_pair.contact_name
    except:
        pass

    if not name:
        name = sender.display_name

    message = u'{}: {}'.format(name, text)

    log_to_slack('{} {}'.format(user.username, message))

    endpoints = get_user_endpoints(target_user, 'co.justyo.yostatus', ignore_permissions=True)
    for endpoint in endpoints:
        send_push_with_text(endpoint=endpoint, text=message, user_info={'user': {
            'id': sender.user_id
        }})

    return make_json_response({})


@status_bp.route('/reactions/', methods=['GET', 'POST'])
@status_bp.route('/reactions', methods=['GET', 'POST'])
def route_reactions():

    if not request.json.get('target_id'):
        raise APIError('Missing "target_id" parameter')

    if not request.json.get('text'):
        raise APIError('Missing "text" parameter')

    sender = g.identity.user
    if request.method == 'POST':

        target_id = request.json.get('target_id')
        target_user = get_user(user_id=target_id)

        text = request.json.get('text')

        name = None
        try:
            contact_pair = get_contact_pair(target_user, sender)
            name = contact_pair.contact_name
        except:
            pass

        if name is None:
            name = sender.display_name

            if name is None:
                name = sender.username

        message = u'{}: {}'.format(name, text)

        endpoints = get_user_endpoints(target_user, 'co.justyo.yostatus', ignore_permissions=True)
        for endpoint in endpoints:
            send_push_with_text(endpoint=endpoint, text=message)

        return make_json_response({})


@status_bp.route('/send_list', methods=['POST'])
def send_list():

    if request.json.get('username'):

        user = get_user(username=request.json.get('username'))

        contact_objects = get_contacts_with_status(user)
        short_list_statuses = []
        short_list_names = []
        for contact in contact_objects:
            if contact.target.username == user.username:
                continue

            if contact.contact_name:
                short_list_names.append(contact.contact_name)
            else:
                short_list_names.append(contact.target.display_name)

            short_list_statuses.append(contact.target.status)

            if len(short_list_statuses) >= 3:
                break

        text = u'You: {}\n{}: {}\n{}: {}\n{}: {}'.format(
                                    user.status,
                                    short_list_names[0], short_list_statuses[0],
                                    short_list_names[1], short_list_statuses[1],
                                    short_list_names[2], short_list_statuses[2],
                                )

        endpoints = get_user_endpoints(user, 'co.justyo.yostatus', ignore_permissions=True)
        for endpoint in endpoints:
            send_push_with_text(endpoint=endpoint,
                                text=text)

        return make_json_response({})


'''
@status_bp.route('/send_push', methods=['POST'])
def send_push():

    if request.json.get('username'):

        user = get_user(username=request.json.get('username'))
        text = u'In a single emoji - what are you up to?'

        endpoints = get_user_endpoints(user, 'co.justyo.yostatus', ignore_permissions=True)
        for endpoint in endpoints:
            send_push_with_text(endpoint=endpoint,
                                text=text)

    else:

        contact_objects = get_contacts_with_status(user)
        short_list_statuses = []
        short_list_names = []
        for contact in contact_objects:
            if contact.target.username == user.username:
                continue

            if contact.contact_name:
                short_list_names.append(contact.contact_name)
            else:
                short_list_names.append(contact.target.display_name)

            short_list_statuses.append(contact.target.status)

            if len(short_list_statuses) >= 3:
                break



        return make_json_response({})


'''
