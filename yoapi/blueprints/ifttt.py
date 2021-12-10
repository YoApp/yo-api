# coding=utf-8
from datetime import datetime
from flask import request, g
from yoapi.accounts import get_user, user_exists
from yoapi.errors import APIError
from yoapi.helpers import make_json_response
from yoapi.models import Yo
from yoapi.models.status import Status
from yoapi.status import update_status
from yoapi.yoflask import Blueprint
from yoapi.yos.send import send_yo

ifttt_bp = Blueprint('ifttt_bp', __name__)

YO_APP_CHANNEL_KEY = 'qGlb3SPhsknep-AnujVJ4OSrCiD593tbBsmVfCNmyBpgGA5laUgcinyb7yXRvCsj'
YO_STATUS_CHANNEL_KEY = 'PzAt510ceTx7CCoEQzJGwDIppgzDkRvzua7rXt4kQZzZpO9usmij369h2aG7aVy9'


@ifttt_bp.route('/ifttt/v1/test/setup', methods=['GET', 'POST'], login_required=False)
def setup():
    channel_key = request.headers.get('IFTTT-Channel-Key')
    if channel_key == YO_APP_CHANNEL_KEY:

        return '''{
          "data": {
            "accessToken": "2u2bZcXfHfLXqifSLh7x7FMzxX0Hgv",
            "samples": {
              "actions": {
                "send_a_yo": {
                    "username": "OR",
                    "link": "http://google.com"
                }
              },
              "actionRecordSkipping": {
                "send_a_yo": {
                    "username": "2invalid-username",
                    "link": "http://google.com"
                }
              }
            }
          }
        }'''

    elif channel_key == YO_STATUS_CHANNEL_KEY:
        return u'''{
          "data": {
            "accessToken": "GkA5tJbxNiSMT2lkbc6VsW5e8f44ge",
            "samples": {
              "actions": {
                "update_status": {
                    "shortname": ":thumbsup:"
                }
              },
              "actionRecordSkipping": {
                "update_status": {
                    "shortname": "invalid-status"
                }
              }
            }
          }
        }'''

    else:
        raise APIError('Invalid channel key', status_code=401)


@ifttt_bp.route('/ifttt/v1/status', methods=['GET', 'POST'], login_required=False)
def status():
    channel_key = request.headers.get('IFTTT-Channel-Key')
    if channel_key not in [YO_APP_CHANNEL_KEY, YO_STATUS_CHANNEL_KEY]:
        raise APIError('Invalid channel key', status_code=401)
    return 'OK'


@ifttt_bp.route('/ifttt/v1/user/info', methods=['GET', 'POST'], login_required=True)
def user():
    user = g.identity.user
    resp = make_json_response({
        u'data': {
            u'id': user.id,
            u'name': user.username
        }
    })
    resp.headers['Content-type'] = 'application/json; charset=utf-8'
    return resp


@ifttt_bp.route('/ifttt/v1/triggers/yo_from_me_to_ifttt_yo_account', methods=['GET', 'POST'], login_required=True)
def yo_from_me_to_ifttt_yo_account():
    user = g.identity.user
    ifttt_user = get_user(username='IFTTT')
    limit = request.json.get('limit')
    if limit:
        yos = Yo.objects.filter(sender=user, recipient=ifttt_user).limit(limit).order_by('-created')
    elif limit == 0:
        yos = []
    else:
        yos = Yo.objects.filter(sender=user, recipient=ifttt_user).limit(3).order_by('-created')

    results = []
    for yo in yos:
        if not yo.has_dbrefs():
            results.append({
                "link": yo.link,
                "from": yo.sender.username if yo.sender else yo.parent.sender.username,
                "yo_time": datetime.fromtimestamp(yo.created / 1000000).isoformat(),
                "meta": {
                    "id": yo.yo_id,
                    "timestamp": yo.created / 1000000
                }})

    resp = make_json_response(data=results)
    resp.headers['Content-type'] = 'application/json; charset=utf-8'
    return resp


