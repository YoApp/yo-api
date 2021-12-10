# -*- coding: utf-8 -*-

"""Routes to retreive and manage the ab-testing copy"""

# pylint: disable=invalid-name


from flask import request

from ..ab_test import update_ab_tests
from ..categories import update_categories
from ..contexts import update_gif_phrases
from ..headers import (update_header_copy, validate_sms_copy,
                       get_header_map)
from ..helpers import make_json_response
from ..permissions import assert_admin_permission
from yoapi.cms import update_items
from ..yoflask import Blueprint

ab_test_bp = Blueprint('ab_test', __name__, url_prefix='/ab_test')


@ab_test_bp.route('/header/update', methods=['PUT'], login_required=True)
def route_header_update():
    assert_admin_permission('Unauthorized')
    result = update_header_copy(request.json)

    return make_json_response(**result)

@ab_test_bp.route('/header/validate', methods=['POST'], login_required=True)
def route_header_validate():
    assert_admin_permission('Unauthorized')
    examples = validate_sms_copy(request.json)

    return make_json_response(examples=examples)

@ab_test_bp.route('/categories/update', methods=['PUT'], login_required=True)
def route_categories_update():
    assert_admin_permission('Unauthorized')
    result = update_categories(request.json)

    return make_json_response(**result)

@ab_test_bp.route('/giphy/update', methods=['PUT'], login_required=True)
def route_giphy_update():
    """Updates the phrases associated with fetching gifs form giphy"""
    assert_admin_permission('Unauthorized')
    result = update_gif_phrases(request.json)

    return make_json_response(**result)


@ab_test_bp.route('/update', methods=['PUT'], login_required=True)
def route_ab_test_update():
    assert_admin_permission('Unauthorized')

    items = request.json
    headers = [item.get('notification') for item in items
               if ('notification' in item.get('dimensions') and
                   item.get('notification'))]

    if headers:
        headers = reduce(lambda x, y: x + y, headers)
        header_map = get_header_map(headers)
    else:
        header_map = {}

    result = update_ab_tests(items, header_map)

    return make_json_response(**result)


@ab_test_bp.route('/update_items', methods=['PUT'], login_required=True)
def route_update():
    assert_admin_permission('Unauthorized')

    resp = update_items(request.json)
    return make_json_response(**resp)