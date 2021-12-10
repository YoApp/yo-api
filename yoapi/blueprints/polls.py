# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta
from random import randint
import string
import urllib
import urlparse
import sys
import arrow

from flask import request, g, current_app
from mongoengine import DoesNotExist, Q
from redis import Redis
from rq_scheduler import Scheduler
from yoapi.accounts import get_user, create_user, update_user
from yoapi.async import async_job
from yoapi.blueprints.accounts import route_login
from yoapi.constants.yos import UNREAD_YOS_FETCH_LIMIT
from yoapi.contacts import remove_contact, get_followers, add_contact
from yoapi.core import sendgrid, sns, log_to_slack
from yoapi.errors import APIError
from yoapi.forms import BroadcastYoForm
from yoapi.helpers import make_json_response, random_number_string
from yoapi.jsonp import jsonp
from yoapi.manage import login
from yoapi.models import Yo, Contact, NotificationEndpoint
from yoapi.models.polls_client_app import PollsClientApp
from yoapi.models.push_app import PushApp, EnabledPushApp
from yoapi.notification_endpoints import register_device, get_useragent_profile
from yoapi.services import low_rq
from yoapi.services.scheduler import schedule_yo
from yoapi.yoflask import Blueprint
from yoapi.yos.helpers import construct_yo, acknowledge_yo_received
from yoapi.yos.queries import get_yo_by_id, clear_get_unread_yos_cache, clear_get_yo_cache
from yoapi.yos.send import send_yo, _apply_callback


polls_bp = Blueprint('polls', __name__)


@async_job(rq=low_rq)
def send_results(poll_id):
    poll = Yo.objects.get(id=poll_id)
    from_user = poll.sender

    left_reply_text = poll.response_pair.split('.')[0]
    right_reply_text = poll.response_pair.split('.')[1]

    left_replies = Yo.objects.filter(reply_to=poll_id, text=left_reply_text)
    left_reply_users = []
    for reply in left_replies:
        left_reply_users.append(reply.sender)

    right_replies = Yo.objects.filter(reply_to=poll_id, text=right_reply_text)
    right_reply_users = []
    for reply in right_replies:
        right_reply_users.append(reply.sender)

    left_count = len(left_reply_users) or 0
    right_count = len(right_reply_users) or 0
    total_count = left_count + right_count

    if total_count == 0:
        return

    left_real_reply_text = poll.left_reply or left_reply_text
    right_real_reply_text = poll.right_reply or right_reply_text

    args = {
        'duration': poll.duration_in_minutes / 60,
        'left_reply_text': left_real_reply_text,
        'right_reply_text': right_real_reply_text,
        'total_count': total_count,
        'left_replies_count': left_count,
        'right_replies_count': right_count,
        'left_replies_percent': "{0:.0f}".format(float(left_count) / total_count * 100.0),
        'right_replies_percent': "{0:.0f}".format(float(right_count) / total_count * 100.0),
        'emoji': u'👈'
    }

    left_result_template_string = u'Final results: (' + poll.question[:20] + u'...)\n' + \
                                  u'$total_count voters in $duration hours\n' \
                                  u'$left_replies_percent% - $left_reply_text ($left_replies_count) $emoji\n' \
                                  u'$right_replies_percent% - $right_reply_text ($right_replies_count)'

    if poll.left_share_template:
        left_share_template_string = poll.left_share_template
    else:
        left_share_template_string = u'{0} - {1} or {2} yopolls.co'. \
            format(poll.question, left_real_reply_text, right_real_reply_text)

    left_result_template = string.Template(left_result_template_string)
    left_result = left_result_template.safe_substitute(args)

    left_share_template = string.Template(left_share_template_string)
    left_share_text = left_share_template.safe_substitute(args)

    right_result_template_string = u'Final results: (' + poll.question[:20] + u'...)\n' + \
                                   u'$total_count votes in $duration hours\n' \
                                   u'$left_replies_percent% - $left_reply_text ($left_replies_count)\n' \
                                   u'$right_replies_percent% - $right_reply_text ($right_replies_count) $emoji'

    if poll.right_share_template:
        right_share_template_string = poll.right_share_template
    else:
        right_share_template_string = u'{0} - {1} or {2} yopolls.co'. \
            format(poll.question, left_real_reply_text, right_real_reply_text)

    right_result_template = string.Template(right_result_template_string)
    right_result = right_result_template.safe_substitute(args)

    right_share_template = string.Template(right_share_template_string)
    right_share_text = right_share_template.safe_substitute(args)

    #sound = request.json.get('sound')
    sound = ''

    response_pair = 'Text.Tweet'

    if request.json.get('test_username'):
        left_link = u'sms:&body=' + urllib.quote(left_share_text.encode('utf-8').replace('%', ' percent'))
        right_link = u'https://twitter.com/intent/tweet?text=' + urllib.quote(left_share_text.encode('utf-8'))
        user = get_user(username=request.json.get('test_username'))
        send_yo(sender=from_user, sound=sound, recipients=[user], text=left_result, app_id='co.justyo.yopolls',
                left_link=left_link, right_link=right_link, response_pair=response_pair, ignore_permission=True)
        return make_json_response()

    if len(left_reply_users) > 0:
        left_link = u'sms:&body=' + urllib.quote(left_share_text.encode('utf-8').replace('%', ' percent'))
        right_link = u'https://twitter.com/intent/tweet?text=' + urllib.quote(left_share_text.encode('utf-8'))
        send_yo(sender=from_user, sound=sound, recipients=left_reply_users, text=left_result,
                app_id='co.justyo.yopolls',
                left_link=left_link, right_link=right_link, response_pair=response_pair, ignore_permission=True)

    if len(right_reply_users) > 0:
        left_link = u'sms:&body=' + urllib.quote(right_share_text.encode('utf-8').replace('%', ' percent'))
        right_link = u'https://twitter.com/intent/tweet?text=' + urllib.quote(right_share_text.encode('utf-8'))
        send_yo(sender=from_user, sound=sound, recipients=right_reply_users, text=right_result,
                app_id='co.justyo.yopolls',
                left_link=left_link, right_link=right_link, response_pair=response_pair, ignore_permission=True)


