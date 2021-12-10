from datetime import timedelta, datetime
from functools import wraps

from flask import g, request
from mongoengine import DoesNotExist
from oauthlib.common import generate_token
from werkzeug.security import gen_salt
from yoapi.blueprints.accounts import route_set_me, route_get_me
from yoapi.blueprints.contacts import route_list_contacts, route_add_contact
from yoapi.blueprints.yos import route_get_unread_yos, route_yo
from yoapi.core import oauth
from yoapi.errors import APIError
from yoapi.helpers import make_json_response
from yoapi.models.oauth import Client, Token
from yoapi.yoflask import Blueprint


rest_bp = Blueprint('rest', __name__)


def get_limit_key():
    if g.identity.user:
        return str('rest:%s' % g.identity.user.username)
    else:
        return str('rest:%s' % g.identity.client.client_id)


@rest_bp.route('/clients/', methods=['GET', 'POST'], login_required=False)
@rest_bp.route('/clients', methods=['GET', 'POST'], login_required=False)
def clients():
    user = g.identity.user
    if request.method == 'GET':
        client_id = request.args.get('client_id')
        if client_id:
            item = Client.objects.get(client_id__iexact=client_id)
            return make_json_response({'app': {
                'name': item.name,
                'description': item.description,
            }})
        else:
            items = Client.objects(user_id=str(user.id))
            return make_json_response({'clients': [{
                'name': item.name,
                'description': item.description,
                'client_id': item.client_id,
                'client_secret': item.client_secret,
                'default_redirect_uri': item.default_redirect_uri,
                'callback_url': item.callback_url
            } for item in items]})

    if request.method == 'POST':
        item = Client(
            client_id=gen_salt(40),
            client_secret=gen_salt(50),
            redirect_uris=[request.json.get('redirect_uri')],
            default_redirect_uri=request.json.get('redirect_uri'),
            callback_url=request.json.get('callback_url'),
            default_scopes=['basic'],
            user_id=str(user.id),
            name=request.json.get('name'),
            description=request.json.get('description')
        )
        item.save()
    return make_json_response(
        client_id=item.client_id,
        client_secret=item.client_secret
    )


@rest_bp.route('/clients/<client_id>/', methods=['GET', 'DELETE', 'PUT'])
def client(client_id):
    try:
        item = Client.objects.get(client_id=client_id)
    except DoesNotExist:
        raise APIError('Client not found.', status_code=404)

    if request.method == 'GET':
        return make_json_response({'app': {
            'name': item.name,
            'description': item.description,
            'default_redirect_uri': item.default_redirect_uri,
            'callback_url': item.callback_url
        }})

    if request.method == 'DELETE':
        user = g.identity.user
        item = Client.objects.get(client_id=client_id)
        if item.user_id == str(user.id):
            item.delete()
            return make_json_response({'status_code': 204})
        else:
            raise APIError('Unauthorized.', status_code=401)

    if request.method == 'PUT':

        item = Client.objects.get(client_id=client_id)

        user = g.identity.user
        if item.user_id != str(user.id):
            raise APIError('Unauthorized.', status_code=401)

        if request.json.get('name'):
            item.name = request.json.get('name')

        if request.json.get('description'):
            item.description = request.json.get('description')

        if request.json.get('default_redirect_uri'):
            item.default_redirect_uri = request.json.get('default_redirect_uri')
            item.redirect_uris = [item.default_redirect_uri]

        if request.json.get('callback_url'):
            item.callback_url = request.json.get('callback_url')

        if request.json.get('callback'):
            item.callback_url = request.json.get('callback')

        item.save()
        return make_json_response({'status_code': 204, 'app': {
            'name': item.name,
            'description': item.description,
            'default_redirect_uri': item.default_redirect_uri,
            'callback_url': item.callback_url
        }})


@rest_bp.route('/authorized_apps/<client_id>/', methods=['GET', 'DELETE'])
def single_authorized_app(client_id):
    user = g.identity.user
    if request.method == 'GET':
        try:
            item = Client.objects.get(
                client_id=client_id,
            )
        except DoesNotExist:
            raise APIError('Client not found.', status_code=404)
        return make_json_response({'app': {
            'name': item.name,
            'description': item.description
        }})

    if request.method == 'DELETE':
        try:
            token = Token.objects.get(
                user=user.id,
                client_id=client_id
            )
            token.delete()
        except DoesNotExist:
            raise APIError('Client not found.', status_code=404)
        return make_json_response()


@rest_bp.route('/authorized_apps/', methods=['GET'])
def authorized_apps():
    user = g.identity.user
    if request.method == 'GET':
        try:
            tokens = Token.objects(
                user=user.id
            ).select_related()
        except DoesNotExist:
            pass

        clients = [token.client for token in tokens]
        public_data_only = []
        for client in clients:
            if client:
                public_data_only.append({'name': client.name,
                                         'description': client.description,
                                         'client_id': client.client_id})

        return make_json_response({'authorized_apps': public_data_only})

    if request.method == 'DELETE':

        if request.args.get('client_id'):
            item = Client(
                client_id=gen_salt(40),
                client_secret=gen_salt(50),
                redirect_uris=[request.json.get('redirect_uri')],
                default_redirect_uri=request.json.get('redirect_uri'),
                default_scopes=['basic'],
                user_id=str(user.id),
                name=request.json.get('name'),
                description=request.json.get('description')
            )
            item.save()
        return make_json_response(
            client_id=item.client_id,
            client_secret=item.client_secret,
        )


@rest_bp.route('/access_token/', methods=['GET'])
@rest_bp.route('/access_token', methods=['GET'])
def access_token():
    user = g.identity.user
    item = Client.objects.get(
        client_id__iexact=request.args.get('client_id')
    )
    Token.objects(client_id=item.client_id, user=user).delete()

    expires = datetime.utcnow() + timedelta(days=365)

    token = Token(access_token=generate_token(),
                  token_type=' Bearer',
                  scopes=['basic'],
                  expires=expires,
                  client_id=item.client_id,
                  user=user).save()
    return make_json_response({'access_token': token.access_token})


@rest_bp.route('/contacts/', methods=['GET', 'POST'], login_required=True)
def contacts():
    if request.method == 'GET':
        return route_list_contacts()
    if request.method == 'POST':
        return route_add_contact()


def insert_bearer():
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):

            if request.json.get('access_token'):
                new_headers = {}
                new_headers.update(request.headers)
                new_headers['Authorization'] = 'Bearer ' + request.json.get('access_token')
                request.headers = new_headers

            return f(*args, **kwargs)
        return decorated
    return wrapper


@rest_bp.route('/yos/', methods=['GET', 'POST'], login_required=True)
@insert_bearer()
@oauth.require_oauth()
def yos():
    if request.method == 'GET':
        return route_get_unread_yos()
    if request.method == 'POST':
        return route_yo(request.oauth.client)


@rest_bp.route('/me/', methods=['GET', 'PUT'], login_required=True)
def me():
    if request.method == 'GET':
        user = g.identity.user
        return make_json_response(user.get_public_dict(field_list='public'))
    if request.method == 'PUT':
        return route_set_me()


@rest_bp.route('/waitlist/', methods=['GET'], login_required=False)
def get_waitlist():
    return make_json_response({
        'spot': '1353',
        'is_waitlist': True,
        'magic_word': 'banana'
    })




