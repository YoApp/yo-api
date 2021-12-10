# -*- coding: utf-8 -*-

"""Routes to retreive and manage the FAQ"""

# pylint: disable=invalid-name


from flask import request

from ..helpers import make_json_response
from ..models import FAQ
from ..permissions import assert_admin_permission
from ..faq import update_faq, get_faq_items, get_faq_items_for_app
from ..yoflask import Blueprint


faq_bp = Blueprint('faq', __name__, url_prefix='/faq')


@faq_bp.route('/', methods=['GET', 'PUT'], login_required=False)
def route_faq():
    if request.method == 'GET':

        if request.json.get('app_id'):
            faq_items = get_faq_items_for_app(request.json.get('app_id'))
        else:
            faq_items = get_faq_items()

        results = [item.to_dict() for item in faq_items]

        # Since the response is very large, redact it from the logs
        return make_json_response(results=results, log_json_response=False)
    elif request.method == 'PUT':
        assert_admin_permission('Unauthorized')
        result = update_faq(request.json)

    return make_json_response(**result)