@polls_bp.route('/polls/share/', methods=['POST'], login_required=False)
def share():

    text = u'If you like Yo Polls share it with your best friend 🤗'
    share_text = u'Yo Polls is awesome! try it: {}'.format('http://j.mp/1R1FbQ6')

    left_link = u'sms:&body=' + urllib.quote(share_text.encode('utf-8').replace('%', ' percent'))
    right_link = u'https://twitter.com/intent/tweet?text=' + urllib.quote(share_text.encode('utf-8'))

    newspolls = get_user(username='NEWSPOLLS', ignore_permission=True)
    login(newspolls.user_id)

    send_yo(sender=newspolls,
            sound='silent',
            broadcast=True,
            text=text,
            app_id='co.justyo.yopolls',
            left_link=left_link,
            right_link=right_link,
            response_pair='Text.Tweet',
            ignore_permission=True)

    return make_json_response({})


def get_topic_user(user, topic_id):
    topic_user = get_user(user_id=topic_id)
    if topic_user not in user.children:
        raise APIError('Unauthorized.', status_code=401)
    else:
        return topic_user


def send_confirmation_push(yo_id):
    yo = get_yo_by_id(yo_id)
    sender = yo.sender
    if sender.app_name == 'Sandbox Polls':
        return
    contacts = Contact.objects(target=sender).select_related()
    send_to = []
    for contact in contacts:
        if not contact.did_send_confirmation_push:
            #if contact.owner.username == 'GUEST714436':
            contact.did_send_confirmation_push = True
            contact.save()
            send_to.append(contact.owner)

    if len(send_to) == 0:
        return
    response_pair = 'No.Yes'
    text = 'Do you enjoy ' + sender.app_name + ' and wish to continue receiving polls on this topic? (Swipe to reply)'
    user = get_user(username='FLASHPOLLS')
    yo = send_yo(sender=user, sound='silent', recipients=send_to, text=text,
                 response_pair=response_pair, is_poll=True, ignore_permission=True,
                 app_id='co.justyo.yopolls')
    yo.user_info = {'type': 'confirmation',
                    'app_user_id': sender.user_id}
    yo.save()


