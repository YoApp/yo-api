# -*- coding: utf-8 -*-

import csv
import datetime
import time
import sys
from pprint import pprint
from uuid import uuid4

import pytz
import re
import gevent
from pyslack import SlackClient
from flask import json, current_app
from flask_script import Option
from flask_principal import identity_changed, Identity
from mongoengine.connection import get_db
from .mongomigration import (UserImporter, HierarchyImporter, ContactImporter,
                             BlockedImporter, BitlyImporter, WelcomeImporter,
                             YoImporter, UdidImporter, InstallationImporter,
                             YoCollectionCleaner, DeviceIdCleaner,
                             PhoneNumberCleaner)
from .utils import (print_response, print_user, print_decoded_token,
                    save_config, load_config, print_object_section)
from .manager import Manager, YoShell, LoggedInYoShell, Command, login
from .. import models
from ..models import Yo
from ..security import jwt
from ..core import sns, principals, cache, parse
from ..accounts import (clear_get_user_cache, find_users,
                        get_user, record_signup_location, update_user)
from ..constants.regex import USERNAME_REGEX
from ..contacts import clear_get_contacts_cache, get_contact_usernames, get_followers, upsert_contact
from ..notification_endpoints import subscribe, clear_get_user_endpoints_cache, \
    get_user_endpoints, register_device
from ..models import (User, Device, SignupLocation,
                      NotificationEndpoint)
from ..parse import Follower
from ..helpers import iso8601_from_usec, get_usec_timestamp
from yoapi.constants.sns import APP_ID_TO_ARN_IDS
from yoapi.constants.yos import UNREAD_YOS_FETCH_LIMIT
from yoapi.models.push_app import EnabledPushApp
from yoapi.models.reengagement_push import ReengagementPush
from yoapi.urltools import UrlHelper
from ..yos.helpers import construct_yo
from ..yos.queries import (clear_get_yos_sent_cache,
                           clear_get_yos_received_cache, get_yos_received, get_yos_sent, clear_get_unread_yos_cache)
from ..yos.send import _send_yo, send_yo

slack = SlackClient('xoxp-2381049824-2381049826-2947402978-7335b3')


class ClearCache(Command):
    option_list = [
        Option('--username'),
    ]

    # pylint: disable=method-hidden
    def run(self, username=None):
        if username:
            user = get_user(username=username)
            clear_get_user_cache(user)
            clear_get_contacts_cache(user)
            clear_get_yos_sent_cache(user)
            clear_get_yos_received_cache(user)
            clear_get_user_endpoints_cache(user)
        else:
            cache.clear()


class FixPolls(Command):

    def run(self):
        yo_team = get_user(username='YOTEAM', ignore_permission=True)
        login(yo_team.user_id)
        enabled_apps = EnabledPushApp.objects.filter(is_active=True).select_related()
        for enabled_app in enabled_apps:
            if enabled_app.has_dbrefs():
                continue
            app_user = get_user(username=enabled_app.app.username)

            upsert_contact(enabled_app.user, app_user, ignore_permission=True)
            print 'ok'


class SendPushToFlashPollsUsers(Command):

    def run(self):
        newspolls = get_user(username='NEWSPOLLS', ignore_permission=True)
        login(newspolls.user_id)

        endpoints = NotificationEndpoint.objects.filter(platform__in=
                                                        ['com.flashpolls.beta.dev',
                                                        'com.flashpolls.beta.prod',
                                                        'com.flashpolls.flashpolls.dev',
                                                        'com.flashpolls.flashpolls.prod',
                                                        'com.flashpolls.beta',
                                                        'com.thenet.flashpolls.dev',
                                                        'com.thenet.flashpolls.prod'
                                                        ])
        for e in endpoints:
            user = e.owner
            yo = send_yo(sender=newspolls,
                     recipients=[user],
                     app_id='co.justyo.yopolls',
                     text='We moved to a new app!',
                     right_link='itms://itunes.apple.com/us/app/apple-store/id1071332021?mt=8',
                     response_pair='Later.Download',
                     ignore_permission=True)
            clear_get_unread_yos_cache(user.user_id, UNREAD_YOS_FETCH_LIMIT, app_id='co.justyo.yopolls')
            print 'Sent to {}'.format(user.username)


