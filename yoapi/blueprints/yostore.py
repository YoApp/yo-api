# -*- coding: utf-8 -*-

"""Routes to retreive and eventually manage the yo index"""

# pylint: disable=invalid-name


from flask import request

from ..helpers import make_json_response, get_remote_addr, get_location_data
from ..models import YoStore
from ..permissions import assert_admin_permission
from yoapi.localization import get_region
from ..yostore import (update_yo_store, get_store_items,
                       update_store_categories, get_store_categories,
                       update_watch_promo_items, get_watch_promo_items)
from ..yoflask import Blueprint


yostore_bp = Blueprint('index', __name__, url_prefix='/index')


@yostore_bp.route('/', methods=['GET', 'PUT'], login_required=False)
def route_index():
    if request.method == 'GET':
        store_items = get_store_items()
        results = [item.to_dict() for item in store_items]

        # Since the response is very large, redact it from the logs
        return make_json_response(results=results, log_json_response=False)
    elif request.method == 'PUT':
        assert_admin_permission('Unauthorized')
        result = update_yo_store(request.json)

    return make_json_response(**result)


@yostore_bp.route('/<string:region>', methods=['GET'], login_required=False)
def route_list_index_by_region(region):
    regions = region.split('+')
    store_items = get_store_items(regions=regions)
    results = [item.to_dict() for item in store_items]

    # Since the response is very large, redact it from the logs
    return make_json_response(results=results, log_json_response=False)


store_category_bp = Blueprint('category', __name__, url_prefix='/category')


@store_category_bp.route('/', methods=['GET', 'PUT'], login_required=False)
def route_store_categories():
    if request.method == 'GET':
        store_categories = get_store_categories()
        results = [item.to_dict() for item in store_categories]

        return make_json_response(results=results)
    elif request.method == 'PUT':
        assert_admin_permission('Unauthorized')
        result = update_store_categories(request.json)

    return make_json_response(**result)


@store_category_bp.route('/<string:region>', methods=['GET'], login_required=False)
def route_get_store_categories_by_region(region):
    regions = region.split('+')
    store_categories = get_store_categories(regions=regions)
    results = [item.to_dict() for item in store_categories]

    return make_json_response(results=results)


watchpromo_bp = Blueprint('watchpromo', __name__, url_prefix='/watchpromo')


@watchpromo_bp.route('/', methods=['GET', 'PUT'], login_required=False)
def route_watch_promo():
    if request.method == 'GET':
        promo_items = get_watch_promo_items()
        results = [item.to_dict() for item in promo_items]

        return make_json_response(results=results)
    elif request.method == 'PUT':
        assert_admin_permission('Unauthorized')
        result = update_watch_promo_items(request.json)

    return make_json_response(**result)


store_bp = Blueprint('store', __name__, url_prefix='/store')

@store_bp.route('/', methods=['GET'], login_required=False)
def route_store():

    #region = None
    #try:
    #    if request.json.get('lat') and request.json.get('lon'):
    #        lat = float(request.json.get('lat'))
    #        long = float(request.json.get('lat'))
    #    else:
    #        address = get_remote_addr(request)
    #        data = get_location_data(address)
    #        lat = float(data.get('latitude'))
    #        long = float(data.get('longitude'))
    #except:
    #    pass

    #if lat and long:
    #    region = get_region((lat, long))

    #store_items = get_store_items(regions=[region])
    store_items = get_store_items()
    populated_categories = set()
    for item in store_items:
        if item.category:
            populated_categories.update([str(c) for c in item.category])

    store_items = [item.to_dict() for item in store_items]

    store_categories = get_store_categories()
    store_categories = [c.to_dict() for c in store_categories
                        if str(c.category) in populated_categories]

    return make_json_response(store_categories=store_categories,
                              store_items=store_items,
                              log_json_response=False)


@store_bp.route('/<string:region>', methods=['GET'], login_required=False)
def route_get_store_by_region(region):
    regions = region.split('+')

    store_items = get_store_items(regions=regions)
    populated_categories = set()
    for item in store_items:
        if item.category:
            populated_categories.update([str(c) for c in item.category])

    store_categories = get_store_categories(regions=regions)
    store_categories = [c.to_dict() for c in store_categories
                        if str(c.category) in populated_categories]

    store_items = [item.to_dict() for item in store_items]

    return make_json_response(store_categories=store_categories,
                              store_items=store_items)