@polls_bp.route('/send_results')
def route_send_results():
    poll_id = request.json.get('yo_id')
    send_results.delay(poll_id)
    return make_json_response({})


@polls_bp.route('/login/', methods=['POST'], login_required=False)
def route_polls_login():
    return route_login()


@polls_bp.route('/polls/devices/', methods=['POST'], login_required=False)
def route_polls_devices():
    app_token = request.json.get('app_token')
    push_token = request.json.get('push_token')
    sns.create_endpoint(app_token,
                        push_token,
                        'arn:aws:sns:us-east-1:131325091098:app/APNS_SANDBOX/co.justyo.polls.ios.sdk.test')
    return make_json_response({})


@polls_bp.route('/polls/<poll_id>/', methods=['GET'], login_required=False)
@polls_bp.route('/polls/<poll_id>', methods=['GET'], login_required=False)
@jsonp
def route_get_poll(poll_id):
    yo = get_yo_by_id(poll_id)
    yo.reload()

    result = {}

    left_reply_button = yo.response_pair.split('.')[0]
    right_reply_button = yo.response_pair.split('.')[1]

    left_replies_count = Yo.objects.filter(reply_to=yo, text=left_reply_button).count()
    right_replies_count = Yo.objects.filter(reply_to=yo, text=right_reply_button).count()

    result.update({'id': yo.yo_id})

    result.update({'left_replies_count': left_replies_count})

    result.update({'right_replies_count': right_replies_count})

    if yo.left_reply:
        result.update({'left_reply': yo.left_reply})

    if yo.right_reply:
        result.update({'right_reply': yo.right_reply})

    if yo.question:
        result.update({'question': yo.question})

    return make_json_response(result)


@polls_bp.route('/polls/', methods=['GET'], login_required=False)
@polls_bp.route('/polls', methods=['GET'], login_required=False)
def route_polls():
    polls = Yo.objects.filter(is_poll=True, broadcast=True, recipient_count__gt=10).order_by('-created').limit(10)

    results = []

    for poll in polls:
        poll_json = {
            'id': poll.yo_id
        }
        results.append(poll_json)

    return make_json_response({'results': results})


@polls_bp.route('/cashout', methods=['POST'], login_required=True)
def route_cash_out():
    user = g.identity.user

    sendgrid.send_mail(recipient='or@justyo.co',
                       subject='Flash Polls - Cash out',
                       body=json.dumps(user.get_public_dict(field_list='account')),
                       sender='cashout@flashpolls.com')

    raise APIError('You need a minimum of $10 balance in order to cash out.')

    return make_json_response({})