class SendPushToYoUsers(Command):

    def run(self):
        from_user = get_user(username='YOTEAM', ignore_permission=True)
        login(from_user.user_id)

        endpoints = NotificationEndpoint.objects.filter(platform__in=
                                                        APP_ID_TO_ARN_IDS.get('co.justyo.yoapp'))

        sent = ['HANNNAH666'
                ,'TYUUKI'
                ,'TALLMANZAC'
                ,'ALLIEGOLD'
                ,'FUKUKU3'
                ,'SEANTHESETTER'
                ,'BENRAGER'
                ,'DANGLAENZER'
                ,'JAYDEESWAG'
                ,'MATMOU5CK'
                ,'JBRAYTON'
                ,'DIO'
                ,'CALPHIE'
                ,'MATITO'
                ,'JOSHLER'
                ,'ANNA207'
                ,'YUUKKEE'
                ,'CASSIE529'
                ,'COLENOSCOPY'
                ,'FLAB02'
                ,'EWEX']

        days_prior = datetime.timedelta(days=-7)
        days_prior_usec = get_usec_timestamp(days_prior)

        index = 0
        for e in endpoints:
            user = e.owner

            if not user:
                continue

            if user.username in sent:
                print 'Skipped1 {}'.format(user.username)
                continue

            if user.last_reengamement_push_time and user.last_reengamement_push_time > days_prior_usec:
                print 'Skipped2 {}'.format(user.username)
                continue

            user_endpoints = get_user_endpoints(user, app_id='co.justyo.yopolls', ignore_permissions=True)
            if len(user_endpoints) > 0:
                continue
            yo = send_yo(sender=from_user,
                         recipients=[user],
                         app_id='co.justyo.yoapp',
                         text=u'Does Donald Trump have small hands? ☝️🖐',
                         link='http://j.mp/1QH8CU6',
                         sound='silent',
                         ignore_permission=True)
            update_user(user, last_reengamement_push_time=get_usec_timestamp(), ignore_permission=True)
            clear_get_unread_yos_cache(user.user_id, UNREAD_YOS_FETCH_LIMIT, app_id='co.justyo.yoapp')
            print 'Sent to {} {}'.format(user.username, index)

            index = index + 1

            if index > 999:
                return




class FixPolls1(Command):

    def run(self):


        array = [

            {
                'username': 'GUEST280777',
                'token': 'ad443cedc20fb947b4b25dfd9cf79fd3403aed4228a4d8516ff67fcfc5125841',
                'installation_id': 'b05808482dcd5f6efb532ad8aac4d835ba813b17'
            },
            {
                'username': 'GUEST259000',
                'token': '77fd29b3e002add1d495a860f8ac837f8e9fe68d3008f679ba4db82af74ff16e',
                'installation_id': '63f8a3aca96e21d891069038cd89688ec3a9ed7c'
            },
            {
                'username': 'GUEST549125',
                'token': '77fd29b3e002add1d495a860f8ac837f8e9fe68d3008f679ba4db82af74ff16e',
                'installation_id': '63f8a3aca96e21d891069038cd89688ec3a9ed7c'
            }


        ]

        for user_dict in array:
            user = get_user(username=user_dict.get('username'), ignore_permission=True)
            login(user.user_id)
            clear_get_user_endpoints_cache(user)
            register_device(user.user_id, 'com.flashpolls.beta', user_dict.get('token'), user_dict.get('installation_id'))


