# -*- coding: utf-8 -*-

"""Account management endpoints."""


from flask import jsonify, request, g
from datetime import timedelta

from ..contacts import (get_followers, get_contact_usernames, add_contact,
                        remove_contact, get_contact_objects, get_contacts,
                        find_contacts_by_facebook_ids, get_contact_pair,
                        block_contact, unblock_contact, hide_contact,
                        get_followers_count, get_blocked_contacts,
                        get_contacts_yo_status, invite_contact,
                        clear_get_contacts_cache, clear_get_followers_cache,
                        get_subscriptions, get_subscriptions_objects, get_contacts_with_status)
from ..accounts import (get_user, update_user, find_users_by_numbers,
                        upsert_pseudo_user, _get_user)
from ..errors import APIError
from ..forms import InviteContactForm
from ..helpers import make_json_response, get_usec_timestamp
from ..models import User
from ..notification_endpoints import get_useragent_profile, ANDROID
from ..notifications import announce_sign_up_to_contacts, send_push_to_user
from ..permissions import assert_account_permission
from yoapi.core import mixpanel_yostatus
from yoapi.models import Contact
from ..yoflask import Blueprint


# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name


# Instantiate a YoFlask customized blueprint that supports JWT authentication.
contacts_bp = Blueprint('contacts', __name__, url_prefix='/rpc')


@contacts_bp.route('/add_contact')
def route_add_contact_proxy():
    """Future proof endpoint for upcoming RPC name change"""
    return route_add_contact()


@contacts_bp.route('/add')
def route_add_contact():
    """Adds the specified user as a contact to the authenticated user

    In the earlier version of the API, this endpoint also sent the new contact
    a Yo. Going forward, we simply add the user to the list of contacts.
    """

    owner = g.identity.user
    contact_name = request.json.get('name') or None
    username = request.json.get('username')
    if username:
        username = username.strip()
    phone_number = request.json.get('phone_number')
    if username:
        target = get_user(username)
    elif phone_number:
        target = upsert_pseudo_user(phone_number)
    else:
        raise APIError('Expected phone_number or username')

    if 'status' in request.user_agent.string.lower():
        mixpanel_yostatus.track(owner.user_id, 'Added friend')
        mixpanel_yostatus.track(target.user_id, 'Was Added as a friend')

        if target.status is None:
            target.status = ' '
            target.save()

    # Make sure the owner hasn't been blocked by the target.
    if target.has_blocked(owner):
        raise APIError('Blocked by user.')

    is_first_time_adding = get_contact_pair(owner, target) is None

    add_contact(owner, target, contact_name)

    if is_first_time_adding:
        if 'status' in request.user_agent.string.lower():
            app_id = 'co.justyo.yostatus'
        else:
            app_id = 'co.justyo.yoapp'
        text = u'{} added you as a friend 💃👯'.format(owner.display_name)
        send_push_to_user(target, app_id, text)

    return make_json_response(added=target.get_public_dict(contact_name))


@contacts_bp.route('/block')
def route_block():
    user = g.identity.user
    target = get_user(request.json.get('username'), ignore_permission=True)
    block_contact(user, target)
    return make_json_response(blocked=target.username)


@contacts_bp.route('/count_subscribers')
def route_count_subscribers():
    username = request.json.get('username')
    if username:
        target = get_user(username)
        followers_count = get_followers_count(target)
    else:
        followers_count = get_followers_count(g.identity.user)
    return make_json_response(count=followers_count)


@contacts_bp.route('/remove_contact')
def route_delete_legacy():
    return route_delete()


@contacts_bp.route('/delete')
def route_delete():
    """Removes a contact from a user's contact list"""
    user = g.identity.user
    target = get_user(request.json.get('username'), ignore_permission=True)

    if get_useragent_profile(request).get('platform') == ANDROID:
        block_contact(user, target)
    else:
        hide_contact(user, target)

    return make_json_response()


