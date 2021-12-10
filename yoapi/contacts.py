# -*- coding: utf-8 -*-

"""Account management package."""

from collections import namedtuple

from flask import current_app, g
from phonenumbers.phonenumberutil import NumberParseException
from .async import async_job
from .permissions import assert_account_permission
from .core import cache, twilio
from .helpers import get_usec_timestamp, clean_phone_number
from .errors import APIError
from .accounts import clear_get_user_cache
from .models import User, Contact, YoToken, Yo
from .services import low_rq


def add_contact(owner, target, contact_name=None, ignore_permission=False):
    """Adds a contact to the owner if it doesn't already exist

    Args:
        owner: A yoapi.models.User object
        target: A yoapi.models.User object
    """

    if not ignore_permission:
        assert_account_permission(owner, 'Permission denied')

    existing_contact = get_contact_pair(owner, target)

    # Don't allow manual entry into a group.
    if target.is_group and not existing_contact:
        raise APIError('Cannot add yourself to a group', status_code=403)

    contact, _ = upsert_contact(owner, target, contact_name=contact_name,
                                reverse_upsert=False,
                                ignore_permission=ignore_permission)

    return contact


def block_contact(source, target):
    """Blocks the target from contacting the blocker

    Args:
        source: A yoapi.models.User object
        target: A yoapi.models.User object
    """
    if not isinstance(source.blocked, list):
        source.blocked = []

    if not source.has_blocked(target):
        source.blocked.append(target)
        source.save()

        contact = get_contact_pair(source, target)
        if contact:
            contact.delete()

        clear_get_user_cache(source)
        clear_get_contacts_cache(source, target)
        clear_get_followers_cache(target)
        clear_get_subscriptions_objects(source)

        if target.in_store:
            event_data = {'event': 'service_unsubscribed',
                          'username': source.username,
                          'service': target.username}
            current_app.log_analytics(event_data)


def clear_get_contacts_cache(user, target=None):
    """Clears the memoize cache for get_contacts"""
    cache.delete_memoized(get_contact_objects, user)
    cache.delete_memoized(_get_contacts, user.user_id)
    cache.delete_memoized(get_contact_usernames, user)
    if target:
        if target.in_store:
            cache.delete_memoized(get_subscriptions, user)
        cache.delete_memoized(get_contact_pair, user, target)


def clear_get_subscriptions_objects(user):
    cache.delete_memoized(get_subscriptions_objects, user)


def clear_get_contacts_last_yo_cache(user, target=None):
    """Clears the memoize cache for get_contacts"""
    cache.delete_memoized(_get_contacts_last_yo, user)
    if target:
        cache.delete_memoized(_get_contacts_last_yo, target)


def clear_get_followers_cache(user):
    """Clears the memoize cache for get_followers"""
    cache.delete_memoized(_get_followers, user)
    cache.delete_memoized(_get_followers_count, user)
    cache.delete_memoized(_get_follower_contacts, user.user_id)


def find_contacts_by_facebook_ids(facebook_ids):
    """Returns contacts that match any of the given facebook ids

      Args:
        facebook_ids: An array of facebook ids.
    """
    matches = User.objects(facebook_id__in=facebook_ids)
    for user in matches:
        if user != g.identity.user:
            yield user.facebook_id, user


def get_blocked_contacts(user):
    """Returns a list of blocked contacts."""
    if not user.blocked:
        return []
    else:
        blocked = [u for u in user.blocked if isinstance(u, User)]
        blocked.sort(key=lambda u: u.username)
        return blocked


@cache.memoize()
def get_contact_objects(user):
    """Returns a list of contact objects."""
    contacts = Contact.objects(owner=user, hidden__exists=False).order_by(
        '-updated', '-created').select_related(max_depth=2)
    return [contact for contact in contacts
            if not contact.has_dbrefs()
        and not contact.owner.has_blocked(contact.target)]


@cache.memoize()
def get_subscriptions(user):
    """Returns a list of contact objects."""
    contacts = Contact.objects(owner=user, hidden__exists=False).order_by(
        '-updated', '-created').select_related()
    subscriptions = [contact.target.username for contact in contacts
                     if not contact.has_dbrefs() and contact.target and
                        not contact.target.has_dbrefs() and
                        contact.target.in_store or contact.target.is_service and
                                                   not contact.target.is_interactive and
                        not contact.owner.has_blocked(contact.target)]
    return subscriptions


@cache.memoize()
def get_subscriptions_objects(user):
    """Returns a list of contact objects."""
    contacts = Contact.objects(owner=user, hidden__exists=False).order_by(
        '-last_yo').select_related()
    subscriptions = [contact.target for contact in contacts
                     if not contact.has_dbrefs() and contact.target and
                        not contact.target.has_dbrefs() and
                        contact.target.in_store or contact.target.is_service and
                                                   not contact.target.is_person and
                                                   not contact.target.is_interactive and
                        not contact.owner.has_blocked(contact.target)]
    return subscriptions


ContactObject = namedtuple('ContactObject', ['target', 'contact_name', 'last_yo'])


