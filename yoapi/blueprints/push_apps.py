from flask import g, request
from mongoengine import DoesNotExist, NotUniqueError
import requests
from yoapi.accounts import get_user
from yoapi.blueprints.accounts import get_limit_key
from yoapi.constants.limits import GET_ME_LIMIT
from yoapi.contacts import upsert_contact, remove_contact
from yoapi.core import cache, limiter
from yoapi.helpers import make_json_response
from yoapi.models.push_app import PushApp, EnabledPushApp
from yoapi.push_apps import get_push_apps, get_app_by_id, get_enabled_push_apps, enable_push_app
from yoapi.yoflask import Blueprint
from yoapi.yos.send import send_yo

push_apps_bp = Blueprint('push_apps', __name__)


@push_apps_bp.route('/apps/', methods=['GET'], login_required=False)
def apps_get():
    items = get_push_apps()
    return make_json_response({'results': [{
                                               'id': str(item.id),
                                               'app_name': item.app_name,
                                               'category': item.category,
                                               'icon_url': item.icon_url,
                                               'hex_color': item.hex_color,
                                               'is_featured': item.is_featured,
                                               'description': item.description,
                                               'slug': item.slug,
                                               'config': item.config
                                           } for item in items]})


@push_apps_bp.route('/apps/<app_id>/', methods=['GET', 'POST'], login_required=False)
def apps_post(app_id):
    item = get_app_by_id(app_id)

    if request.method == 'GET':

        return make_json_response({
            'id': str(item.id),
            'app_name': item.app_name,
            'category': item.category,
            'icon_url': item.icon_url,
            'hex_color': item.hex_color,
            'is_featured': item.is_featured,
            'description': item.description,
            'short_description': item.short_description,
            'config': item.config
        })

    elif request.method == 'POST':
        if g.identity.user:
            user = g.identity.user
            demo_url = item.demo_url
            requests.post(demo_url, json={'username': user.username})
            return make_json_response({'status_code': 200}), 200
        else:
            return make_json_response({'status_code': 401}), 401


@push_apps_bp.route('/apps/<app_id>/users/', methods=['GET'], login_required=True)
def apps_get_users(app_id):
    app = get_app_by_id(app_id)
    if app.username != g.identity.user.username:
        return make_json_response({'status_code': 401}), 401

    enabled_apps = EnabledPushApp.objects.filter(app=app, is_active=True).select_related()
    users = [enabled_app.user for enabled_app in enabled_apps]

    return make_json_response(
        {'results': [{
                         'username': user.username,
                     }
                     for user in users
        ]
        })


@limiter.limit(GET_ME_LIMIT, key_func=get_limit_key,
               error_message='Too many calls')
@push_apps_bp.route('/enabled_apps/', methods=['GET'], login_required=True)
def enabled_apps():
    items = get_enabled_push_apps(g.identity.user)
    return make_json_response({'results': [{
                                               'id': str(item.app.id),
                                               'app_name': item.app.app_name,
                                               'category': item.app.category,
                                               'description': item.app.description,
                                               'icon_url': item.app.icon_url,
                                               'hex_color': item.app.hex_color
                                           } for item in items]})


@push_apps_bp.route('/enabled_apps/<app_id>/', methods=['GET', 'POST', 'PUT', 'DELETE'], login_required=True)
def enabled_apps_single(app_id):
    app = get_app_by_id(app_id)
    user = g.identity.user

    if request.method == 'POST':
        try:

            enable_push_app(user, app)

            return make_json_response({'status_code': 201}), 201
        except NotUniqueError as e:
            return make_json_response({'status_code': 200}), 200

    elif request.method == 'PUT':

        entry = EnabledPushApp.objects.get(user=user,
                                           app=app)

        entry.config = request.json.config
        entry.is_active = request.json.is_active
        entry.save()
        return make_json_response({'status_code': 200}), 200

    elif request.method == 'DELETE':

        try:
            entry = EnabledPushApp.objects.get(user=user,
                                               app=app)
            entry.delete()
        except DoesNotExist:
            pass

        try:
            app_user = get_user(username=app.username)
            remove_contact(user, app_user)
        except DoesNotExist:
            pass

        cache.delete_memoized(get_enabled_push_apps, user)

        return make_json_response({'status_code': 204}), 204

    elif request.method == 'GET':
        try:
            item = EnabledPushApp.objects.get(user=user,
                                              app=app)
            return make_json_response({
                'app_name': item.app.app_name,
                'description': item.app.description,
                'config': item.config
            })
        except DoesNotExist as e:
            return make_json_response({'status_code': 404}), 404