@polls_bp.route('/broadcast_poll')
def route_broadcast_poll():
    form_args = request.json
    form = BroadcastYoForm.from_json(form_args)
    form.validate()

    from_user = g.identity.user

    response_pair = request.json.get('response_pair')
    text = request.json.get('text')
    left_link = request.json.get('left_link')
    right_link = request.json.get('right_link')
    scheduled_for = request.json.get('scheduled_for')
    left_reply = request.json.get('left_reply')
    right_reply = request.json.get('right_reply')
    duration_in_minutes = request.json.get('duration_in_minutes')

    question = text
    if response_pair == u'🅰.🅱':
        text = text + '\n' + \
               u'🅰 ' + left_reply + '\n' + \
               u'🅱 ' + right_reply
    elif response_pair == u'☝️.✌️':
        text = text + '\n' + \
               u'☝️' + left_reply + '\n' + \
               u'✌️' + right_reply

    if scheduled_for:
        scheduled_for_date = datetime.utcfromtimestamp(int(scheduled_for))
        if request.json.get('test_username'):
            user = get_user(username=request.json.get('test_username'))
            yo = construct_yo(sender=from_user,
                              recipients=[user],
                              sound=form.sound.data,
                              link=form.link.data,
                              location=form.location.data,
                              response_pair=response_pair,
                              text=text,
                              left_link=left_link,
                              right_link=right_link,
                              app_id='co.justyo.yopolls',
                              is_poll=True)
        else:
            yo = construct_yo(sender=from_user,
                              broadcast=True,
                              sound=form.sound.data,
                              link=form.link.data,
                              location=form.location.data,
                              response_pair=response_pair,
                              text=text,
                              left_link=left_link,
                              right_link=right_link,
                              app_id='co.justyo.yopolls',
                              is_poll=True)
        schedule_yo(yo, int(scheduled_for_date.strftime("%s")) * int(1e6))
    else:
        scheduled_for_date = datetime.utcnow()
        if request.json.get('test_username'):
            user = get_user(username=request.json.get('test_username'))
            yo = send_yo(sender=from_user, recipients=[user],
                         sound=form.sound.data, app_id='co.justyo.yopolls',
                         text=text, response_pair=response_pair,
                         left_link=left_link, right_link=right_link, is_poll=True)
        else:
            yo = send_yo(sender=from_user, broadcast=True,
                         sound=form.sound.data, app_id='co.justyo.yopolls',
                         text=text, response_pair=response_pair,
                         left_link=left_link, right_link=right_link, is_poll=True)

    yo.left_share_template = request.json.get('left_share_template')
    yo.right_share_template = request.json.get('right_share_template')
    yo.left_reply = left_reply
    yo.right_reply = right_reply
    yo.duration_in_minutes = duration_in_minutes
    yo.question = question
    yo.app_id = 'co.justyo.yopolls'
    yo.save()

    url = urlparse.urlparse(current_app.config.get('RQ_LOW_URL'))
    conn = Redis(host=url.hostname, port=url.port, db=0, password=url.password)
    scheduler = Scheduler(connection=conn, queue_name='low')
    dt = scheduled_for_date + timedelta(minutes=int(duration_in_minutes))
    scheduler.enqueue_at(dt, send_results, yo.yo_id)

    scheduler.enqueue_at(scheduled_for_date + timedelta(seconds=20), send_confirmation_push, yo.yo_id)

    return make_json_response({'success': True, 'yo_id': yo.yo_id})