@cache.memoize()
def _get_contacts(user_id):
    """Returns a list of contacts."""
    contacts = Contact.objects(owner=user_id, hidden__exists=False).limit(100).order_by(
        '-updated', '-created').select_related()

    results = []
    owner = None
    for contact in contacts:
        target = contact.target
        last_yo = contact.last_yo
        if not owner:
            owner = contact.owner

        if owner.has_blocked(target):
            continue

        if not isinstance(target, User) or target.is_subscribable:
            continue

        contact_name = contact.contact_name

        if target.in_store:
            continue

        if target.app_name:
            continue

        if target.is_service and not target.is_person:
            if target.callback is None or target.callbacks and len(target.callbacks) == 0:
                continue

        if target.is_group:
            contact_name = None

        results.append(ContactObject(target, contact_name, last_yo))

    return results


def get_contacts(user, ignore_permission=False):
    if not ignore_permission:
        assert_account_permission(user, 'No permission to access user')
    contacts = _get_contacts(user.user_id)
    return contacts


def get_contacts_with_status(user):
    contacts = Contact.objects(owner=user.user_id,
                               hidden__exists=False
    ).limit(100).order_by('-updated', '-created').select_related()
    results = []
    for c in contacts:
        if c.target.status:
            results.append(c)

    return results


@cache.memoize()
def get_contact_usernames(user):
    """Returns a list of contacts."""
    contacts = Contact.objects(owner=user, hidden__exists=False).order_by(
        '-updated', '-created').select_related()
    contacts = [contact.target.username for contact in contacts
                if not contact.has_dbrefs()
        and not contact.owner.has_blocked(contact.target)]
    return contacts


@cache.memoize()
def _get_contacts_last_yo(user):
    """Returns the last yo sent for each contact"""
    contacts = Contact.objects(owner=user, hidden__exists=False,
                               last_yo_object__exists=True).order_by(
        '-last_yo').select_related(max_depth=2)
    return [contact.last_yo_object for contact in contacts
            if not contact.has_dbrefs()
               and isinstance(contact.last_yo_object, Yo)
        and not user.has_blocked(contact.target)]


def get_contacts_yo_status(user, contacts=None, ignore_permission=False):
    """Returns the status associated with the last yo between each contact"""
    if not ignore_permission:
        assert_account_permission(user, 'Permission denied')

    contact_yos = _get_contacts_last_yo(user)

    if contacts:
        contacts = set(contacts)
        contacts_len = len(contacts)
        yos = []
        for yo in contact_yos:
            if contacts_len <= 0:
                break

            friend = yo.get_friend(user, safe=True)
            if friend and friend.username in contacts:
                yos.append(yo)
                contacts_len -= 1
    else:
        yos = contact_yos

    statuses = [yo.get_status_dict(user) for yo in yos if not yo.has_dbrefs()]
    return [status for status in statuses if status]


def get_followers_count(user, ignore_permission=False):
    """Returns a list of followers."""
    if not ignore_permission:
        assert_account_permission(user, 'Permission denied')
    return _get_followers_count(user)


def get_followers(user, ignore_permission=False):
    """Returns a list of followers."""
    if not ignore_permission:
        assert_account_permission(user, 'Permission denied')
    return _get_followers(user)


@cache.memoize()
def _get_follower_contacts(user_id):
    """Returns a list of follower Contact objects."""
    contacts = Contact.objects(target=user_id).select_related()
    contacts = [contact for contact in contacts
                if not contact.has_dbrefs() and
                   not contact.owner.has_blocked(contact.target)]
    return list(contacts)


@cache.memoize()
def _get_followers(user):
    """Returns a list of followers."""
    contacts = Contact.objects(target=user).select_related()
    contacts = [contact.owner for contact in contacts
                if not contact.has_dbrefs() and
                   not contact.owner.has_blocked(contact.target)]
    return list(contacts)


@cache.memoize()
def _get_followers_count(user):
    """Returns the count of followers."""
    return Contact.objects(target=user).count()


@cache.memoize()
def get_contact_pair(user, target):
    """Returns the contact object for this user and target or None"""

    return Contact.objects(owner=user, target=target).first()


def hide_contact(owner, target, ignore_permission=False):
    """Removes a follower from a target"""
    if not ignore_permission:
        assert_account_permission(owner, 'Permission denied')

    Contact.objects(owner=owner, target=target).update(set__hidden=True)
    clear_get_contacts_cache(owner, target)
    clear_get_followers_cache(target)


def invite_contact(number=None, contact_name=None, country_code_if_missing='1'):
    """Sends a sms message via twilio to the supplied phone
    number to invite them to Yo"""
    try:
        valid_number = clean_phone_number(number, country_code_if_missing)
    except NumberParseException:
        raise APIError('Invalid phone number provided')

    user = g.identity.user

    digits = ''.join([d for d in number if d.isdigit()])
    ab_test = int(digits) % 2

    if ab_test:
        yoback_link = YoToken.generate_link(recipient=user, text=contact_name)
        message = 'Yo from %s, click the link to Yo Back: %s'
        message = message % (user.username, yoback_link)
        current_app.logger.info({'Event': 'Invite', 'type': 'yoback',
                                 'username': user.username})
    else:
        message = 'Join %s on Yo. %s'
        server = current_app.config.get('INVITE_SERVER')
        invite_link = '%s/%s' % (server, user.username)
        message = message % (user.username, invite_link)
        current_app.logger.info({'Event': 'Invite', 'type': 'invite',
                                 'username': user.username})

    twilio.send(valid_number, message)

    return message


