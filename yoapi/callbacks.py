# -*- coding: utf-8 -*-

"""Callback operations package."""

from flask import current_app, g, request
from mongoengine import DoesNotExist

from .accounts import (_get_user, clear_get_user_cache, get_user,
                       write_through_user_cache, update_user)
from .contacts import (clear_get_contacts_cache,
                       clear_get_contacts_last_yo_cache,
                       clear_get_followers_cache, get_contact_pair)
from .core import sns
from .helpers import get_usec_timestamp
from .models import Contact, NotificationEndpoint
from .notification_endpoints import (clear_get_user_endpoints_cache,
                                     get_useragent_profile)
from .async import async_job
from .services import low_rq

from .models.payload import YoPayload
from .yos.queries import get_yos_received

DASHBOARD_ROUTES = set(['/rpc/broadcast_from_api_account',
                        '/rpc/yo_from_api_account'])
PUBLIC_API_ROUTES = set(['/yo/', '/yoall/', '/subscribers_count',
                         '/accounts/', '/check_username'])

def remove_disabled_endpoint(endpoint_arn):
    try:
        endpoint = NotificationEndpoint.objects(arn=endpoint_arn).get()

        # Clear the cache prior to deleting the endpoint
        if endpoint.owner:
            clear_get_user_endpoints_cache(endpoint.owner)
        endpoint.delete()
    except DoesNotExist:
        pass

    sns.delete_endpoint(endpoint_arn=endpoint_arn)


def process_user_activity():
    user = g.identity.user
    identity = g.identity
    auth_type = identity.auth_type if hasattr(identity, 'auth_type') else None
    useragent_platform = get_useragent_profile().get('platform')

    if request.is_user_activity():
        user.last_seen_time = get_usec_timestamp()

    # Pseudo users should only log in with api tokens
    # but lets be cautious.
    if user.is_pseudo or user.is_admin:
        if user._changed_fields:
            write_through_user_cache(user)

        return

    # logged in via an coookie. If this is the dashboard set the
    # flag on the user being acted upon. At this point we cannot
    # say for sure that the authenticated user is or isn't a person.
    if auth_type == 'WEB' and request.path in DASHBOARD_ROUTES:
        impersonated_user = get_user(request.json.get('username'))
        if not impersonated_user._is_service:
            update_user(impersonated_user, _is_service=True)

        """
        TODO: Figure out if it makes sense to retract _is_person=True
        if impersonated_user._is_person:
            update_user(impersonated_user, _is_person=None)
            # Let us know if mistakes are perhaps being made.
            message = 'Trying to change _is_person from True to None'
            current_app.log_error({
                'username': user.username,
                'impersonated_username': impersonated_user.username,
                'path': request.path,
                'auth_type': 'WEB'})
        """

    # Logged in via the app or a replay request. Check the useragent
    # to be sure that we can pull a platform based on known useragents.
    # Don't set the flag if its already set.
    elif (auth_type.startswith('JWT') and useragent_platform and
          not user._is_person):
        user._is_person = True

    # Using an api token. This could be due to a number of things so
    # limit taking action only to public api endpoints.
    elif auth_type == 'API' and request.path == '/yoall/':
        if not user._is_service:
            user._is_service = True

        if request.json.get('username'):
            impersonated_user = get_user(request.json.get('username'))

            if not impersonated_user._is_service:
                update_user(impersonated_user, _is_service=True)

            """
            TODO: Figure out if it makes sense to retract _is_person=True
            if impersonated_user._is_person:
                update_user(impersonated_user, _is_person=None)
                # Let us know if mistakes are perhaps being made.
                message = 'Trying to change _is_person from True to None'
                current_app.log_error({
                    'username': user.username,
                    'impersonated_username': impersonated_user.username,
                    'path': request.path,
                    'auth_type': 'API'})
            """

    elif auth_type == 'API' and request.path in PUBLIC_API_ROUTES:
        if not user._is_service:
            user._is_service = True

        """
        TODO: Figure out if it makes sense to retract _is_person=True
        if user._is_person:
            user._is_person = None
            # Let us know if mistakes are perhaps being made.
            message = 'Trying to change _is_person from True to None'
            current_app.log_error({
                'username': user.username,
                'impersonated_username': impersonated_user.username,
                'path': request.path,
                'auth_type': 'API'})
        """

    if user._changed_fields:
        write_through_user_cache(user)


def consume_pseudo_user(user, phone):
    """Takes all activity done by a pseudouser and migrates it to a
    (hopefully recently created) user

    user: User object that will end up with the data
    phone: canonical phone number starting with + and country code
    of the pseudo user to consume.
    
    Returns: the user object, modified or not.
    """
    # trim leading + off of phone number to get username
    try:
        pseudo_user = get_user(username=phone[1:])
    except:
        # pseudo_user not found, so we have nothing to do
        return False
    # only update contacts owned by the user. The reciprocal 
    # contacts can be changed by a backround worker asynchronously
    owner_contacts = Contact.objects(owner=pseudo_user)

    owner_contact_targets = []
    group_count = 0
    contact_count = 0
    for c in owner_contacts:
        if c.target.is_group:
            group_count += 1

        contact_count += 1
        if get_contact_pair(user, c.target):
            continue
        c.update(set__owner=user)
        owner_contact_targets.append(c.target.user_id)

    user.migrated_from = pseudo_user
    user.save()
    pseudo_user.migrated_to = user
    pseudo_user.save()

    clear_get_user_cache(user)
    clear_get_user_cache(pseudo_user)

    clear_get_contacts_cache(user)
    clear_get_contacts_last_yo_cache(user)

    _consume_pseudo_user_async.delay(user.user_id, pseudo_user.user_id,
                                     owner_contact_targets)

    last_yo_received = get_yos_received(pseudo_user, limit=1, ignore_permission=True)
    event_data = {'event': 'pseudo_user_converted',
                  'phone': phone,
                  'username': user.username,
                  'group_count': group_count,
                  'contact_count': contact_count,
                  'yos_received': pseudo_user.count_in or 0,
                  'yos_sent': pseudo_user.count_out or 0,
                  'last_yo_type': None,
                  'last_yo_header': None}
    if last_yo_received:
        last_yo_received = last_yo_received[0]
        payload = YoPayload(last_yo_received,
                            NotificationEndpoint.perfect_payload_support_dict())
        event_data.update({'last_yo_type': payload.payload_type,
                           'last_yo_header': payload.get_push_text()})

    current_app.log_analytics(event_data)
    return True

@async_job(rq=low_rq)
def _consume_pseudo_user_async(user_id, pseudo_user_id, owner_contact_targets):
    target_contacts = Contact.objects(target=pseudo_user_id)

    user = _get_user(user_id=user_id)
    for c in target_contacts:
        if get_contact_pair(c.owner, user):
            continue
        c.target = user
        c.save()
        clear_get_contacts_cache(c.owner)

    for uid in owner_contact_targets:
        u = _get_user(user_id=uid)
        clear_get_followers_cache(u)