class CreateUser(Command):
    option_list = [
        Option('--username'),
        Option('--password'),
        Option('--jwt_expiration_delta', default=1e9)
    ]

    # pylint: disable=method-hidden
    def run(self, username, password, jwt_expiration_delta):
        params = {'username': username,
                  'password': password}

        # Set a custom JWT expiration delta.
        current_app.config['JWT_EXPIRATION_DELTA'] = jwt_expiration_delta

        res = self.jsonpost('/rpc/sign_up', data=params)
        print_response(res)

        jwt_token = json.loads(res.data).get('tok')
        if jwt_token:
            decoded_token = jwt.decode_callback(jwt_token)
            print_decoded_token(decoded_token)
            user = jwt.user_callback(decoded_token)


class GetParseFollowers(Command):
    option_list = [
        Option('--username'),
    ]

    # pylint: disable=method-hidden
    def run(self, username):
        query = Follower.Query.filter(followee=username)
        documents = query.limit(100)
        n = 1
        while documents:
            for document in documents:
                print document.follower, document.objectId
            documents = query.skip(n * 100).limit(100)
            n += 1


class GetYos(Command):
    option_list = [
        Option('--admin'),
        Option('--sender'),
        Option('--recipient'),
    ]

    # pylint: disable=method-hidden
    def run(self, admin=None, recipient=None, sender=None):
        login(admin)
        if sender:
            user = get_user(username=sender)
            yos = get_yos_sent(user)
        if recipient:
            user = get_user(username=recipient)
            yos = get_yos_received(user)

        for i, yo in enumerate(yos):
            data = yo.to_dict()
            data['nr'] = i
            data['created'] = iso8601_from_usec(yo.created)
            data['sender'] = yo.sender.username
            data['recipients'] = [r.username for r in yo.recipients]
            pprint(data)


class DecodeToken(Command):
    option_list = [
        Option('--jwt_token')
    ]

    # pylint: disable=method-hidden
    def run(self, jwt_token):
        decoded_token = jwt.decode_callback(jwt_token)
        print_decoded_token(decoded_token)


class GetHierarchy(Command):
    option_list = [
    ]

    # pylint: disable=method-hidden
    def run(self):
        fieldnames = ['_id', 'username', 'parent', 'created', 'updated']

        # The ID field needs a different name in query vs csv dict writer.
        csv_fieldnames = fieldnames[:]
        csv_fieldnames[0] = 'id'

        writer = csv.DictWriter(
            sys.stderr, fieldnames=fieldnames, extrasaction='ignore',
            restval='', quoting=csv.QUOTE_ALL)
        writer.writeheader()

        database = get_db()
        collection = database[User._get_collection_name()]
        users = collection.find(
            {},
              dict(zip(fieldnames, [1] * len(fieldnames))))

        for i, user in enumerate(users):
            if 'parent' in user:
                user['parent'] = str(user['parent'])
            writer.writerow(user)


class UpdateUser(Command):
    option_list = [
        Option('--target_id'),
        Option('--set__api_token'),
        Option('--set__password'),
        Option('--set__phone'),
        Option('--set__email')
    ]

    # pylint: disable=method-hidden
    def run(self, target_id=None, **kwargs):
        # Prepare the fake request.
        current_app.preprocess_request()
        # Create an identity.
        identity = Identity(target_id)
        # Set this identity on the thread.
        principals.set_identity(identity)
        # Tell listeners that the identity has changed.
        identity_changed.send(current_app, identity=identity)

        user = get_user(user_id=target_id)
        args = dict([(key.split('__')[1], value)
                     for key, value in kwargs.items() if value])
        update_user(user, **args)
        print_user(user)


class FindUser(Command):
    option_list = [
        Option('--user_id'),
        Option('--username'),
        Option('--parse_id'),
        Option('--api_token'),
        Option('--phone'),
        Option('--email'),
        Option('--device_ids')
    ]

    # pylint: disable=method-hidden
    def run(self, **kwargs):
        kwargs['id'] = kwargs.pop('user_id')
        login(self.config.get('user_id'))
        users = find_users(**dict([(k, v) for k, v in kwargs.items() if v]))
        for user in users:
            print_user(user)