def remove_contact(owner, target, ignore_permission=False):
    """Removes a follower from a target"""
    if not ignore_permission:
        assert_account_permission(owner, 'Permission denied')

    Contact.objects(owner=owner, target=target).delete()
    clear_get_contacts_cache(owner, target)
    clear_get_followers_cache(target)


def unblock_contact(source, target):
    """Blocks the target from contacting the blocker

    Args:
        blocker: A yoapi.models.User object
        target: A yoapi.models.User object
    """
    if source.has_blocked(target):
        source.update(pull__blocked=target)
        clear_get_user_cache(source)
        clear_get_contacts_cache(source, target)
        clear_get_followers_cache(target)


def upsert_contact(owner, target, last_yo=None, contact_name=None,
                   reverse_upsert=None, ignore_permission=False):
    """Adds or updates a contact

    We should be clearer about the mechanisms of implicitly adding contacts
    vs explicitly adding contacts. One of the two should be sufficient.

    Args:
        owner: A yoapi.models.User object
        target: A yoapi.models.User object
        last_yo: A yoapi.models.Yo integer

    Returns:
        The contact row after upsert, is_first_yo.
    """
    if not ignore_permission:
        assert_account_permission(owner, 'Permission denied')

    # If this is a new contact, contact will be None.
    contact = Contact.objects(owner=owner, target=target)
    previous_yo = None
    is_new_contact = not bool(contact)
    if owner.is_pseudo and is_new_contact:
        raise APIError('Sign up for Yo to yo new contacts.', status_code=403)
    is_first_yo = bool(last_yo)
    # only allow is_first_yo to be True if something was passed as
    # a last_yo parameter (i.e. this is being called by send_yo)
    if contact and last_yo:
        previous_yo = contact.first().last_yo
        is_first_yo = True if not previous_yo else False

    upsert_values = {}
    if contact_name:
        upsert_values.update({'set__contact_name': contact_name})

    if last_yo:
        upsert_values.update({'set__last_yo': last_yo.created,
                              'set__last_yo_state': 'You sent',
                              'set__last_yo_object': last_yo})

    upsert_values.update({'set__target_username': target.username})

    contact = contact.modify(
        new=True,
        upsert=True,
        set__updated=get_usec_timestamp(),
        unset__hidden=True, **upsert_values)

    if reverse_upsert is not None:
        should_reverse_upsert = reverse_upsert
    else:
        should_reverse_upsert = not target.is_service

    # Set the last yo object on the recipient's contact object so that
    # retrieving status is easier.
    if last_yo:
        # Clear cache so we get contacts in chronological order on next call.
        clear_get_contacts_cache(target, owner)

        Contact.objects(owner=target, target=owner).modify(
            upsert=should_reverse_upsert,
            set__last_yo=last_yo.created,
            set__last_yo_object=last_yo,
            set__updated=get_usec_timestamp(),
            unset__hidden=True)

    # If owner has blocked said user then we unblock them.
    unblocked = False
    if owner.has_blocked(target):
        unblock_contact(owner, target)
        unblocked = True

    # Clear cache so we get contacts in chronological order on next call.
    clear_get_contacts_cache(owner, target)

    # Clear the cache so we get new yo statuses on next call.
    clear_get_contacts_last_yo_cache(owner, target)

    clear_get_subscriptions_objects(owner)

    # Only clear the followers if it is a new contact
    if is_new_contact:
        # Only clear if this is a new contact
        clear_get_followers_cache(target)

    if (is_new_contact or unblocked) and target.in_store:
        event_data = {'event': 'service_subscribed',
                      'username': owner.username,
                      'service': target.username}
        current_app.log_analytics(event_data)

    # Return contact and boolean
    return contact, is_first_yo


@async_job(rq=low_rq)
def delete_user_contacts(user_id):
    contacts_query = Contact.objects(owner=user_id)
    contacts = contacts_query.select_related()
    followers_query = Contact.objects(target=user_id)
    followers = followers_query.select_related()
    contacts_to_clear = set()
    user = None
    for contact in contacts:
        if not user and isinstance(contact.target, User):
            user = contact.owner

        if not contact.has_dbrefs():
            contacts_to_clear.add(contact.target)
    contacts_query.delete()

    for follower in followers:
        if not user and isinstance(follower.target, User):
            user = follower.target

        if not follower.has_dbrefs():
            contacts_to_clear.add(follower.owner)
    followers_query.delete()

    for contact in contacts_to_clear:
        clear_get_contacts_cache(contact, user)
        clear_get_contacts_cache(user, contact)
        clear_get_contacts_last_yo_cache(contact, user)
        clear_get_contacts_last_yo_cache(user, contact)
        clear_get_followers_cache(contact)

    if isinstance(user, User):
        clear_get_followers_cache(user)
