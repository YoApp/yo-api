import urllib
import urlparse
from flask import request, g
from mongoengine import DoesNotExist
from yoapi.errors import APIError
from yoapi.helpers import make_json_response
from yoapi.models.integration import Integration, IntegrationType
from yoapi.permissions import assert_admin_permission
from yoapi.yoflask import Blueprint
import requests

integration_bp = Blueprint('integration', __name__, url_prefix='/rpc')


@integration_bp.route('/update_integrations', methods=['PUT'], login_required=True)
def update_integrations():
    assert_admin_permission('Unauthorized')
    payload = request.json

    items = []
    for row in payload:
        row = row.copy()
        items.append(row)

        item_id = row.get('id')
        is_new = False
        if item_id:
            try:
                item = IntegrationType.objects.get(_id=item_id)
            except DoesNotExist:
                raise APIError('The integration %s does not exist' % item_id)

            if row.get('delete'):
                #clear_get_category_cache(category.yo_type,
                #                         content=category.content)
                item.delete()
                item.update({'update_status': 'deleted'})
                continue
        else:
            if row.get('delete'):
                row.update({'update_status': 'skipped'})
                continue
            item = IntegrationType()
            is_new = True

        name = row.get('name').strip()
        description = row.get('description').strip()
        logo_url = row.get('logo_url').strip()
        client_id = row.get('client_id').strip()
        client_secret = row.get('client_secret').strip()
        redirect_uri = row.get('redirect_uri').strip()
        authorization_url = row.get('authorization_url').strip()
        token_url = row.get('token_url').strip()
        scope = row.get('scope').strip()

        if item.name != name:
            item.name = name

        if item.description != description:
            item.description = description

        if item.logo_url != logo_url:
            item.logo_url = logo_url

        if item.client_id != client_id:
            item.client_id = client_id

        if item.client_secret != client_secret:
            item.client_secret = client_secret

        if item.redirect_uri != redirect_uri:
            item.redirect_uri = redirect_uri

        if item.authorization_url != authorization_url:
            item.authorization_url = authorization_url

        if item.token_url != token_url:
            item.token_url = token_url

        if item.scope != scope:
            item.scope = scope

        row.update({'update_status': 'nochange'})
        if is_new:
            row.update({'update_status': 'created'})
        elif item._changed_fields:
            row.update({'update_status': 'updated'})

        if is_new or item._changed_fields:
            item.save()
            row.update({'id': item.id})
            #clear_get_category_cache(category.yo_type,
            #                         content=category.content)

    return make_json_response(result=items)


@integration_bp.route('/get_integrations', methods=['POST'])
def get_integrations():
    integration_types = IntegrationType.objects.all()

    items = [{
                 'id': str(type.id),
                 'name': type.name,
                 'description': type.description,
                 'logo_url': type.logo_url,
                 'auth_url': type.authorization_url + '?' +
                             urllib.urlencode({
                                 'client_id': type.client_id,
                                 'redirect_uri': type.redirect_uri,
                                 'scope': type.scope,
                                 'response_type': 'code'
                             }).replace('+', '%20')
             } for type in integration_types]

    return make_json_response(results=items)


@integration_bp.route('/add_integration', methods=['POST'])
def add_integration():
    auth = request.json.get('auth')
    data = urlparse.parse_qs(auth)
    integration_type_id = request.json.get('id')
    integration_type = IntegrationType.objects.get(id=integration_type_id)

    code = data['code']

    token_url = integration_type.token_url
    redirect_uri = integration_type.redirect_uri

    response = requests.post(token_url, {
        'client_id': integration_type.client_id,
        'client_secret': integration_type.client_secret,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri
    })

    access_token = response.json().get('access_token')
    refresh_token = response.json().get('refresh_token')

    integration = Integration(type=integration_type,
                              user=g.identity.user,
                              access_token=access_token,
                              refresh_token=refresh_token)

    integration.save()

    return 'OK'


@integration_bp.route('/remove_integration', methods=['POST'])
def remove_integration():
    integration_type_id = request.json.get('id')

    integration_type = IntegrationType.objects.get(id=integration_type_id)
    integration = Integration.objects.get(type=integration_type,
                                          user=g.identity.user)

    integration.delete()

    return 'OK'