@polls_bp.route('/poll_reply')
def route_polls_reply():
    reply_to = request.json.get('reply_to')
    reply_text = request.json.get('context') or request.json.get('text')
    response_pair = request.json.get('response_pair')
    from_push = request.json.get('from_push')
    user = g.identity.user

    if reply_to:

        replied_to_yo = get_yo_by_id(reply_to)

        acknowledge_yo_received(reply_to, status='read', from_push=from_push)

        if replied_to_yo.parent:
            replied_to_yo = replied_to_yo.parent

        #exists = Yo.objects.filter(sender=user, reply_to=replied_to_yo).count() > 0
        #if exists:
        #    raise APIError('Already voted')

        try:
            log_to_slack(u'{}: {} ({}) from {} replied {} from_push={}'.format(replied_to_yo.question[:20],
                                                                               user.display_name,
                                                                               user.username,
                                                                               user.city,
                                                                               reply_text,
                                                                               from_push))
        except Exception as e:
            pass

        yo = construct_yo(sender=user,
                          recipients=[replied_to_yo.sender],
                          context=reply_text,
                          reply_to=replied_to_yo,
                          text=reply_text,
                          app_id='co.justyo.yopolls',
                          ignore_permission=True)

        response = {'success': True, 'yo_id': yo.yo_id}

        if replied_to_yo.is_poll:

            if replied_to_yo.user_info and replied_to_yo.user_info.get('type') == 'confirmation':
                app_user_id = replied_to_yo.user_info.get('app_user_id')
                app_user = get_user(user_id=app_user_id)
                if reply_text == 'Yes':
                    text = u'Awesome! You will continue receiving polls from ' + app_user.app_name
                else:
                    text = u'No worries! You will no longer receive polls from ' + app_user.app_name
                    try:
                        app = PushApp.objects.get(username=app_user.username)
                        entry = EnabledPushApp.objects.get(user=user, app=app)
                        entry.delete()
                    except DoesNotExist:
                        pass
                    try:
                        remove_contact(user, app_user)
                    except DoesNotExist:
                        pass

                flashpolls = get_user(username='FLASHPOLLS')
                send_yo(sender=flashpolls,
                        sound='silent',
                        recipients=[user],
                        text=text,
                        app_id='co.justyo.yopolls',
                        response_pair=response_pair,
                        ignore_permission=True)

                return make_json_response({})

            left_reply_text = replied_to_yo.response_pair.split('.')[0]
            right_reply_text = replied_to_yo.response_pair.split('.')[1]

            left_real_reply_text = replied_to_yo.left_reply or left_reply_text
            right_real_reply_text = replied_to_yo.right_reply or right_reply_text

            left_count = Yo.objects.filter(reply_to=replied_to_yo, text=left_reply_text).count()
            right_count = Yo.objects.filter(reply_to=replied_to_yo, text=right_reply_text).count()

            replied_to_yo.left_replies_count = left_count
            replied_to_yo.right_replies_count = right_count
            replied_to_yo.save()

            total_count = left_count + right_count
            if total_count == 0:
                return

            duration_in_minutes = replied_to_yo.duration_in_minutes or 0

            args = {
                'duration': duration_in_minutes / 60,
                'left_reply_text': left_real_reply_text,
                'right_reply_text': right_real_reply_text,
                'total_count': total_count,
                'left_replies_count': left_count,
                'right_replies_count': right_count,
                'left_replies_percent': "{0:.0f}".format(float(left_count) / total_count * 100.0),
                'right_replies_percent': "{0:.0f}".format(float(right_count) / total_count * 100.0),
                'emoji': u'👈'
            }

            if reply_text == left_reply_text:

                left_replies_percent = u"{0:.0f}%".format(float(left_count) / total_count * 100.0)
                right_replies_percent = u"{0:.0f}%".format(float(right_count) / total_count * 100.0)

                body = left_replies_percent.ljust(5) + ' (' + str(
                    left_count) + ') - ' + left_real_reply_text + u' 👈\n' + \
                       right_replies_percent.ljust(5) + ' (' + str(
                    right_count) + ') - ' + right_real_reply_text + '\n'

                if replied_to_yo.left_share_template:
                    left_share_template_string = replied_to_yo.left_share_template
                else:
                    left_share_template_string = u'"{0}" - {1} or {2}? yopolls.co'. \
                        format(replied_to_yo.question, left_real_reply_text, right_real_reply_text)

                left_share_template = string.Template(left_share_template_string)
                left_share_text = left_share_template.safe_substitute(args)

                left_link = u'sms:&body=' + urllib.quote(left_share_text.encode('utf8'))
                right_link = u'https://twitter.com/intent/tweet?text=' + urllib.quote(left_share_text.encode('utf8'))

            elif reply_text == right_reply_text:

                left_replies_percent = u"{0:.0f}%".format(float(left_count) / total_count * 100.0)
                right_replies_percent = u"{0:.0f}%".format(float(right_count) / total_count * 100.0)

                body = left_replies_percent.ljust(5) + ' (' + str(
                    left_count) + ') - ' + left_real_reply_text + '\n' + \
                       right_replies_percent.ljust(5) + ' (' + str(
                    right_count) + ') - ' + right_real_reply_text + u' 👈\n'

                if yo.right_share_template:
                    right_share_template_string = replied_to_yo.right_share_template
                else:
                    right_share_template_string = u'"{0}" - {1} or {2} yopolls.co'. \
                        format(replied_to_yo.question, left_real_reply_text, right_real_reply_text)

                right_share_template = string.Template(right_share_template_string)
                right_share_text = right_share_template.safe_substitute(args)

                left_link = u'sms:&body=' + urllib.quote(right_share_text.encode('utf8'))
                right_link = u'https://twitter.com/intent/tweet?text=' + urllib.quote(right_share_text.encode('utf8'))

            else:
                return make_json_response(response)

            if user.coins:
                user.coins += 1
            else:
                user.coins = 1
            user.save()

            try:

                if yo.scheduled_for:
                    end_date = arrow.get(replied_to_yo.scheduled_for / 1e6) + timedelta(
                        minutes=replied_to_yo.duration_in_minutes)
                else:
                    end_date = arrow.get(replied_to_yo.created / 1e6) + timedelta(
                        minutes=replied_to_yo.duration_in_minutes)

                if arrow.utcnow() > end_date:
                    header = u'Final results: ({}...)\n'.format(replied_to_yo.question[:20])
                    footer = u'Poll ended: ' + end_date.humanize()
                else:
                    header = u'So far, ({}...)\n'.format(replied_to_yo.question[:20])
                    footer = u'Final results: ' + end_date.humanize()

                send_yo(sender=replied_to_yo.sender,
                        recipients=user.username,
                        text=header +
                             body +
                             footer,
                        response_pair='Text.Tweet',
                        left_link=left_link,
                        right_link=right_link,
                        sound='silent',
                        app_id='co.justyo.yopolls',
                        ignore_permission=True)
            except Exception as e:
                current_app.log_exception(sys.exc_info())

    clear_get_yo_cache(yo.yo_id)
    if yo.reply_to:
        clear_get_yo_cache(yo.reply_to.yo_id)
    _apply_callback.delay(yo.yo_id)

    clear_get_unread_yos_cache(user.user_id, UNREAD_YOS_FETCH_LIMIT, app_id='co.justyo.yopolls')

    return make_json_response(response)