@ifttt_bp.route('/ifttt/v1/triggers/yo_received', methods=['GET', 'POST'], login_required=True)
def yo_received():
    user = g.identity.user
    limit = request.json.get('limit')
    if limit:
        yos = Yo.objects.filter(recipient=user).limit(limit).order_by('-created')
    elif limit == 0:
        yos = []
    else:
        yos = Yo.objects.filter(recipient=user).limit(3).order_by('-created')

    results = []
    for yo in yos:
        if not yo.has_dbrefs():
            results.append({
                "link": yo.link,
                "from": yo.sender.username if yo.sender else yo.parent.sender.username,
                "yo_time": datetime.fromtimestamp(yo.created / 1000000).isoformat(),
                "meta": {
                    "id": yo.yo_id,
                    "timestamp": yo.created / 1000000
                }})

    resp = make_json_response(data=results)
    resp.headers['Content-type'] = 'application/json; charset=utf-8'
    return resp


@ifttt_bp.route('/ifttt/v1/actions/send_a_yo', methods=['GET', 'POST'], login_required=True)
def send_a_yo():
    if not request.json.get('actionFields'):
        raise APIError('Missing username')

    username = request.json.get('actionFields').get('username')
    if not username:
        raise APIError('Missing username')

    if not user_exists(username.upper()):
        resp = make_json_response({'errors': [{'message': 'User does not exist', 'status': 'SKIP'}]}, status_code=400)
        resp.headers['Content-type'] = 'application/json; charset=utf-8'
        return resp

    user = g.identity.user
    yo = send_yo(sender=user,
                 link=request.json.get('actionFields').get('link'),
                 recipients=request.json.get('actionFields').get('username'),
                 app_id='co.justyo.yoapp')

    resp = make_json_response(data=[{
                                        'id': yo.yo_id
                                    }])
    resp.headers['Content-type'] = 'application/json; charset=utf-8'
    return resp


@ifttt_bp.route('/ifttt/v1/triggers/status_updated', methods=['GET', 'POST'], login_required=True)
def status_updated():
    user = g.identity.user
    limit = request.json.get('limit')
    if limit:
        status_updates = Status.objects.filter(user=user).limit(limit).order_by('-created')
    elif limit == 0:
        status_updates = []
    else:
        status_updates = Status.objects.filter(user=user).limit(3).order_by('-created')

    results = map(lambda status_update: {
        "status": status_update.status,
        "status_url": 'https://yostat.us/' + status_update.user.username,
        "created_at": datetime.fromtimestamp(status_update.created / 1000000).isoformat(),
        "meta": {
            "id": str(status_update.id),
            "timestamp": status_update.created / 1000000
        }}
                  , status_updates)

    resp = make_json_response(data=results)
    resp.headers['Content-type'] = 'application/json; charset=utf-8'
    return resp


@ifttt_bp.route('/ifttt/v1/actions/update_status', methods=['GET', 'POST'], login_required=True)
def route_update_status():
    if not request.json.get('actionFields'):
        raise APIError('Missing status')

    status = request.json.get('actionFields').get('shortname')
    if not status:
        raise APIError('Missing status')

    if len(status) > 2 and not status.startswith(':'):
        resp = make_json_response({'errors': [{'message': 'Invalid status - can be only a single emoji', 'status': 'SKIP'}]}, status_code=400)
        resp.headers['Content-type'] = 'application/json; charset=utf-8'
        return resp

    user = g.identity.user
    status_update = update_status(user, status)

    resp = make_json_response(data=[{
                                        'id': str(status_update.id)
                                    }])
    resp.headers['Content-type'] = 'application/json; charset=utf-8'
    return resp


path_to_emoji_status_dict = {
    'update_status_to_home': u'🏡',
    'update_status_to_a_laptop_emoji': u'💻',
    'update_status_to_suitcase_emoji': u'💼',
    'update_status_to_a_beer_emoji': u'🍻'
}

@ifttt_bp.route('/ifttt/v1/actions/update_status_to_home', methods=['POST'], login_required=True)
@ifttt_bp.route('/ifttt/v1/actions/update_status_to_a_laptop_emoji', methods=['POST'], login_required=True)
@ifttt_bp.route('/ifttt/v1/actions/update_status_to_suitcase_emoji', methods=['POST'], login_required=True)
@ifttt_bp.route('/ifttt/v1/actions/update_status_to_a_beer_emoji', methods=['POST'], login_required=True)
def route_update_status_specific():
    user = g.identity.user

    status = path_to_emoji_status_dict.get(request.path.replace('/ifttt/v1/actions/', ''))
    status_update = update_status(user, status)

    resp = make_json_response(data=[{
                                        'id': str(status_update.id)
                                    }])
    resp.headers['Content-type'] = 'application/json; charset=utf-8'
    return resp