@contacts_bp.route('/find_friends')
def route_find_friends():
    user = g.identity.user
    phone_numbers = request.json.get('phone_numbers')
    if not phone_numbers:
        raise APIError('No phone numbers supplied.', status_code=400)

    default_country_code = request.json.get('default_country_code')
    country_code_if_missing = user.country_code or default_country_code or '1'

    contacts = find_users_by_numbers(
        phone_numbers,
        country_code_if_missing=country_code_if_missing,
        user_phone=user.phone)

    # convert generator into a list
    contacts = [c for c in contacts]
    result = [{'username': user.username,
               'number': number,
               'display_name': user.display_name,
               'yo_count': user.yo_count,
               'last_seen': user.last_seen_time
               }
              for number, user in contacts]

    # If the user has not previously announced to their friends they are on Yo
    # send a silent yo to tell them.
    # Create a set of contact_ids to prevent duplicate notifications.
    user = g.identity.user
    is_beta = get_useragent_profile(request).get('is_beta')
    if not is_beta and user.first_name and user.last_name and not user.has_announced_signup:
        update_user(user, has_announced_signup=True)
        contact_ids = [c.user_id for _, c in contacts]
        contact_ids = list(set(contact_ids))
        is_yostatus = 'status' in request.user_agent.string
        announce_sign_up_to_contacts.delay(contact_ids, is_yostatus)

    return make_json_response(friends=result)

@contacts_bp.route('/find_facebook_friends')
def route_find_facebook_friends():
    user = g.identity.user
    facebook_ids = request.json.get('facebook_ids')
    if not facebook_ids:
        raise APIError('No Facebook ids supplied.', status_code=400)

    contacts = find_contacts_by_facebook_ids(facebook_ids)

    friends = []
    for facebook_id, friend in contacts:
        contact = get_contact_pair(user, friend)
        contact_name = contact.get_name() if contact else None
        user_public_dict = friend.get_public_dict(contact_name)
        user_public_dict.update({'facebook_id': facebook_id})
        friends.append(user_public_dict)

    return make_json_response(friends=friends)

@contacts_bp.route('/get_blocked_contacts')
def route_get_blocked_contacts():
    username = request.json.get('username')
    if username:
        user = get_user(username=username)
        assert_account_permission(user, 'No permission to access user.')
    else:
        user = g.identity.user
    contacts = get_blocked_contacts(user)
    return make_json_response(
        contacts=[contact.username
                  for contact in contacts])


@contacts_bp.route('/get_blocked_objects')
def route_get_blocked_objects():
    username = request.json.get('username')
    if username:
        user = get_user(username=username)
        assert_account_permission(user, 'No permission to access user.')
    else:
        user = g.identity.user
    contacts = get_blocked_contacts(user)
    results = []
    # get a contact_name if one exists
    for contact in contacts:
        if contact.is_service or contact.is_group:
            contact_object = None
        else:
            contact_object = get_contact_pair(user, contact)

        contact_name = None
        if contact_object:
            contact_name = contact_object.get_name()

        results.append(contact.get_public_dict(contact_name))

    return make_json_response(contacts=results)


@contacts_bp.route('/get_contacts', pseudo_forbidden=False)
def route_get_contacts():
    username = request.json.get('username')
    if username:
        user = get_user(username=username)
        assert_account_permission(user, 'No permission to access user.')
    else:
        user = g.identity.user
    contacts = get_contact_usernames(user)
    return make_json_response(contacts=contacts)


@contacts_bp.route('/list_contacts', pseudo_forbidden=False)
def route_list_contacts():
    username = request.json.get('username')
    if username:
        user = get_user(username=username)
        assert_account_permission(user, 'No permission to access user.')
    else:
        user = g.identity.user

    if request.json.get('status_only'):
        contact_objects = get_contacts_with_status(user)

        user_dicts = []
        for c in contact_objects:
            user_dicts.append(c.target.get_public_dict(c.contact_name))

        user_dicts = sorted(user_dicts, key=lambda user_dict: user_dict.get('status_last_updated'), reverse=True)

        return make_json_response(contacts=user_dicts)

    else:
        contacts = get_contacts(user)
        contacts = [c.target.get_public_dict(display_name=c.contact_name) for c in contacts]
        return make_json_response(contacts=contacts)


