# -*- coding: utf-8 -*-

"""Group management package."""


import sys

from flask import g, current_app
from collections import namedtuple

from .accounts import (create_user, get_user, update_user,
                       make_username_unique, delete_user,
                       upsert_pseudo_user)
from .constants.emojis import replace_emojis_with_text, text_has_emojis
from .constants.regex import IS_ALNUM_RE
from .contacts import (get_contact_pair, clear_get_contacts_cache,
                       clear_get_followers_cache, remove_contact,
                       get_contact_objects, block_contact,
                       _get_follower_contacts)
from .errors import APIError
from .helpers import get_usec_timestamp
from .models import Contact
from .notifications import _send_notification_to_users
from .permissions import admin_permission

from .models.payload import Payload


def assert_group_permission(group, error_message):
    """Checks that the current user has valid view permission
    over the provided group.
    NOTE: In order to move this to security.py the curcular dependency on
    contacts.py would need to be remediated"""

    user = g.identity.user

    if is_user_in_group(group, user):
        return

    assert_group_admin_permission(group, error_message)


def assert_group_admin_permission(group, error_message):
    """Checks that the current user has valid administrative permission
    over the provided group.
    NOTE: In order to move this to security.py the curcular dependency on
    contacts.py would need to be remediated"""
    user = g.identity.user

    if admin_permission.can():
        return

    if user == group.parent:
        return

    contact = get_contact_pair(group, user)
    if contact and contact.is_group_admin:
        return

    raise APIError(error_message, status_code=401)


GroupContact = namedtuple('GroupContact', ['member', 'is_group_admin'])


def create_group(name=None, members=None, description=None):
    """Creates a new group"""
    if not name:
        raise APIError('Invalid group name.')

    clean_name = ''.join([c for c in name if c.isalnum()])
    if not clean_name and text_has_emojis(name):
        clean_name = replace_emojis_with_text(name)

    username = ''.join([c.upper() for c in clean_name
                       if IS_ALNUM_RE.search(c)])
    if not username:
        username = make_username_unique('GROUP', random_length=4,
                                        use_letters=True)
    else:
        username = make_username_unique(username)

    creator = g.identity.user
    group = create_user(parent=creator, name=name, description=description,
                        username=username, is_group=True)

    add_group_member(group, creator, is_admin=True)

    members = members if members else []
    members_len = len(members)
    for member in members:
        # Since the ios client sends the name field with everything,
        # only store it if its a pseudo user.
        if member.get('username'):
            username = member.get('username').upper()
            user = get_user(username=username)
            if user.has_blocked(creator):
                continue

            name = None

        elif member.get('phone_number'):
            phone_number = member.get('phone_number')

            try:
                user = upsert_pseudo_user(phone_number, created_by_group=True)
            except APIError:
                continue

            name = member.get('name') or member.get('display_name')
        else:
            raise APIError('Expected username or phone_number.')

        if user == creator:
            continue

        add_group_member(group, user, contact_name=name,
                         send_notifications=False)

        if not user.is_pseudo:
            # Let the new member know they were added.
            message = '%s added you to \'%s\' group with %s other%s'
            message = message %  (creator.display_name, group.name,
                                  members_len,
                                  's' if members_len > 1 else '')

            support = [('must_handle_any_text', True)]
            payload_args = [message, None]
            payload_kwargs = {'sender': group.username}
            _send_notification_to_users.delay([user.user_id], support,
                                              payload_args,
                                              payload_kwargs)

    current_app.log_analytics({'event': 'group_created',
                               'group': name,
                               'creator': group.parent.username,
                               'member_count': members_len})
    return group