@polls_bp.route('/apps1', methods=['POST', 'GET'])
@polls_bp.route('/apps1/', methods=['POST', 'GET'])
def route_polls_apps():

    user = g.identity.user

    if request.method == 'GET':
        items = PollsClientApp.objects.filter(owner=user)
        return make_json_response({'results': [item.get_public_dict() for item in items]})

    elif request.method == 'POST':
        p12_file = request.files.get('p12_file')
        p12_content = p12_file.stream.read()
        p12_password = request.form.get('p12_password')

        name = request.form.get('name')
        slug = name.lower().replace(' ', '-')

        rv = sns.create_platform_application_with_p12(name=slug,
                                                      platform='APNS_SANDBOX',
                                                      p12_content=p12_content,
                                                      p12_password=p12_password)

        platform_arn = rv.get('CreatePlatformApplicationResponse').get('CreatePlatformApplicationResult').get('PlatformApplicationArn')
        if platform_arn:
            app = PollsClientApp(owner=user,
                                 name=name,
                                 slug=slug,
                                 platform_arn=platform_arn)
            app.save()

            return make_json_response({})

        return APIError()


#TODO look at how smooch is doing the route with app token or not
@polls_bp.route('/apps/<app_token>', methods=['PUT', 'GET', 'DELETE'])
@polls_bp.route('/apps/<app_token>/', methods=['PUT', 'GET', 'DELETE'])
def route_polls_apps_single(app_token):
    p12_file = request.files.get('p12_file')

    if p12_file:
        p12_content = p12_file.stream.read()
        p12_password = request.json.get('p12_password')
        rv = sns.create_platform_application_with_p12(name='test',
                                                      platform='APNS',
                                                      p12_content=p12_content,
                                                      p12_password=p12_password)

    return make_json_response({})


@polls_bp.route('/installations', methods=['POST', 'GET'], login_required=False)
@polls_bp.route('/installations/', methods=['POST', 'GET'], login_required=False)
def route_polls_installations():

    app_token = request.json.get('app_token')
    if app_token is None:
        raise APIError('Missing topic_id parameter')

    if request.method == 'GET':

        user_id = request.json.get('user_id')
        if user_id is None:
            raise APIError('Missing user_id parameter')

        items = NotificationEndpoint.objects.filter(app_token=app_token,
                                                    external_user_id=user_id)
        return make_json_response({'results': [item.as_polls_installation() for item in items]})

    elif request.method == 'POST':

        platform = request.json.get('platform')
        if platform is None:
            raise APIError('Missing platform parameter')

        push_token = request.json.get('push_token')
        if push_token is None:
            raise APIError('Missing push_token parameter')

        endpoints = NotificationEndpoint.objects(app_token=app_token,
                                                 platform=platform,
                                                 token=push_token)

        if len(endpoints) > 0:
            endpoint = endpoints[0]
            user = endpoint.owner
        else:
            padding = random_number_string(length=6)
            username = '%s%s' % ('USER', padding)
            user = create_user(username=username)

        user_id = request.json.get('user_id')
        if user_id:
            update_user(user,
                        ignore_permission=True,
                        external_user_id=user_id)

        try:
            app = PollsClientApp.objects.get(app_token=app_token)
            platform_arn = app.platform_arn
        except DoesNotExist:
            raise APIError('Invalid app_token')

        arn = sns.create_endpoint(platform, push_token, platform_arn)

        profile = get_useragent_profile()
        version = profile.get('app_version')
        os_version = profile.get('os_version')
        sdk_version = profile.get('sdk_version')

        # Upsert so calls in quick succession succeed.
        endpoints.modify(upsert=True,
                         set__token=push_token,
                         set__platform=platform,
                         set__owner=user,
                         set__arn=arn,
                         set__version=version,
                         set__os_version=os_version,
                         set__sdk_version=sdk_version)

        return make_json_response({})