@contacts_bp.route('/get_subscriptions')
def route_get_subscriptions():
    username = request.json.get('username')
    if username:
        user = get_user(username=username)
        assert_account_permission(user, 'No permission to access user.')
    else:
        user = g.identity.user
    subscriptions = get_subscriptions(user)
    return make_json_response(subscriptions=subscriptions)


@contacts_bp.route('/get_subscriptions_objects')
def route_get_subscriptions_objects():
    username = request.json.get('username')
    if username:
        user = get_user(username=username)
        assert_account_permission(user, 'No permission to access user.')
    else:
        user = g.identity.user
    subscriptions = get_subscriptions_objects(user)
    subscriptions = [user.get_public_dict() for user in subscriptions]
    return make_json_response(subscriptions=subscriptions)


@contacts_bp.route('/get_followers')
def route_get_followers():
    # TODO: Remove this when we have a better way to allow
    # administrative access to mongodb
    username = request.json.get('username')
    if username:
        user = get_user(username=username)
        assert_account_permission(user, 'No permission to access user.')
    else:
        user = g.identity.user
    followers = get_followers(user)
    follower_usernames = [follower.username for follower in followers]
    return make_json_response(followers=follower_usernames)


@contacts_bp.route('/set_contacts')
def route_set_contacts():
    # TODO: deprecate this endpoint unless it will be needed for future functionality
    # Presently this is not implemented in the legacy api
    return make_json_response()


@contacts_bp.route('/get_contacts_status')
def route_get_contacts_status():
    username = request.json.get('username')
    if username:
        user = get_user(username=username)
        assert_account_permission(user, 'No permission to access user.')
    else:
        user = g.identity.user

    contacts = request.json.get('usernames')
    if contacts and not isinstance(contacts, list):
        raise APIError('Expected usernames to be a list')

    contacts = Contact.objects(owner=user,
                               hidden__exists=False,
                               target_username__exists=True,
                               last_yo_state__exists=True).order_by('-last_yo')

    public_results = [{
                      'status': contact.last_yo_state,
                      'username': contact.target_username,
                      'time': contact.last_yo,
                      'last_seen': contact.target.last_seen_time
                      } for contact in contacts]

    return make_json_response(contacts=public_results)

@contacts_bp.route('/is_blocked')
def route_is_blocked():
    user = g.identity.user
    target = get_user(request.json.get('username'), ignore_permission=True)
    is_blocked = user.has_blocked(target)
    return make_json_response(blocked=is_blocked)


@contacts_bp.route('/unblock')
def route_unblock():
    user = g.identity.user
    target = get_user(request.json.get('username'), ignore_permission=True)
    unblock_contact(user, target)
    return make_json_response()


@contacts_bp.route('/invite_contact')
def route_invite_contact():
    form = InviteContactForm.from_json(request.json)
    form.validate()

    message = invite_contact(**form.patch_data)
    return make_json_response(message=message)


@contacts_bp.route('/mute')
def route_mute():
    username = request.json.get('username')
    if not username:
        raise APIError('Expected username')

    try:
        expire_in_hours = int(request.json.get('expire_in_hours'))
    except:
        expire_in_hours = 8

    target = get_user(username)
    contact = get_contact_pair(g.identity.user, target)

    mute_until = None
    if contact:
        duration = timedelta(hours=expire_in_hours)

        mute_until = get_usec_timestamp(delta=duration)
        contact.mute_until = mute_until
        contact.save()
        # Clearing the cache here is mainly needed for the contact
        # pair and the followers of the group. This is a heavy
        # action that should be refactored.
        clear_get_contacts_cache(contact.owner, contact.target)
        clear_get_followers_cache(contact.target)

    return make_json_response(mute_until=mute_until)


@contacts_bp.route('/unmute')
def route_unmute():
    username = request.json.get('username')
    if not username:
        raise APIError('Expected username')

    target = get_user(username)
    contact = get_contact_pair(g.identity.user, target)

    if contact:
        contact.mute_until = None
        contact.save()
        # Clearing the cache here is mainly needed for the contact
        # pair and the followers of the group. This is a heavy
        # action that should be refactored.
        clear_get_contacts_cache(contact.owner, contact.target)
        clear_get_followers_cache(contact.target)

    return make_json_response()
