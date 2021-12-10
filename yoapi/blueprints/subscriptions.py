from flask import g, request
from mongoengine import DoesNotExist
import validators
from yoapi.accounts import get_user
from yoapi.errors import APIError
from yoapi.helpers import make_json_response
from yoapi.models.subscription import Subscription
from yoapi.yoflask import Blueprint


subscriptions_bp = Blueprint('subscriptions', __name__)


@subscriptions_bp.route('/status/subscriptions/', methods=['GET', 'POST'], login_required=True)
@subscriptions_bp.route('/status/subscriptions', methods=['GET', 'POST'], login_required=True)
@subscriptions_bp.route('/status/webhooks/', methods=['GET', 'POST'], login_required=True)
@subscriptions_bp.route('/status/webhooks', methods=['GET', 'POST'], login_required=True)
def subscriptions():
    user = g.identity.user
    if request.method == 'GET':
            items = Subscription.objects(owner=user)
            return make_json_response({'results': [item.get_public_dict() for item in items]})

    if request.method == 'POST':

        webhook_url = request.json.get('webhook_url')
        if not validators.url(webhook_url):
            raise APIError('Invalid url in webhook parameter')

        target_id = request.json.get('target_id')
        target_username = request.json.get('target_username')
        if target_id:
            target = get_user(user_id=target_id)
        elif target_username:
            target = get_user(username=target_username)
        else:
            raise APIError('Missing target_username or target_id')

        item = Subscription(
            owner=user,
            target=target,
            webhook_url=webhook_url,
            event_type='status.update',
            token=request.json.get('redirect_uri')
        )
        item.save()
        return make_json_response(item.get_public_dict())


@subscriptions_bp.route('/status/subscriptions/<subscription_id>/', methods=['GET', 'DELETE'])
@subscriptions_bp.route('/status/subscriptions/<subscription_id>', methods=['GET', 'DELETE'])
@subscriptions_bp.route('/status/webhooks/<subscription_id>/', methods=['GET', 'DELETE'])
@subscriptions_bp.route('/status/webhooks/<subscription_id>', methods=['GET', 'DELETE'])
def subscription(subscription_id):
    try:
        item = Subscription.objects.get(id=subscription_id)
    except DoesNotExist:
        raise APIError('Subscription not found.', status_code=404)

    user = g.identity.user
    if item.owner.user_id != user.user_id:
        raise APIError(status_code=403)

    if request.method == 'GET':
        return make_json_response(item.get_public_dict())

    if request.method == 'DELETE':

        item.delete()
        return make_json_response({'status_code': 204})
