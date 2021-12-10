# -*- coding: utf-8 -*-

"""Callbacks for external services"""

# pylint: disable=invalid-name

import json
import sys

import re
from flask import current_app, request
from mongoengine import DoesNotExist, MultipleObjectsReturned
from ..accounts import (complete_account_verification_by_sms)
from ..callbacks import remove_disabled_endpoint, consume_pseudo_user
from ..errors import APIError
from ..helpers import make_json_response
from ..models import User
from ..security import load_identity
from yoapi.yos.send import _push_to_recipient
from ..yoflask import Blueprint
from ..core import sns, twilio, log_to_slack, redis


callback_bp = Blueprint('callback', __name__, url_prefix='/callback')


@callback_bp.route('/sns', login_required=False)
def route_sns_callback():
    topic_arn = request.json.get('TopicArn')
    if topic_arn != sns.SYS_DELIVERY_FAILURE_ARN:
        # We do not currently process any other requests
        return make_json_response()

    # If this request does not contain a valid Message payload simply return
    # 200. This can occure when subscribing this url to sns
    message = request.json.get('Message')
    try:
        message_json = json.loads(message)
    except ValueError:
        return make_json_response()

    if message_json.get('FailureType') in sns.REMOVE_ON_FAILURE_TYPES:
        remove_disabled_endpoint(message_json.get('EndpointArn'))

    return make_json_response()


@callback_bp.route('/gen_204', login_required=False)
def route_no_response():
    return make_json_response(status_code=204)


@callback_bp.route('/log_exception', login_required=False)
def route_log_exception():
    # Simply return 200 and allow the logger to put the payload
    # in the logs
    return make_json_response(status_code=204)


@callback_bp.route('/sms', login_required=False)
def route_sms_callback():
    """Enables gen_sms_hash to work with reverse phone verification.
    Twilio will send a post to this endpoint when it receives a text message
    """
    #account_sid = request.json.get('AccountSid')
    from_phone_number = request.json.get('From')
    to_phone_number = request.json.get('To')
    if to_phone_number == from_phone_number:
        return ''
    message_body = request.json.get('Body') or request.json.get('Text')

    #twilio_account_sid = current_app.config.get('TWILIO_ACCOUNT_SID')
    #account_mismatch = account_sid != twilio_account_sid
    #if account_mismatch:
            #or number_mismatch:
    #    raise APIError('Unauthorized request', status_code=401)

    token_match = re.search(r'Code[ ]?:[ ]?([a-zA-Z0-9]{32})', message_body)
    if not token_match:

        if redis.get('msg3:' + from_phone_number) is None:
            redis.set('msg3:' + from_phone_number, 60*60*24*356)
            twilio.send(from_phone_number, 'Yo! messages here aren\'t being read. Try our app: http://justyo.co (reply stop to stop)')

        log_to_slack('{} -> {}: {}'.format(from_phone_number, to_phone_number, message_body))
        raise APIError('Token not found in body')
    token = token_match.group(1)

    try:
        user = User.objects(temp_token__token=token).get()
    except (MultipleObjectsReturned, DoesNotExist):
        current_app.log_exception(sys.exc_info())
        log_to_slack('token: ' + token)
        raise APIError('Invalid Token')

    load_identity(user.user_id)
    complete_account_verification_by_sms(user,
                                         token_match.group(1),
                                         from_phone_number)
    try:
        consume_pseudo_user(user, from_phone_number)
    except:
        current_app.log_exception(sys.exc_info())

    # TODO send a silent push to the device to tell it to refresh contacts
    # if consume_pseudo_user returns true
    return make_json_response()


@callback_bp.route('/command_ack', login_required=True)
def route_command_ack():
    request.log_as_event = True

    #status_code = request.json.get('status_code')
    #command_id = request.json.get('id')
    #command = request.json.get('command')

    yo_id = request.json.get('context').get('yo_id')
    _push_to_recipient(yo_id, protocol='sns', add_response_acked=True)

    return make_json_response(status_code=200)