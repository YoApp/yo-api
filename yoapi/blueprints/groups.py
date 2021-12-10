# -*- coding: utf-8 -*-

"""Group management endpoints."""


from flask import g, request, current_app

from ..accounts import get_user, upsert_pseudo_user
from ..contacts import add_contact, remove_contact, get_contact_pair
from ..errors import APIError
from ..forms import AddGroupForm, UpdateGroupForm
from ..groups import (create_group, get_group_contacts, leave_group,
                      add_group_member, remove_group_member,
                      set_group_admin, block_group, update_group,
                      fix_old_group)
from ..helpers import make_json_response, get_usec_timestamp
from ..yoflask import Blueprint


# Instantiate a YoFlask customized blueprint that supports JWT authentication.
groups_bp = Blueprint('groups', __name__, url_prefix='/rpc')

def _lookup_group_from_request():
    username = request.json.get('username')
    user_id = request.json.get('user_id')

    if not (username or user_id):
        raise APIError('Must specify username or user_id.')

    group = None
    try:
        group = get_user(username=username, user_id=user_id)
    except:
        # Pass here to display a better error message.
        pass

    if not (group and group.is_group):
        raise APIError('Group not found.')

    if group.created < 1434350930750436 and group.updated < 1434350930750436:
        fix_old_group(group)

    return group


@groups_bp.route('/add_group', login_required=False)
def route_add_group():
    """Adds a group with the provided details and contacts"""
    form = AddGroupForm.from_json(request.json)
    form.validate()

    group = create_group(**form.patch_data)

    return make_json_response(group=group.get_public_dict(), status_code=201)


@groups_bp.route('/add_group_members', login_required=True)
def route_add_group_members():
    """Add a group member"""

    group = _lookup_group_from_request()
    members = request.json.get('members')
    result = []
    for member in members:
        username = member.get('username')
        phone_number = member.get('phone_number')
        display_name = member.get('display_name')
        name = member.get('name')

        # Only use the display name field for pseudo users.
        if username:
            contact_name = None
            user = get_user(username=username.upper())
            if not user:
                raise APIError('User not found.')
        elif phone_number:
            contact_name = name or display_name
            try:
                user = upsert_pseudo_user(phone_number)
            except APIError:
                continue
        else:
            raise APIError('Expected username or phone_number')

        add_group_member(group, user, contact_name=contact_name)
        result.append(user.get_public_dict(contact_name))

    return make_json_response(added=result)


@groups_bp.route('/block_group', login_required=True)
def route_block_group():
    """Block a group"""

    group = _lookup_group_from_request()
    block_group(group)

    return make_json_response(blocked=group.get_public_dict())


@groups_bp.route('/update_group', login_required=True)
def route_update_group():
    """Edit group info"""

    form = UpdateGroupForm.from_json(request.json)
    form.validate()

    group = _lookup_group_from_request()
    group = update_group(group, **form.patch_data)

    return make_json_response(group.get_public_dict())


@groups_bp.route('/get_group', login_required=True)
def route_get_group():
    """Get group info"""

    group = _lookup_group_from_request()
    group_public_dict = group.get_public_dict()

    user = g.identity.user
    current_time = get_usec_timestamp()

    group_contacts = get_group_contacts(group)

    contact = get_contact_pair(user, group)
    if contact:
        is_muted = contact.mute_until > current_time
        group_public_dict.update({'is_muted': is_muted})

    group_members = []
    group_admins = []
    for group_contact in group_contacts:
        name = group_contact.get_name()
        member_public_dict = group_contact.target.get_public_dict(name)

        if group_contact.is_group_admin:
            group_admins.append(member_public_dict)
        else:
            group_members.append(member_public_dict)

    group_public_dict.update({'members': group_members,
                              'admins': group_admins})

    return make_json_response(group_public_dict)


@groups_bp.route('/leave_group', login_required=True)
def route_leave_group():
    """Leave a group"""

    group = _lookup_group_from_request()
    leave_group(group)

    return make_json_response(left=group.get_public_dict())


@groups_bp.route('/remove_group_member', login_required=True)
def route_remove_group_member():
    """Remove a group member"""

    group = _lookup_group_from_request()

    member = request.json.get('member')
    user = get_user(username=member)

    remove_group_member(group, user)
    return make_json_response(removed=user.get_public_dict())


@groups_bp.route('/set_group_admin', login_required=True)
def route_set_group_admin():
    """Change the group admins"""

    group = _lookup_group_from_request()

    member = request.json.get('member')
    user = get_user(username=member)

    admin = request.json.get('admin', True)
    admin = False if admin != True else True

    set_group_admin(group, user, admin)

    return make_json_response(updated=user.get_public_dict(),
                              is_group_admin=admin)