def add_group_member(group, member, is_admin=None, contact_name=None,
                     send_notifications=True, ignore_permission=False):
    """Add a user to a group."""

    if not ignore_permission:
        assert_group_permission(group, 'Cannot modify group.')

        if is_admin is not None:
            assert_group_admin_permission(group, 'Cannot modify group.')

    if member.is_group:
        raise APIError('Groups cannot contain other groups.')

    if member.has_blocked(group):
        raise APIError('Member has blocked group.', status_code=403)

    # create the relationship to be owned and managed by the group.
    upsert_values = {'new': False,
                     'set__updated': get_usec_timestamp(),
                     'upsert': True,
                     'unset__hidden': True}

    # We manually check for the group parent just in case
    # a weird error occurs or is introduced.
    if is_admin or member == group.parent:
        upsert_values.update({'set__is_group_admin': True})
    elif is_admin is False:
        upsert_values.update({'unset__is_group_admin': True})

    if contact_name:
        upsert_values.update({'set__contact_name': contact_name})

    contact = Contact.objects(owner=group, target=member).modify(
        **upsert_values)

    clear_get_contacts_cache(group, member)
    clear_get_followers_cache(member)


    # create the relationship to be owned and managed by the member.
    upsert_values = {'new': False,
                     'set__updated': get_usec_timestamp(),
                     'upsert': True}
    contact = Contact.objects(owner=member, target=group).modify(
        **upsert_values)

    clear_get_contacts_cache(member, group)
    clear_get_followers_cache(group)

    # If the contact is None then it is new.
    if not contact and send_notifications:
        user = g.identity.user
        group_member_ids = get_group_members(group)
        group_member_ids = [m.user_id for m in group_member_ids
                            if m != user and m != member]
        if group_member_ids:
            display_name = contact_name or member.display_name
            # Let the current members know someone was added.
            message = '%s added %s to \'%s\' group' % (user.display_name,
                                                       member.display_name,
                                                        group.name)

            support = [('must_handle_any_text', True)]
            payload_args = [message, None]
            payload_kwargs = {'sender': group.username}
            _send_notification_to_users.delay(group_member_ids, support,
                                              payload_args,
                                              payload_kwargs)

        if member != g.identity.user and not member.is_pseudo:
            # Let the new member know they were added.
            message = '%s added you to \'%s\' group' % (user.display_name,
                                                        group.name)

            support = [('must_handle_any_text', True)]
            payload_args = [message, None]
            payload_kwargs = {'sender': group.username}
            _send_notification_to_users.delay([member.user_id], support,
                                              payload_args,
                                              payload_kwargs)

    return contact


def update_group(group, ignore_permission=False, **kwargs):
    """Edit the group info"""

    if not ignore_permission:
        assert_group_admin_permission(group, 'Cannot modify group.')

    old_name = None
    if 'name' in kwargs:
        old_name = kwargs.get('name')

    group = update_user(group, ignore_permission=True, **kwargs)

    if old_name and old_name != group.name:
        group_member_ids = get_group_members(group)
        group_member_ids = [member.user_id for member in group_member_ids]
        message = '\'%s\' group name has been changed to \'%s\''
        message = message % (old_name, group.name)

        support = [('must_handle_any_text', True)]
        payload_args = [message, None]
        payload_kwargs = {'sender': group.username}
        _send_notification_to_users.delay(group_member_ids, support,
                                          payload_args,
                                          payload_kwargs)

    return group


def get_group_members(group, ignore_permission=False):
    """Returns a list of group members."""

    if not ignore_permission:
        assert_group_permission(group, 'Permission denied')

    if not group.is_group:
        return []

    group_contacts = get_group_contacts(group, ignore_permission)
    return [group_contact.target for group_contact in group_contacts]


def get_group_followers(group, ignore_permission=False):
    """Returns a list of group member Contacts owned by the members."""

    if not ignore_permission:
        assert_group_permission(group, 'Group Permission denied')

    if not group.is_group:
        return []

    return _get_follower_contacts(group.user_id)


def get_group_contacts(group, ignore_permission=False):
    """Returns a list of group member Contacts owned by the group."""

    if not ignore_permission:
        assert_group_permission(group, 'Group Permission denied')

    if not group.is_group:
        return []

    # Get the contact objects owned by the group.
    contacts = get_contact_objects(group)
    return [contact for contact in contacts
            if not contact.target.has_blocked(group)]


def is_user_in_group(group, user):
    """Check if user is in group"""

    contact = get_contact_pair(group, user)
    return bool(contact and not user.has_blocked(group))