class GetSignupsByLocation(Command):
    option_list = [
    ]

    # pylint: disable=method-hidden
    def run(self):
        signups = SignupLocation.objects()
        for signup in signups:
            print signup.user.username, signup.city, signup.country_name, signup.zip_code


class ReregisterUserDevices(Command):
    """Highly experimental function. Do not use as is."""

    option_list = [
        Option('--username'),
    ]

    # pylint: disable=method-hidden
    def run(self, username):
        # Prepare the fake request.
        current_app.preprocess_request()
        # Fetch a user so we can establish an identity.
        user = get_user(username='MTSGRD', ignore_permission=True)
        # Create an identity.
        identity = Identity(str(user.id))
        # Set this identity on the thread.
        principals.set_identity(identity)
        # Tell listeners that the identity has changed.
        identity_changed.send(current_app, identity=identity)

        # Register devices.
        user = get_user(username)
        devices = Device.objects(owner=user)
        for i, device in enumerate(devices):
            if not re.match(USERNAME_REGEX, device.owner.username):
                continue
            print i, device.owner.id, device.owner.username, device.device_type, device.token
            if not device.token.startswith('ey'):
                parse.subscribe(device.owner, device.device_type, device.token)


class ReregisterDevices(Command):
    """Highly experimental function. Do not use as is."""

    option_list = [
        Option('--cutoff'),
    ]

    # pylint: disable=method-hidden
    def run(self, cutoff):

        # Prepare the fake request.
        current_app.preprocess_request()
        # Fetch a user so we can establish an identity.
        user = get_user(username='MTSGRD', ignore_permission=True)
        # Create an identity.
        identity = Identity(str(user.id))
        # Set this identity on the thread.
        principals.set_identity(identity)
        # Tell listeners that the identity has changed.
        identity_changed.send(current_app, identity=identity)

        # Register devices.
        users = User.objects(created__gte=cutoff)
        user_ids = [str(user.id) for user in users]
        devices = Device.objects(owner__in=user_ids)
        for i, device in enumerate(devices):
            if device.device_type != 'winphone':
                continue
            if not re.match(USERNAME_REGEX, device.owner.username):
                continue
            print i, device.owner.id, device.owner.username, device.device_type, device.token
            parse.subscribe(device.owner, device.device_type, device.token)


class RegisterDevicesToAmazon(Command):
    """Register IOS devices in amazon for independence day"""
    option_list = []

    def run(self):
        devices = Device.objects(device_type='ios')
        print 'Total devices', len(devices)
        for i, item in enumerate(devices):
            print '\r%s' % i,
            try:
                subscribe.delay(item.owner, item.device_type, item.token)
            except:
                print 'Error registering %s %s %s' % (i, item.device_type, item.token)


class RegisterDevice(Command):
    option_list = [
        Option('--push_token'),
        Option('--device_type')
    ]

    # pylint: disable=method-hidden
    def run(self, push_token, device_type):
        params = {'push_token': push_token,
                  'device_type': device_type}

        res = self.jsonpost('/rpc/register_device', data=params,
                            jwt_token=self.jwt_token)
        print_response(res)


class UnregisterDevice(Command):
    option_list = [
        Option('--push_token'),
        Option('--device_type')
    ]

    # pylint: disable=method-hidden
    def run(self, push_token, device_type):
        params = {'push_token': push_token,
                  'device_type': device_type}

        res = self.jsonpost('/rpc/unregister_device', data=params,
                            jwt_token=self.jwt_token)
        print_response(res)


