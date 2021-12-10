# -*- coding: utf-8 -*-

"""Permissions module.

It is very important to protect core functionality with granular
authorization to avoid accidental leaks or cross-contamination.

Example:

    # Restrict access to profiles.
    if not (AccessProfilePermission(username).can()):
        raise Unauthorized('No permission to view profile: %s' % username)

"""

from functools import partial
from flask_principal import (Permission, Need, RoleNeed)
from .errors import APIError


# It is not against PEP8 to use lower case variable names at the module level.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name


# Need declarations.
LoginNeed = partial(Need, 'logged_in')
AccountNeed = partial(Need, 'account')
ViewProfileNeed = partial(Need, 'view_profile')

# Role declarations.
admin_need = RoleNeed('admin')
pseudo_need = RoleNeed('pseudo_account')

# Permissions to control authentication requirement on endpoints.
login_required_permission = Permission(LoginNeed(True))
login_required = login_required_permission.require(http_exception=401)

# Permission that prevents accounts with the pseudo_need.
pseudo_forbidden_permission = Permission()
pseudo_forbidden_permission.excludes = set([pseudo_need])
pseudo_forbidden = pseudo_forbidden_permission.require(http_exception=401)


# Permission that requires login and prevents pseudo users.
no_pseudo_login_permission = login_required_permission.union(
        pseudo_forbidden_permission)
no_pseudo_login = no_pseudo_login_permission.require(http_exception=401)

# Admin permission.
admin_permission = Permission(admin_need).require(http_exception=401)


def assert_admin_permission(error_message):
    """Throws an exception unless admin permission is satisfied."""
    if not admin_permission.can():
        raise APIError(error_message, status_code=401)


class AccountPermission(Permission):

    """Permission for account level operations."""

    def __init__(self, user):
        """Initializes a permission with one or more needs.

        The user parameter can be any of the following:

            User: A permission is initialized both for given user as well as
            the parent user if such exists.

            string: The argument is assumed to be a username and a single need
            is passed to the permission constructor.

        Raises:

            A ValueError if the user argument is None.

        """
        if not user:
            raise ValueError('No value for permission')
        userneed = AccountNeed(user.user_id)
        if user.parent:
            parentneed = AccountNeed(user.parent.user_id)
            super(AccountPermission, self).__init__(userneed, parentneed)
        else:
            super(AccountPermission, self).__init__(userneed)


def assert_account_permission(user, error_message):
    """Throws an exception unless permission is satisfied."""
    if not (admin_permission.can() or AccountPermission(user).can()):
        raise APIError(error_message, status_code=401)


class AccessProfilePermission(Permission):

    """Permission for viewing a profile."""

    def __init__(self, user):
        """Initializes a permission with one or more needs.

        The user parameter can be any of the following:

            User: A permission is initialized both for given user as well as
            the parent user if such exists.

            string: The argument is assumed to be a username and a single need
            is passed to the permission constructor.

        Raises:

            A ValueError if the user argument is None.

        """
        if not user:
            raise ValueError('No value for permission')
        args = [ViewProfileNeed(str(user.id))]

        # Allow parent accounts to view profile.
        if user.parent:
            args.append(ViewProfileNeed(str(user.parent.id)))

        super(AccessProfilePermission, self).__init__(*args)


def assert_view_permission(user, error_message):
    """Throws an exception unless permission is satisfied."""
    # if not (admin_permission.can() or AccessProfilePermission(user).can()):
    # TODO: This needs to be fixed later
    #     raise APIError(error_message, status_code=401)

    pass