@polls_bp.route('/installations/<installation_id>', methods=['POST', 'GET', 'DELETE'], login_required=False)
@polls_bp.route('/installations/<installation_id>/', methods=['POST', 'GET', 'DELETE'], login_required=False)
def route_polls_installations_single(installation_id):

    user = g.identity.user
    item = NotificationEndpoint.objects.get(owner=user, installation_id=installation_id)

    if request.method == 'GET':
        return make_json_response(item.as_polls_installation())

    elif request.method == 'DELETE':
        item.delete()
        return make_json_response({'status_code': 204})

    elif request.method == 'PUT':

        # nothing to edit

        return make_json_response(item.as_polls_installation())


@polls_bp.route('/topics', methods=['GET', 'POST'])
@polls_bp.route('/topics/', methods=['GET', 'POST'])
def route_polls_topics():
    user = g.identity.user
    if request.method == 'GET':
        items = user.children
        return make_json_response({'results': [item.as_topic() for item in items]})

    if request.method == 'POST':
        username = 'POLL' + str(randint(1000, 9999))
        params = {
            'parent': user,
            'username': username,
            'name': request.json.get('name'),
            'description': request.json.get('description'),
            'callback_url': request.json.get('callback_url')
        }
        topic_user = create_user(**params)
        topic_user.save()
        return make_json_response(topic_user.as_topic())


@polls_bp.route('/topics/<topic_id>', methods=['GET', 'PUT', 'DELETE'])
@polls_bp.route('/topics/<topic_id>/', methods=['GET', 'PUT', 'DELETE'])
def route_polls_topics_single(topic_id):
    topic_user = get_topic_user(g.identity.user, topic_id)

    if request.method == 'GET':
        return make_json_response(topic_user.as_topic())

    elif request.method == 'DELETE':
        topic_user.delete()
        return make_json_response({'status_code': 204})

    elif request.method == 'PUT':

        editable_fields = ['name', 'description', 'callback_url']

        for field in editable_fields:
            if request.json.get(field):
                setattr(topic_user, field, request.json.get(field))

        topic_user.save()

        return make_json_response(topic_user.as_topic())


@polls_bp.route('/subscriptions', methods=['GET', 'POST'])
@polls_bp.route('/subscriptions/', methods=['GET', 'POST'])
def route_polls_subscriptions():
    user = g.identity.user

    topic_id = request.json.get('topic_id')
    if topic_id is None:
        raise APIError('Missing topic_id parameter')

    topic_user = get_topic_user(user, topic_id)

    if request.method == 'GET':
        items = get_followers(topic_user, ignore_permission=True)
        return make_json_response({'results': [item.as_subscription() for item in items]})

    if request.method == 'POST':
        contact = add_contact(user, topic_user, ignore_permission=True)
        return make_json_response(contact.as_subscription())


@polls_bp.route('/subscriptions/<subscription_id>', methods=['GET', 'PUT', 'DELETE'])
@polls_bp.route('/subscriptions/<subscription_id>/', methods=['GET', 'PUT', 'DELETE'])
def route_polls_subscriptions_single(topic_id):
    topic_user = get_user(user_id=topic_id)

    if request.method == 'GET':
        return make_json_response(topic_user.as_topic())

    elif request.method == 'DELETE':
        topic_user.delete()
        return make_json_response({'status_code': 204})

    elif request.method == 'PUT':

        editable_fields = ['name', 'description', 'callback_url']

        for field in editable_fields:
            if request.json.get(field):
                setattr(topic_user, field, request.json.get(field))

        topic_user.save()

        return make_json_response(topic_user.as_topic())