class Login(Command):
    option_list = [
        Option('--username'),
        Option('--password'),
        Option('--jwt_expiration_delta', default=1e9)
    ]

    # pylint: disable=method-hidden
    def run(self, username, password, jwt_expiration_delta):
        # Set a custom JWT expiration delta.
        current_app.config['JWT_EXPIRATION_DELTA'] = jwt_expiration_delta

        params = {'username': username,
                  'password': password}

        res = self.jsonpost('/rpc/login', data=params)
        print_response(res)

        data = json.loads(res.data)
        jwt_token = data.pop('tok')
        if jwt_token:
            decoded_token = jwt.decode_callback(jwt_token)
            print_decoded_token(decoded_token)

            user = jwt.user_callback(decoded_token)
            save_config(jwt_token=jwt_token, **data)


class SendYo(Command):
    option_list = [
        Option('--to'),
        Option('--link'),
        Option('--location')
    ]

    # pylint: disable=method-hidden
    def run(self, to, link, location):
        res = self.jsonpost(
            '/rpc/yo',
            jwt_token=self.jwt_token,
            data={
                'to': to,
                'link': link,
                'location': location})
        print_response(res)


class ImportUsers(Command):
    option_list = [
        Option('--user_data'),
    ]

    # pylint: disable=method-hidden
    def run(self, user_data=None):
        importer = UserImporter(filename=user_data)
        importer.run()


class ImportUdids(Command):
    option_list = [
        Option('--user_data'),
    ]

    # pylint: disable=method-hidden
    def run(self, user_data=None):
        importer = UdidImporter(filename=user_data)
        importer.run()


class ImportHierarchy(Command):
    option_list = [
        Option('--user_data'),
    ]

    # pylint: disable=method-hidden
    def run(self, user_data=None):
        importer = HierarchyImporter(filename=user_data)
        importer.run()


class ImportBlocked(Command):
    option_list = [
        Option('--blocked_data'),
    ]

    # pylint: disable=method-hidden
    def run(self, blocked_data=None):
        importer = BlockedImporter(filename=blocked_data)
        importer.run()


class ImportBitly(Command):
    option_list = [
        Option('--bitly_data'),
    ]

    # pylint: disable=method-hidden
    def run(self, bitly_data=None):
        importer = BitlyImporter(filename=bitly_data)
        importer.run()


class ImportWelcomeLink(Command):
    option_list = [
        Option('--welcome_data'),
    ]

    # pylint: disable=method-hidden
    def run(self, welcome_data=None):
        importer = WelcomeImporter(filename=welcome_data)
        importer.run()


class ImportContacts(Command):
    option_list = [
        Option('--contact_data'),
    ]

    # pylint: disable=method-hidden
    def run(self, contact_data=None):
        importer = ContactImporter(filename=contact_data)
        importer.run()


class ImportYos(Command):
    option_list = [
        Option('--yo_data'),
    ]

    # pylint: disable=method-hidden
    def run(self, yo_data=None):
        importer = YoImporter(filename=yo_data)
        importer.run()


class ImportInstallations(Command):
    option_list = [
        Option('--installation_data')
    ]

    def run(self, installation_data=None):
        importer = InstallationImporter(filename=installation_data)
        importer.run()


class ResetDB(Command):
    option_list = [
        Option('--model_names'),
    ]
    # pylint: disable=method-hidden

    def run(self, model_names=None):
        assert current_app.config['MONGODB_HOST'] == 'localhost'
        for model_name in model_names.split(','):
            model = getattr(models, model_name)
            model.drop_collection()
            model.ensure_indexes()


class TestLocation(Command):
    # pylint: disable=method-hidden
    def run(self):
        record_signup_location()


class GenerateAPITokens(Command):
    """For a short amount of time, some api accounts were being
    created without api_tokens.
    """

    def run(self):
        users = User.objects(parent__exists=True,
                             api_token__exists=False)
        for user in users:
            print user.username
            try:
                user.api_token = str(uuid4())
                user.save()
                clear_get_user_cache(user)
            except Exception as e:
                # A couple of users don't have valid usernames
                pass


