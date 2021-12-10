# -*- coding: utf-8 -*-

"""Public API endpoints"""

# pylint: disable=invalid-name

from .accounts import route_user_exists, route_new_api_user
from .contacts import route_count_subscribers
from .yos import (route_yo, route_broadcast_from_api_account,
                  get_yoall_limit, get_limit_key, get_yoall_key)
from ..constants.limits import *
from ..core import limiter
from ..limiters import limit_requests_by_user
from ..yoflask import Blueprint

public_api_bp = Blueprint('public_api', __name__)


@limiter.limit(get_yoall_limit, key_func=get_yoall_key,
               error_message=YO_LIMIT_ERROR_MSG)
@public_api_bp.route('/yoall/')
def route_broadcast_from_api_account_legacy():
    """Public API endpoint for a broadcast"""
    return route_broadcast_from_api_account()


@public_api_bp.route('/subscribers_count/', methods=['GET'])
def route_count_subscribers_legacy():
    """Public API endpoint for counting subscribers"""
    return route_count_subscribers()


@limit_requests_by_user(SIGNUP_LIMIT, error_message=SIGNUP_LIMIT_MSG)
@public_api_bp.route('/accounts/')
def route_new_api_user_legacy():
    """Public API endpoint for creating a new user"""
    return route_new_api_user()


@public_api_bp.route('/check_username/', methods=['GET'], login_required=False)
def route_user_exists_legacy():
    """Public API endpoint for checking if username is taken"""
    return route_user_exists()


@limiter.limit(YO_LIMITS, key_func=get_limit_key)
@public_api_bp.route('/yo/')
def route_yo_legacy():
    """Public API endpoint for a Yo"""
    return route_yo()
