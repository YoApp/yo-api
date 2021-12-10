# -*- coding: utf-8 -*-
from gevent import monkey
monkey.patch_all()

import mock
import unittest

from flask import json
from flask_principal import identity_changed
from pygeocoder import GeocoderError
from giphypop import Giphy
from imgurpython import ImgurClient
from requests import Session

from parse_rest.query import QueryManager as ParseUserQuery
from parse_rest.user import User as ParseUser
from twilio.rest import Messages
from werkzeug.datastructures import Headers
from yoapi.accounts import facebook
from yoapi.core import cache, redis, principals, limiter, sns, s3
from yoapi.factory import create_api_app, create_worker_app
from yoapi.helpers import random_string
from yoapi.jwt import generate_token
from yoapi.models import (User, Contact, Yo, Header,
                          NotificationEndpoint, ABExperiment, ABTest,
                          ResponseCategory)
from yoapi.parse import Parse
from yoapi.security import YoIdentity
from yoapi.services import low_rq, medium_rq, high_rq
from yoapi.urltools import UrlHelper

from yoapi.extensions.flask_sendgrid import SendGridClient


class BaseTestCase(unittest.TestCase):

    """Base for common functions across all tests.

    TODO: We need a dedicated test account.
    """

    app = None
    worker_app = None

    _ephemeral_account = {'username': 'TESTUSERTEMP',
                          'password': 'totoro'}

    _ephemeral_api = {'username': 'TESTUSERPYTHONAPI',
                      'parent': 'TESTUSERPYTHON',
                      'name': 'API testing account',
                      'needs_location': True,
                      'dont_send_api_email': True}
    _ephemeral_invalid_api = {'username': '18493848473',
                              'parent': 'TESTUSERPYTHON',
                              'name': 'API testing account',
                              'needs_location': True,
                              'dont_send_api_email': True}
    _user1_push_token = ('APA91bGLTIEP6ROvCQm_z5ll9FuWS3PKx4rJMkG8xZuqFk8il3'
                         'lSlg1lK9ertowyhyia-71Fh1KpE311hdijVPZFlXwryDXDdx_X'
                         'QIBlwRcrL5Nvlo39yzkb7SXU5x3IPqnulcx5dryq5-oGoc6fc9'
                         'pBRhVHvkMdRQ')

    _user2_push_token = ('c5165dad5f8ab1b90dbda9be37263829b1477c011a5e6e942a'
                         'a3f9ea683bf5e9')

    _photo = """
    /9j/4QAYRXhpZgAASUkqAAgAAAAAAAAAAAAAAP/sABFEdWNreQABAAQAAAAKAAD/4QMtaHR0cDov
    L25zLmFkb2JlLmNvbS94YXAvMS4wLwA8P3hwYWNrZXQgYmVnaW49Iu+7vyIgaWQ9Ilc1TTBNcENl
    aGlIenJlU3pOVGN6a2M5ZCI/PiA8eDp4bXBtZXRhIHhtbG5zOng9ImFkb2JlOm5zOm1ldGEvIiB4
    OnhtcHRrPSJBZG9iZSBYTVAgQ29yZSA1LjMtYzAxMSA2Ni4xNDU2NjEsIDIwMTIvMDIvMDYtMTQ6
    NTY6MjcgICAgICAgICI+IDxyZGY6UkRGIHhtbG5zOnJkZj0iaHR0cDovL3d3dy53My5vcmcvMTk5
    OS8wMi8yMi1yZGYtc3ludGF4LW5zIyI+IDxyZGY6RGVzY3JpcHRpb24gcmRmOmFib3V0PSIiIHht
    bG5zOnhtcD0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wLyIgeG1sbnM6eG1wTU09Imh0dHA6
    Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9tbS8iIHhtbG5zOnN0UmVmPSJodHRwOi8vbnMuYWRvYmUu
    Y29tL3hhcC8xLjAvc1R5cGUvUmVzb3VyY2VSZWYjIiB4bXA6Q3JlYXRvclRvb2w9IkFkb2JlIFBo
    b3Rvc2hvcCBDUzYgKE1hY2ludG9zaCkiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6OEJEMUI3
    MkM1NkY5MTFFNDkzQTg5NThDODZGMzc0MjkiIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6OEJE
    MUI3MkQ1NkY5MTFFNDkzQTg5NThDODZGMzc0MjkiPiA8eG1wTU06RGVyaXZlZEZyb20gc3RSZWY6
    aW5zdGFuY2VJRD0ieG1wLmlpZDo4QkQxQjcyQTU2RjkxMUU0OTNBODk1OEM4NkYzNzQyOSIgc3RS
    ZWY6ZG9jdW1lbnRJRD0ieG1wLmRpZDo4QkQxQjcyQjU2RjkxMUU0OTNBODk1OEM4NkYzNzQyOSIv
    PiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVu
    ZD0iciI/Pv/uAA5BZG9iZQBkwAAAAAH/2wCEABQQEBkSGScXFycyJh8mMi4mJiYmLj41NTU1NT5E
    QUFBQUFBREREREREREREREREREREREREREREREREREREREQBFRkZIBwgJhgYJjYmICY2RDYrKzZE
    RERCNUJERERERERERERERERERERERERERERERERERERERERERERERERERP/AABEIABQAFAMBIgAC
    EQEDEQH/xABhAAEAAwAAAAAAAAAAAAAAAAAAAgUGAQEAAAAAAAAAAAAAAAAAAAAAEAAABQIFAwUB
    AAAAAAAAAAAAARECEgMEITEiEwVRgRXwQZGhMxQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhED
    EQA/ANG3mLY21XG427P6E4kMuwhV521pMY9xu1lJrYnJOqCt5jjirX9BxMM2VDStEjTA8FE7lr7D
    kTuzpufScyBbbVieHt2+wFj5uz2P6J6FjlivRMwGY8fcz8hsuhuz2k1RVcvXwADcAAAAAAD/2Q==
    """
    _test_parse_token = 'CXM8Vd3SqRk1aoew3XDi9nwQp'  # Never expires?

    android_111064067_ua = 'Yo/111064067 (Android; Nexus 5; 21; 5.0.1)'
    android_111064076_ua = 'Yo/111064076 (Android; Nexus 5; 21; 5.0.1)'
    androidbeta_111064077_ua = 'YoBeta/111064077 (Android; Nexus 5; 21; 5.0.1)'

    ios_141_ua = 'Yo/1.4.1 (iPhone; iOS 8.1.2; Scale/2.00)'
    ios_146_ua = 'Yo/1.4.6 (iPhone; iOS 8.1.2; Scale/2.00)'
    ios_154_ua = 'Yo/1.5.4 (iPhone; iOS 8.1.2; Scale/2.00)'
    ios_155_ua = 'Yo/1.5.5 (iPhone; iOS 8.1.2; Scale/2.00)'
    ios_big_155_ua = 'Yo/1.5.5 (iPhone; iOS 8.1.2; Scale/3.00)'
    iosbeta_156_ua = 'YoBeta/1.5.6 (iPhone; iOS 8.1.2; Scale/2.00)'

    installation_id = 'automatic-testing'

    _sns_delivery_failure_json = {
        'MessageId': 'adb968a8-2a7a-5d30-8bfc-25e8843f2596',
        'Timestamp': '2015-01-26T21:05:09.766Z',
        'TopicArn': 'arn:aws:sns:us-east-1:131325091098:sys_delivery_failure',
        'UnsubscribeURL': 'https://sns.us-east-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=arn:aws:sns:us-east-1:131325091098:sys_delivery_failure:07f18142-7a8a-41d4-a72f-5a13c5d52f6f',
        'Subject': 'DeliveryFailure event for app iOS (APNS)',
        'Signature': 'JF2JK9GlPEnB9Yu8yeZ47ZnHEcVRP4+Oycxs7sx5zyuNK5lL/Ul0glt8i24LiUD9CUGBcQUQn9AsyjVTCpnK93+x69rObhn5MxcjEewp+vXCbmysBNKWmHF4yfyR/F2qeHy+sZ65JDuf0rVIZSKQf0ajleGVMuVfb3/DHQ6l822t7lXsCdKvAZGvgwgt8buv8BthdVpIY4Navvpi3j1feMiMy2ZtRM5LHNz1q2KMm+VYCSWGE/0MJ+ySMokDQtSKQBmrbYQ2csJ67BkWQGCaZqDW9O+yWrDiiIj8LqlcJZbvboJcZnwfWDjnw2eLBqe/N0RuxA3gPHWv3zL4wDRGmA==',
        'SigningCertURL': 'https://sns.us-east-1.amazonaws.com/SimpleNotificationService-d6d679a1d18e95c2f9ffcf11f4f9e198.pem',
        'SignatureVersion': '1',
        'Type': 'Notification',
        'Message': '{\"DeliveryAttempts\":1,\"EndpointArn\":\"arn:aws:sns:us-east-1:131325091098:endpoint/APNS/iOS/cc9a9af5-59a6-3593-9305-834ccb9ca9f7\",\"EventType\":\"DeliveryFailure\",\"FailureMessage\":\"Endpoint is disabled\",\"FailureType\":\"EndpointDisabled\",\"MessageId\":\"7094feb9-e6ca-5faa-bc20-b3f9488faf48\",\"Resource\":\"arn:aws:sns:us-east-1:131325091098:app/APNS/iOS\",\"Service\":\"SNS\",\"Time\":\"2015-01-26T21:05:09.730Z\"}'
    }


    @classmethod
    def setup_class(cls):

        # Prepare the app and push the app context.
        cls.app = cls._create_app()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()
        cls.client = cls.app.test_client(use_cookies=False)

        # Create a worker app as well for background tasks.
        cls.worker_app = cls._create_worker_app()
        cls.worker = low_rq.create_worker(app=cls.worker_app, pool_size=20)

        # Make sure we are not working against the production database.
        assert 'localhost' in cls.app.config['MONGODB_HOST']
        assert 'localhost' in cls.app.config['CACHE_REDIS_URL']
        assert 'localhost' in cls.app.config['REDIS_URL']

        # Install patchers for libraries that make external requests.
        cls.live_counter_patcher = mock.patch('yoapi.yos.send.ping_live_counter')
        cls.geocoder_patcher = mock.patch('yoapi.yos.send.geocoder.reverse_geocode')
        cls.parse_push_patcher = mock.patch.object(Parse, 'push')
        cls.parse_signup_patcher = mock.patch.object(ParseUser, 'signup')
        cls.parse_subscribe_patcher = mock.patch.object(Parse, 'subscribe')
        cls.parse_unsubscribe_patcher = mock.patch.object(Parse, 'unsubscribe')
        cls.parse_delete_patcher = mock.patch.object(ParseUser, 'DELETE')
        cls.parse_query_get_patcher = mock.patch.object(ParseUserQuery, 'get')
        cls.send_grid_send_patcher = mock.patch.object(SendGridClient, 'send')
        cls.facebook_get_profile_patcher = mock.patch.object(facebook, 'get_profile')
        cls.facebook_get_picture_patcher = mock.patch.object(facebook, 'get_profile_picture')
        cls.s3_upload_image_patcher = mock.patch.object(s3, 'upload_image')
        cls.sns_subscribe_patcher = mock.patch.object(sns, 'subscribe')
        cls.sns_unsubscribe_patcher = mock.patch.object(sns, 'unsubscribe')
        cls.sns_publish_patcher = mock.patch.object(sns, 'publish')
        cls.sns_create_endpoint_patcher = mock.patch.object(sns, 'create_endpoint')
        cls.sns_delete_endpoint_patcher = mock.patch.object(sns, 'delete_endpoint')
        cls.sns_create_topic_patcher = mock.patch.object(sns, 'create_topic')
        cls.sns_set_endpoint_patcher = mock.patch.object(sns, 'set_endpoint')
        cls.twilio_send_patcher = mock.patch.object(Messages, 'create')
        cls.get_request_patcher = mock.patch.object(Session, 'request')
        cls.get_link_content_type_patcher = mock.patch('yoapi.yos.send.get_link_content_type')
        cls.short_url_patcher = mock.patch.object(UrlHelper, 'get_short_url')
        cls.giphy_search_patcher = mock.patch.object(Giphy, 'search')
        cls.imgur_search_patcher = mock.patch.object(ImgurClient, 'gallery_search')
        cls.experiment_logger_patcher = mock.patch.object(ABExperiment, 'log')

    def setUp(self):
        """Runs before each job"""

        # Drop data stored in previous test runs.
        Contact.drop_collection()
        NotificationEndpoint.drop_collection()
        User.drop_collection()
        Yo.drop_collection()
        Header.drop_collection()
        ABTest.drop_collection()
        ResponseCategory.drop_collection()

        # Clear the flask-cache redis cache.
        cache.clear()

        # Clear redis cache.
        redis.flushdb()

        # Clear RQ databases.
        low_rq.connection.flushdb()
        medium_rq.connection.flushdb()
        high_rq.connection.flushdb()

        # Clear limiter redis cache.
        limiter.storage.storage.flushdb()

        # Ensure indexes
        Contact.ensure_indexes()
        NotificationEndpoint.ensure_indexes()
        User.ensure_indexes()
        Yo.ensure_indexes()
        Header.ensure_indexes()
        ABTest.ensure_indexes()
        ResponseCategory.ensure_indexes()

        self._phone1 = '+14153351320'
        # Create user 1
        token = random_string(length=5)
        _user1 = User(
            username='TESTUSERPYTHON',
            facebook_id='testuser1',
            email='a@b.com',
            phone=self._phone1,
            first_name='First Test',
            last_name='User',
            api_token=token)
        _user1.set_password('calcifer')
        _user1.save()
        self._user1_jwt = generate_token(_user1)
        self._user1 = _user1

        # Create user 2
        token = random_string(length=5)
        _user2 = User(username='TESTUSERPYTHON2',
                facebook_id='testuser2',
                first_name='Second Test',
                last_name='User',
                topic_arn='test:arn',
                api_token=token)
        _user2.set_password('calcifer')
        _user2.save()
        self._user2_jwt = generate_token(_user2)
        self._user2 = _user2

        # Create user 3
        _user3 = User(username='TESTUSERPYTHON3')
        _user3.set_password('calcifer')
        _user3.save()
        self._user3_jwt = generate_token(_user3)
        self._user3 = _user3

        # Create user 4
        _user4 = User(username='TESTUSERPYTHON4',
                first_name='Very Long First Name With Lots and Lots of Words',
                last_name='Also very long but probably doesn\'t matter')
        _user4.set_password('calcifer')
        _user4.save()
        self._user4_jwt = generate_token(_user4)
        self._user4 = _user4

        # Create user 5 for YOALL rate limit testing **ONLY
        _yoalluser = User(username='TESTYOALLUSER')
        _yoalluser.set_password('calcifer')
        _yoalluser.save()
        self._yoalluser_jwt = generate_token(_yoalluser)
        self._yoalluser = _yoalluser

        # Create headers for first yos.
        Header(sms=u'👉 Swipe/Tap to open\n📎 Yo From %(sender_display_name)s',
               push=u'👉 Swipe/Tap to open\n📎 Yo From %(sender_display_name)s',
               ending='\n\nTap to Yo back: %(webclient_url)s',
               yo_type='link_yo', is_default=False, group_yo=False,
               id='54dd685ca17351c1d859689e').save()

        Header(sms=u'👉 Swipe/Tap to open\n📍 Yo From %(sender_display_name)s',
               push=u'👉 Swipe/Tap to open\n📍 Yo From %(sender_display_name)s',
               ending='\n\nTap to Yo back: %(webclient_url)s',
               yo_type='location_yo', is_default=False, group_yo=False,
               id='54dd6880a17351c1d85968b3').save()

        Header(sms=(u'👉 You won\'t believe what Yo can do.\n📎 Open this'
                     u'Yo From %(sender_display_name)s'),
               push=(u'👉 You won\'t believe what Yo can do.\n📎 Open this'
                     u'Yo From %(sender_display_name)s'),
               ending='\n\nTap to Yo back: %(webclient_url)s',
               yo_type='link_yo', is_default=False, group_yo=False,
               id='54dd6939a17351c1d859692e').save()

        Header(sms=(u'📍This is a Location Yo\n👐 Open it. \n☝️Double tap your '
                     u'friends to send one From %(sender_display_name)s'),
               push=(u'📍This is a Location Yo\n👐 Open it. \n☝️Double tap your '
                     u'friends to send one From %(sender_display_name)s'),
               ending='\n\nTap to Yo back: %(webclient_url)s',
               yo_type='link_yo', is_default=False, group_yo=False,
               id='54de9ecba17351c1d85a55aa').save()

        # Create headers for SMS copy.
        Header(sms='Yo from %(sender_display_name)s.',
               push='%(emoji)s Yo %(from)s %(sender_display_name)s',
               ending='\n\nTap to Yo back: %(webclient_url)s',
               id='54dd67efa17351c1d8596887',
               yo_type='default_yo', group_yo=False, is_default=True).save()

        Header(sms=('Yo Photo from %(sender_display_name)s '
                    'via %(forwarded_from)s.'),
               push=('%(emoji)s Yo Photo %(from)s %(forwarded_from)s '
                    'via %(sender_display_name)s'),
               ending='\n\nTap to view: %(webclient_url)s',
               yo_type='forwarded_photo_yo', group_yo=False,
               is_default=True).save()

        Header(sms=('Yo Link from %(sender_display_name)s '
                    'via %(forwarded_from)s.'),
               push=('%(emoji)s Yo Link %(from)s %(forwarded_from)s '
                     'via %(sender_display_name)s'),
               ending='\n\nTap to view: %(webclient_url)s',
               yo_type='forwarded_yo', group_yo=False, is_default=True).save()

        Header(sms='Yo Link from %(sender_display_name)s.',
               push='%(emoji)s Yo Link %(from)s %(sender_display_name)s',
               ending='\n\nTap to view: %(webclient_url)s',
               yo_type='link_yo', group_yo=False, is_default=True).save()

        Header(sms='Yo Location from %(sender_display_name)s @ %(city)s.',
               push='%(emoji)s Yo Location %(from)s %(sender_display_name)s @ %(city)s',
               ending='\n\nTap to see where they are: %(webclient_url)s',
               yo_type='location_city_yo', group_yo=False,
               is_default=True).save()

        Header(sms='Yo Location from %(sender_display_name)s.',
               push='%(emoji)s Yo Location %(from)s %(sender_display_name)s',
               ending='\n\nTap to see where they are: %(webclient_url)s',
               yo_type='location_yo', group_yo=False, is_default=True).save()

        Header(sms='Yo Photo from %(sender_display_name)s.',
               push='%(emoji)s Yo Photo %(from)s %(sender_display_name)s',
               ending='\n\nTap to view: %(webclient_url)s',
               yo_type='photo_yo', group_yo=False, is_default=True).save()

        Header(sms=('Yo from %(sender_display_name)s to '
                    '\'%(group_name)s\' %(social_text)s.'),
               push=('%(emoji)s Yo %(from)s %(sender_display_name)s to '
                     '%(group_name)s %(social_text)s'),
               ending='\n\nTap to Yo back: %(webclient_url)s',
               yo_type='default_yo', group_yo=True, is_default=True).save()

        Header(sms=('Yo Photo from %(sender_display_name)s '
                    'via %(forwarded_from)s to \'%(group_name)s\' '
                    '%(social_text)s.'),
               push=('%(emoji)s Yo Photo %(from)s %(forwarded_from)s '
                     'via %(sender_display_name)s to %(group_name)s'),
               ending='\n\nTap to view: %(webclient_url)s',
               yo_type='forwarded_photo_yo', group_yo=True,
               is_default=True).save()

        Header(sms=('Yo Link from %(sender_display_name)s '
                    'via %(forwarded_from)s to \'%(group_name)s\' '
                    '%(social_text)s.'),
               push=('%(emoji)s Yo Link %(from)s %(forwarded_from)s '
                     'via %(sender_display_name)s to %(group_name)s'),
               ending='\n\nTap to view: %(webclient_url)s',
               yo_type='forwarded_yo', group_yo=True,
               is_default=True).save()

        Header(sms=('Yo Link from %(sender_display_name)s to '
                    '\'%(group_name)s\' %(social_text)s.'),
               push=('%(emoji)s Yo Link %(from)s %(sender_display_name)s to '
                     '%(group_name)s'),
               ending='\n\nTap to view: %(webclient_url)s',
               yo_type='link_yo', group_yo=True, is_default=True).save()

        Header(sms=('Yo Location from %(sender_display_name)s @ '
                    '%(city)s to \'%(group_name)s\' %(social_text)s.'),
               push=('%(emoji)s Yo Location %(from)s %(sender_display_name)s @ '
                     '%(city)s to %(group_name)s'),
               ending='\n\nTap to see where they are: %(webclient_url)s',
               yo_type='location_city_yo', group_yo=True,
               is_default=True).save()

        Header(sms=('Yo Location from %(sender_display_name)s to '
                    '\'%(group_name)s\' %(social_text)s.'),
               push=('%(emoji)s Yo Location %(from)s %(sender_display_name)s to '
                     '%(group_name)s'),
               ending='\n\nTap to see where they are: %(webclient_url)s',
               yo_type='location_yo', group_yo=True,
               is_default=True).save()

        Header(sms=('Yo Photo from %(sender_display_name)s to '
                    '\'%(group_name)s\' %(social_text)s.'),
               push=('%(emoji)s Yo Photo %(from)s %(sender_display_name)s to '
                     '%(group_name)s'),
               ending='\n\nTap to view: %(webclient_url)s',
               yo_type='photo_yo', group_yo=True, is_default=True).save()

        # Start mocking functions, objects and libraries.
        self.geocoder_mock = self.geocoder_patcher.start()
        self.parse_push_mock = self.parse_push_patcher.start()
        self.parse_signup_mock = self.parse_signup_patcher.start()
        self.parse_delete_mock = self.parse_delete_patcher.start()
        self.parse_query_get_mock = self.parse_query_get_patcher.start()
        self.parse_subscribe_mock = self.parse_subscribe_patcher.start()
        self.parse_unsubscribe_mock = self.parse_unsubscribe_patcher.start()
        self.send_grid_send_mock = self.send_grid_send_patcher.start()
        self.s3_upload_image_mock = self.s3_upload_image_patcher.start()
        self.facebook_get_profile_mock = self.facebook_get_profile_patcher.start()
        self.facebook_get_picture_mock = self.facebook_get_picture_patcher.start()

        # When patching a function on an instance of an object then only said
        # instance will have the mocked function. One of the functions mocked
        # on SNS is defined in the extension instance object. So we switch
        # to the worker app context before starting the patcher.
        with self.worker_app.app_context():
            self.sns_subscribe_mock = self.sns_subscribe_patcher.start()
            self.sns_unsubscribe_mock = self.sns_unsubscribe_patcher.start()
            self.sns_publish_mock = self.sns_publish_patcher.start()
            self.sns_create_endpoint_mock = self.sns_create_endpoint_patcher.start()
            self.sns_create_topic_mock = self.sns_create_topic_patcher.start()
            self.sns_delete_endpoint_mock = self.sns_delete_endpoint_patcher.start()
            self.sns_set_endpoint_mock = self.sns_set_endpoint_patcher.start()

        self.twilio_send_mock = self.twilio_send_patcher.start()
        self.get_request_mock = self.get_request_patcher.start()
        self.get_link_content_type_mock = self.get_link_content_type_patcher.start()
        self.short_url_mock = self.short_url_patcher.start()
        self.giphy_search_mock = self.giphy_search_patcher.start()
        self.imgur_search_mock = self.imgur_search_patcher.start()

        # Start the patcher to get the mock but stop it until it
        # needs to be used.
        self.experiment_logger_mock = self.experiment_logger_patcher.start()
        self.experiment_logger_patcher.stop()

        # Setup return values for mock objects.
        self.get_request_mock.return_value.json.return_value = None
        self.geocoder_mock.side_effect = GeocoderError('Error')
        self.get_link_content_type_mock.return_value = 'application/unknown'
        self.short_url_mock.return_value = None
        self.s3_upload_image_mock.return_value = 'image.jpg'
        self.sns_create_endpoint_mock.return_value = 'aws:is:great'
        self.sns_create_topic_mock.return_value = 'aws:is:great'
        self.sns_subscribe_mock.return_value = 'aws:is:great'
        self.facebook_get_profile_mock.return_value = {}
        # by setting is_silhouette the picture will be skipped.
        self.facebook_get_picture_mock.return_value = {'is_silhouette': True}
        self.giphy_search_mock.return_value = []
        self.imgur_search_mock.return_value = []

        self.addCleanup(self.tearDown)


    def tearDown(self):
        """Runs after each job"""
        # Stop mocking functions, objects and libraries.
        patchers = [self.experiment_logger_patcher,
                    self.geocoder_patcher,
                    self.giphy_search_patcher,
                    self.facebook_get_profile_patcher,
                    self.facebook_get_picture_patcher,
                    self.imgur_search_patcher,
                    self.live_counter_patcher,
                    self.parse_push_patcher,
                    self.parse_signup_patcher,
                    self.parse_subscribe_patcher,
                    self.parse_unsubscribe_patcher,
                    self.parse_query_get_patcher,
                    self.parse_delete_patcher,
                    self.send_grid_send_patcher,
                    self.s3_upload_image_patcher,
                    self.sns_subscribe_patcher,
                    self.sns_unsubscribe_patcher,
                    self.sns_publish_patcher,
                    self.sns_create_endpoint_patcher,
                    self.sns_create_topic_patcher,
                    self.sns_set_endpoint_patcher,
                    self.sns_delete_endpoint_patcher,
                    self.twilio_send_patcher,
                    self.get_request_patcher,
                    self.get_link_content_type_patcher,
                    self.short_url_patcher]
        for patcher in patchers:
            try:
                patcher.stop()
            except:
                # Patcher already stopped.
                pass

        # Check for failed items.
        self.assertEquals(low_rq.failed_queue.count, 0)
        self.assertEquals(high_rq.failed_queue.count, 0)
        self.assertEquals(medium_rq.failed_queue.count, 0)

    @classmethod
    def _create_app(cls):
        """Creates a Flask application instance

        We need to create the app in this base class even though the super class
        determines what app we are creating. Not following this patterns would mean
        we need duplication of the code to push the context.

        For testing non-endpoint related functionality we create an app straight
        from the factory.
        """
        return create_api_app('automated_tests', config='tests.config.Testing')

    @classmethod
    def _create_worker_app(cls):
        """Creates a Flask application instance

        We need to create the app in this base class even though the super class
        determines what app we are creating. Not following this patterns would mean
        we need duplication of the code to push the context.

        For testing non-endpoint related functionality we create an app straight
        from the factory.
        """
        return create_worker_app('automated_tests_worker',
                                 config='tests.config.Testing')

    def become(self, user):
        """Impersates a user"""
        identity = YoIdentity(str(user.id))
        principals.set_identity(identity)
        # Tell listeners that the identity has changed.
        identity_changed.send(self.app, identity=identity)

    def shortDescription(self):
        """Turns off doctstrings in verbose output"""
        return None

    def jsonpost(self, *args, **kwargs):
        """Convenience method for making JSON POST requests."""
        kwargs.setdefault('content_type', 'application/json')
        if 'data' in kwargs:
            kwargs['data'] = json.dumps(kwargs['data'])

        headers = Headers()
        override_headers = kwargs.pop('headers', {})
        if override_headers:
            for k, v in override_headers.items():
                headers.add(k, v)

        if 'useragent' in kwargs:
            useragent = kwargs.pop('useragent')
            headers.add('User-Agent', useragent)

        if 'jwt_token' in kwargs:
            token = kwargs.pop('jwt_token')
            if kwargs.pop('auth', False):
                raise Exception('Can\'t use multiple identities')
            headers.add('Authorization', 'Bearer ' + token)
        elif kwargs.pop('auth', True):
            token = self._user1_jwt
            headers.add('Authorization', 'Bearer ' + token)

        if not 'X-Yo-Installation-Id' in headers:
            headers.add('X-Yo-Installation-Id', self.installation_id)

        # Set a quick JSON lookup attribute.
        response = self.client.post(headers=headers, *args, **kwargs)
        try:
            response.json = json.loads(response.data)
        except:
            response.json = None

        return response

    def jsonput(self, *args, **kwargs):
        """Convenience method for making JSON PUT requests."""
        kwargs.setdefault('content_type', 'application/json')
        if 'data' in kwargs:
            kwargs['data'] = json.dumps(kwargs['data'])

        headers = Headers()
        override_headers = kwargs.pop('headers', {})
        if override_headers:
            for k, v in override_headers.items():
                headers.add(k, v)

        if 'useragent' in kwargs:
            useragent = kwargs.pop('useragent')
            headers.add('User-Agent', useragent)

        if 'jwt_token' in kwargs:
            token = kwargs.pop('jwt_token')
            if kwargs.pop('auth', False):
                raise Exception('Can\'t use multiple identities')
            headers.add('Authorization', 'Bearer ' + token)
        elif kwargs.pop('auth', True):
            token = self._user1_jwt
            headers.add('Authorization', 'Bearer ' + token)

        if not 'X-Yo-Installation-Id' in headers:
            headers.add('X-Yo-Installation-Id', self.installation_id)

        # Set a quick JSON lookup attribute.
        response = self.client.put(headers=headers, *args, **kwargs)
        try:
            response.json = json.loads(response.data)
        except:
            response.json = None

        return response