class ClearSNSEndpoints(Command):
    """For a short period of time, newly signed up users were recieving
       improper topic arns"""

    def run(self):
        users = User.objects(topic_arn__exists=True)
        for i, user in enumerate(users):
            print '\r%s' % i,
            user.topic_arn = None
            user.save()
            clear_get_user_cache(user)

        notification_endpoints = NotificationEndpoint.objects()
        for i, endpoint in enumerate(notification_endpoints):
            print '%s endpoint %s' % (i, endpoint.arn)
            sns.delete_endpoint(endpoint_arn=endpoint.arn)
            endpoint.delete()

        topics = sns.get_all_topics() \
            .get('ListTopicsResponse') \
            .get('ListTopicsResult') \
            .get('Topics')
        for i, topic in enumerate(topics):
            topic = topic.get('TopicArn')
            if not topic.startswith('sys_'):
                print '%s topic %s' % (i, topic),
                sns.delete_topic(topic)


class ClearSNSSubscriptions(Command):
    """We were at one point using subscriptions to yos but since thats
    no longer the case lets delete all of them"""

    def run(self):
        first = True
        next_token = None
        offset = 0
        queuing_pool = gevent.pool.Pool(100)

        def unsubscribe(i, arn, delete_func):
            print '\r%s subscription %s' % (i, arn),
            sys.stdout.flush()
            delete_func(arn)

        sns_unsubscribe = sns.unsubscribe

        while first or next_token:
            first = False
            result = sns.get_all_subscriptions(next_token=next_token) \
                .get('ListSubscriptionsResponse') \
                .get('ListSubscriptionsResult')
            next_token = result.get('NextToken')
            subscriptions = result.get('Subscriptions')

            for i, subscription in enumerate(subscriptions):
                topic = subscription.get('TopicArn')
                arn = subscription.get('SubscriptionArn')
                if not topic.startswith('sys_') and len(topic) == 59:
                    queuing_pool.spawn(unsubscribe, (i + offset), arn,
                                       sns_unsubscribe)

            offset += len(subscriptions)


class ClearSNSTopics(Command):
    """We were at one point using topics to yos but since thats
    no longer the case lets delete all of them"""

    def run(self):
        first = True
        next_token = None
        offset = 0
        queuing_pool = gevent.pool.Pool(30)

        def delete_topic(i, arn, delete_func):
            print '\r%s topic %s' % (i, arn),
            sys.stdout.flush()
            delete_func(arn)

        sns_delete_topic = sns.delete_topic

        while first or next_token:
            first = False
            result = sns.get_all_topics(next_token=next_token) \
                .get('ListTopicsResponse') \
                .get('ListTopicsResult')
            next_token = result.get('NextToken')
            topics = result.get('Topics')

            for i, topic in enumerate(topics):
                topic = topic.get('TopicArn')
                if not topic.startswith('sys_') and len(topic) == 59:
                    queuing_pool.spawn(delete_topic, (i + offset), topic,
                                       sns_delete_topic)

            offset += len(topics)


class RemoveNestedListsFromYos(Command):
    """Remove the nested recipients ListField in favor of generating a child
       Yo for each broadcast recipient. This also allows us to more easily
       track yo ack in the future"""

    option_list = [
        Option('--yo_data'),
    ]

    # pylint: disable=method-hidden
    def run(self, yo_data=None):
        importer = YoCollectionCleaner(filename=yo_data)
        importer.run()


class RemoveDuplicateDeviceIdsFromUsers(Command):
    option_list = [
        Option('--user_data'),
    ]

    def run(self, user_data=None):
        cleaner = DeviceIdCleaner(filename=user_data)
        cleaner.run()


class RemoveInvalidPhoneNumbersFromUsers(Command):
    option_list = [
        Option('--user_data'),
    ]

    def run(self, user_data=None):
        cleaner = PhoneNumberCleaner(filename=user_data)
        cleaner.run()


