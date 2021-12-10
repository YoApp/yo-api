# -*- coding: utf-8 -*-

"""Client banner management endpoints."""


from flask import request, current_app, g

from ..errors import APIError
from ..banners import get_banner, update_banners, acknowledge_banner
from ..helpers import make_json_response, get_usec_timestamp
from ..permissions import assert_admin_permission
from ..yoflask import Blueprint

# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name


# Instantiate a YoFlask customized blueprint that supports JWT authentication.
banners_bp = Blueprint('banner', __name__, url_prefix='/rpc')

@banners_bp.route('/banner_ack', login_required=True)
def route_acknowledge_banner():
    banner_id = request.json.get('banner_id')
    status = request.json.get('result')

    if not banner_id:
        raise APIError('Missing banner_id')

    if not status:
        raise APIError('Missing result')

    acknowledge_banner(banner_id, status)

    return make_json_response()

@banners_bp.route('/get_banner', login_required=True)
def route_get_banner():

    if request.headers.get('X-APP-ID'):
        raise APIError('No banner')

    # @or: disable banners
    #raise APIError('No banner')

    open_count = request.json.get('open_count')
    contexts = request.json.get('contexts')

    if not contexts:
        raise APIError('Missing open_count or contexts')

    # This isn't used yet.
    _ = request.json.get('location')

    user = g.identity.user
    banner = get_banner(user, contexts, open_count)

    if not banner:
        raise APIError('No banner')

    return make_json_response(message=banner.parent.message,
                              context=banner.parent.context,
                              link=banner.parent.link,
                              id=banner.banner_id)


@banners_bp.route('/update_banners', methods=['PUT'], login_required=True)
def route_update_banners():
    assert_admin_permission('Unauthorized')

    resp = update_banners(request.json)
    return make_json_response(**resp)