def remove_group_member(group, member, ignore_permission=False):
    """Remove a user from a group"""

    if not ignore_permission:
        assert_group_admin_permission(group, 'Cannot modify group.')

    remove_contact(member, group, ignore_permission=True)
    remove_contact(group, member, ignore_permission=True)
    members = get_group_members(group, ignore_permission=True)
    if not members:
        try:
            delete_user(group, ignore_permission=True)
        except:
            # If an error occurs here send an email.
            current_app.log_exception(sys.exc_info())


def block_group(group):
    """Remove the current user from a group.
    NOTE: This is here so that when creators and such leave groups
    it can be handled."""

    user = g.identity.user

    if is_user_in_group(group, user):
        members = get_group_members(group)
        member_ids = [member.user_id for member in members if member != user]
        # Let the current members know someone left.
        if member_ids:
            contact = get_contact_pair(group, user)
            display_name = contact.get_name()
            message = '%s just left \'%s\' group' % (display_name, group.name)

            support = [('must_handle_any_text', True)]
            payload_args = [message, None]
            payload_kwargs = {'sender': group.username}
            _send_notification_to_users.delay(member_ids, support,
                                              payload_args,
                                              payload_kwargs)

    block_contact(user, group)


def leave_group(group):
    """Remove the current user from a group.
    NOTE: This is here mainly for language."""

    member = g.identity.user
    if is_user_in_group(group, member):
        group_member_ids = get_group_contacts(group)
        group_member_ids = [m.target.user_id for m in group_member_ids
                            if m.target != member and m.is_group_admin]
        if group_member_ids:
            contact = get_contact_pair(group, member)
            display_name = contact.get_name()
            # Let the current members know someone left.
            message = '%s just left \'%s\' group' % (display_name, group.name)

            support = [('must_handle_any_text', True)]
            payload_args = [message, None]
            payload_kwargs = {'sender': group.username}
            _send_notification_to_users.delay(group_member_ids, support,
                                              payload_args,
                                              payload_kwargs)

    remove_contact(member, group)
    remove_contact(group, member, ignore_permission=True)
    members = get_group_members(group, ignore_permission=True)
    if not members:
        try:
            delete_user(group, ignore_permission=True)
        except:
            # If an error occurs here send an email.
            current_app.log_exception(sys.exc_info())


def set_group_admin(group, member, is_admin, ignore_permission=False):
    """Sets the is_admin flag on the contact pair for a group member.
    This function is just a wrapper to add_group_member"""

    if not ignore_permission:
        assert_group_admin_permission(group, 'Cannot modify group.')

    if member == group.parent and not is_admin:
        raise APIError('Cannot modify the creators access.')

    # NOTE: Maybe this shouldn't be an upsert?
    add_group_member(group, member, is_admin=is_admin)


def fix_old_group(group):
    """Converts older groups from using reverse relationships to use
    forward and reverse relationships"""

    user = g.identity.user
    current_time = get_usec_timestamp()

    try:
        contacts = Contact.objects(target=group)

        for contact in contacts:
            new_contact = Contact.objects(owner=group,
                                          target=contact.owner)
            existing = new_contact.first()
            upsert_values = {}
            if contact.is_group_admin:
                upsert_values.update({'set__is_group_admin': True})
            else:
                upsert_values.update({'unset__is_group_admin': True})

            if (contact.last_yo and
                (not existing or existing.last_yo < contact.last_yo)):
                upsert_values.update({'set__last_yo': contact.last_yo})
                upsert_values.update({'set__last_yo_object': contact.last_yo_object})

            new_contact.modify(upsert=True, set__updated=current_time,
                               **upsert_values)

            contact.is_group_admin = None
            contact.save()

        clear_get_contacts_cache(group, user)
        clear_get_contacts_cache(user, group)
        clear_get_followers_cache(group)
        clear_get_followers_cache(user)

        # save the group to update its updated time.
        update_user(group, updated=current_time,
                    ignore_permission=True)
        current_app.logger.info({'message': 'fixed old group',
                                 'group_name': group.name,
                                 'group_username': group.username})
    except Exception:
        current_app.log_exception(sys.exc_info())