class ExportEmails(Command):

    def run(self):
        users = User.objects.filter(email=re.compile('^.{1,256}$'))
        added = []
        with open("emails.txt", "a") as myfile:
            for user in users:
                print user.email
                if 'nextdroidlabs.com' in user.email:
                    continue
                elif 'justyo.co' in user.email:
                    continue
                elif 'yoceleb.com' in user.email:
                    continue
                elif 'test' == user.email.lower():
                    continue
                if user.email in added:
                    continue
                try:
                    myfile.write(user.email + '\n')
                    added.append(user.email)
                except:
                    print 'error'



test = False


class TestReengagementPushOnCohorts(Command):
    """Finds users with a last_seen_time of a week ago or more and sends
    them a Yo to rengage them"""

    option_list = [
        Option('--time_delta_days', type=int),
        Option('--link'),
        Option('--header'),
        Option('--was_reengaged', type=bool)
    ]

    def run(self, time_delta_days, link, header=None, was_reengaged=None):
        if not time_delta_days:
            time_delta_days = 7

        start = time.time()

        days_prior = datetime.timedelta(days=time_delta_days)
        days_prior_usec = get_usec_timestamp(days_prior)

        yo_team = get_user(username='YOTEAM', ignore_permission=True)
        login(yo_team.user_id)

        cohort_size = 1000

        today = datetime.datetime.now().date()
        start_of_today = datetime.datetime(today.year, today.month, today.day)
        end_of_day = datetime.datetime(today.year, today.month, today.day, 23, 59)
        reengagement_push = ReengagementPush.objects.get(date__gte=start_of_today, date__lte=end_of_day)

        headers = reengagement_push.headers

        sent_to_users = []

        slack.chat_post_message('#reengagement', 'Sending reengagement test pushes')

        for header in headers:

            if header.link:
                link = header.link
            else:
                urlhelper = UrlHelper(reengagement_push.link)
                link = urlhelper.get_short_url()
                header.link = link
                header.save()

            slack.chat_post_message('#reengagement', 'Sending reengagement push: ' + header.push)
            slack.chat_post_message('#reengagement', 'link: ' + link + '+')

            recipient_count = 0

            while recipient_count < cohort_size:

                if test:
                    cohort = User.objects.filter(username='OR')
                else:
                    cohort = User.objects.filter(
                                                 country_name='United States', last_reengamement_push_time__exists=False) \
                        .order_by('-created') \
                        .limit(cohort_size)

                for user in cohort:

                    if recipient_count >= cohort_size:
                        continue

                    #  verify real person
                    if user.is_pseudo or user.is_service:
                        continue

                    # verify it not night
                    if user.timezone:
                        user_time = datetime.datetime.now(pytz.timezone(user.timezone))
                        if user_time.hour > 19:
                            print 'too late'
                            continue  # too late to send this

                    if user in sent_to_users:
                        print 'should not happen!'
                        continue

                    if user.country_name:
                        if user.country_name != 'United States':
                            print 'wrong country: ' + user.country_name
                            continue
                    else:
                        continue

                    yo = construct_yo(sender=yo_team,
                                      header=header,
                                      recipients=[user],
                                      link=link,
                                      link_content_type='image/gif',
                                      ignore_permission=True)

                    _send_yo.delay(yo_id=yo.yo_id)
                    print 'sent to ' + user.username

                    user.update(set__last_reengamement_push_time=get_usec_timestamp())
                    recipient_count += 1
                    sent_to_users.append(user)

            end = time.time()
            reengagement_push.elapsed = end - start


class SendBestReengagePushToAllUsers(Command):

    def run(self):

        today = datetime.datetime.now().date()
        start_of_today = datetime.datetime(today.year, today.month, today.day)
        end_of_day = datetime.datetime(today.year, today.month, today.day, 23, 59)
        reengagement_push = ReengagementPush.objects.get(date__gte=start_of_today, date__lte=end_of_day)

        max = 0
        best_header = None
        for header in reengagement_push.headers:
            count_opens = Yo.objects.filter(header=header, status='read').count()
            if count_opens > max:
                max = count_opens
                best_header = header

        start = time.time()

        days_prior = datetime.timedelta(days=7)
        days_prior_usec = get_usec_timestamp(days_prior)
        now = get_usec_timestamp()

        yo_team = get_user(username='YOTEAM', ignore_permission=True)
        login(yo_team.user_id)

        #count = User.objects.filter(Q(is_pseudo=False) &
        #                            Q(last_seen_time__lte=days_prior_usec) &
        #                            Q(last_reengamement_push_time__gte=days_prior_usec) |
        #                            Q(last_reengamement_push_time__exists=False)).count()

        count = User.objects.filter(country_name='United States', last_reengamement_push_time__exists=False).count()
        batch_size = 1000
        batch_count = (count / batch_size) + 1

        recipient_count = 0
        sent_to_users = []

        for batch_index in range(0, 1 if test else batch_count):

            if test:
                batch = User.objects.filter(username='OR')
            else:
                batch = User.objects.filter(country_name='United States', last_reengamement_push_time__exists=False) \
                .order_by('-created') \
                    .limit(batch_size) \
                    .skip(batch_index*batch_size)
                #User.objects.filter(Q(is_pseudo=False) &
                #                            Q(last_seen_time__lte=days_prior_usec) &
                #                            Q(last_reengamement_push_time__gte=days_prior_usec) |
                #                            Q(last_reengamement_push_time__exists=False)) \

            for user in batch:

                #  verify real person
                if user.is_pseudo or user.is_service:
                    continue

                if user.country_name:
                    if user.country_name != 'United States':
                        continue
                else:
                    continue

                # verify it not night
                if user.timezone:
                    user_time = datetime.datetime.now(pytz.timezone(user.timezone))
                    if user_time.hour > 19:
                        continue  # too late to send this

                if user in sent_to_users:
                    print 'should not happen!'
                    continue

                yo = construct_yo(sender=yo_team,
                                  header=best_header,
                                  recipients=[user],
                                  link=best_header.link,
                                  link_content_type='image/gif',
                                  ignore_permission=True)

                _send_yo.delay(yo_id=yo.yo_id)
                print 'sent to ' + user.username

                user.update(set__last_reengamement_push_time=now)
                recipient_count += 1
                sent_to_users.append(user)

        end = time.time()
        reengagement_push.elapsed = end - start


def print_user(user):
    # Copy over related accounts.
    user_dict = user.to_dict()
    if user.parent:
        user_dict['parent'] = user.parent.username
    if user.children:
        for i, child in enumerate(user.children[:]):
            user_dict['children'][i] = child.username
    print_object_section('USER', user_dict)

    # Copy over people you've added.
    contacts = get_contact_usernames(user)
    contact_usernames = [contact.username for contact in contacts]
    print_object_section('CONTACTS', contact_usernames)

    # Copy over people who have added you, but are not in your contacts.
    # followers = get_followers(user)
    # follower_usernames = [follower.username for follower in followers]
    # print_object_section('FOLLOWERS', follower_usernames)


class DebugOr(Command):
    # pylint: disable=method-hidden
    def run(self):

        current_app.preprocess_request()

        identity = Identity('5489d6cff4a5052f696eac35')
        # Set this identity on the thread.
        principals.set_identity(identity)
        # Tell listeners that the identity has changed.
        identity_changed.send(current_app, identity=identity)
        print 'sfgsd 1'
        count = 0
        user = get_user('USATODAY')
        followers = get_followers(user, ignore_permission=True)
        print 'sfgsd 2'
        for follower in followers:
            endpoints = get_user_endpoints(follower)
            print follower.username + ' has ' + len(endpoints)
            if len(endpoints) == 0:
                count += 1

        print count



