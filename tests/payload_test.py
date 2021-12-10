# -*- coding: utf-8 -*-
"""Tests for various conditions that change the payload sent to a endpoint"""

from . import BaseTestCase

from yoapi.accounts import update_user
from yoapi.urltools import UrlHelper
from yoapi.helpers import random_string
from yoapi.groups import get_group_contacts
from yoapi.models import (NotificationEndpoint, Contact, User,
                          ResponseCategory)
from yoapi.notification_endpoints import (get_useragent_profile, IOSBETA, IOS,
                                          ANDROID)
from yoapi.services import low_rq, medium_rq

from yoapi.models.payload import Payload, YoPayload, YoGroupPayload
from yoapi.constants import payload as YoPayloadConst
from yoapi.constants.regex import (DOUBLE_PERIOD_RE, NOT_GSM_RE,
                                   NOT_ASCII_GSM_RE)
from yoapi.constants.payload import CALL_TEXT_CATEGORY
from yoapi.yos.helpers import construct_yo, _create_child_yos
from yoapi.yos.queries import get_child_yos, get_yo_by_id


class PayloadTestCase(BaseTestCase):

    def setUp(self):
        # create a fake requests for useragent parsing
        super(PayloadTestCase, self).setUp()

        # TODO: Refactor the get_useragent_profile function to accept a
        # useragent instead of a request
        class FakeRequest(object): pass
        # The only thing that makes an endpoint beta is the platform when
        # passed to register_device
        ios_request = FakeRequest()
        ios_request.user_agent = self.iosbeta_156_ua
        ua_profile = get_useragent_profile(ios_request)
        self.ios_beta_endpoint = NotificationEndpoint(
            owner=self._user1,
            installation_id=self.installation_id,
            token=self._user1_push_token,
            platform=IOSBETA,
            version=ua_profile.get('app_version'),
            os_version=ua_profile.get('os_version'),
            sdk_version=ua_profile.get('sdk_version'))
        self.ios_beta_payload_support_dict = self.ios_beta_endpoint \
            .get_payload_support_dict()

        ios_request = FakeRequest()
        ios_request.user_agent = self.ios_155_ua
        ua_profile = get_useragent_profile(ios_request)
        self.ios_endpoint = NotificationEndpoint(
            owner=self._user1,
            installation_id=self.installation_id,
            token=self._user1_push_token,
            platform=ua_profile.get('platform'),
            version=ua_profile.get('app_version'),
            os_version=ua_profile.get('os_version'),
            sdk_version=ua_profile.get('sdk_version'))
        self.ios_payload_support_dict = self.ios_endpoint \
            .get_payload_support_dict()

        android_request = FakeRequest()
        android_request.user_agent = self.android_111064076_ua
        ua_profile = get_useragent_profile(android_request)
        self.android_endpoint = NotificationEndpoint(
            owner=self._user1,
            installation_id=self.installation_id,
            token=self._user1_push_token,
            platform=ua_profile.get('platform'),
            version=ua_profile.get('app_version'),
            os_version=ua_profile.get('os_version'),
            sdk_version=ua_profile.get('sdk_version'))
        self.android_payload_support_dict = self.android_endpoint \
            .get_payload_support_dict()

        self.perfect_support_dict = \
                NotificationEndpoint.perfect_payload_support_dict()

        self.legacy_payload_support_dict = {
            'handles_any_text': False,
            'handles_long_text': False,
            'handles_response_category': False,
            'is_legacy': True
        }

        self.pseudo_payload_support_dict = {
            'handles_any_text': True,
            'handles_invisible_push': False,
            'handles_display_names': True,
            'handles_long_text': True,
            'handles_response_category': True,
            'is_legacy': False,
            'platform': 'sms',
            'handles_unicode': False,
        }

        # make a pseudo user

        token = random_string(length=5)
        pseudo_user1 = User(username='12322222222', phone='+12322222222',
                           is_pseudo=True, verified=True, api_token=token)
        self.pseudo_user1 = pseudo_user1.save()

        token = random_string(length=5)
        pseudo_user2 = User(username='12322222224', phone='+12322222224',
                           is_pseudo=True, verified=True, api_token=token)
        self.pseudo_user2 = pseudo_user2.save()

        # make the pseudo user friends with user1
        Contact(owner=self._user1, target=self.pseudo_user1,
                contact_name="Pseudo Friend").save()
        Contact(owner=self.pseudo_user1, target=self._user1).save()

        # Create group
        _group1 = User(username='GROUP1', name='Group 1', parent=self._user1,
                       is_group=True).save()
        Contact(target=self._user1, owner=_group1, is_group_admin=True).save()
        Contact(target=self._user2, owner=_group1).save()
        Contact(target=self._user3, owner=_group1).save()
        Contact(target=self._user4, owner=_group1).save()
        Contact(target=self.pseudo_user1, owner=_group1).save()

        Contact(owner=self._user1, target=_group1, is_group_admin=True).save()
        Contact(owner=self._user2, target=_group1).save()
        Contact(owner=self._user3, target=_group1).save()
        Contact(owner=self._user4, target=_group1).save()
        Contact(owner=self.pseudo_user1, target=_group1).save()
        self._group1 = _group1

        # Create group
        _group2 = User(username='GROUP2', name='Group 2', parent=self._user1,
                       is_group=True).save()
        Contact(target=self._user1, owner=_group2, is_group_admin=True).save()
        Contact(target=self.pseudo_user1, owner=_group2,
                contact_name='Pseudo U.').save()
        Contact(target=self.pseudo_user2, owner=_group2,
                contact_name='Pseudo2 U.').save()

        Contact(owner=self._user1, target=_group2).save()
        Contact(owner=self.pseudo_user1, target=_group2).save()
        Contact(owner=self.pseudo_user2, target=_group2).save()

        self._group2 = _group2

        # Creae some ResponseCategories.
        ResponseCategory(yo_type='default_yo', left_text='test_l',
                         right_text='test_r').save()


    def assertValidSMS(self, text):
        self.assertTrue(len(text) <= 160)
        self.assertFalse(NOT_GSM_RE.search(text))

    def assertNiceSMS(self, text):
        self.assertValidSMS(text)
        self.assertFalse(DOUBLE_PERIOD_RE.search(text))
        self.assertFalse(NOT_ASCII_GSM_RE.search(text))


    def test_01_yo_payload_default_yo(self):
        self.assertFalse(self.android_endpoint.is_legacy)
        self.assertTrue(self.android_endpoint.handles_any_text)
        self.assertFalse(self.ios_endpoint.is_legacy)
        self.assertTrue(self.ios_endpoint.handles_any_text)

        # Set recipient's count_in
        self.become(self._user2)
        update_user(self._user2, count_in=0)

        # Test base yo with legacy endpoint
        self.become(self._user1)
        yo = construct_yo(sender=self._user1, recipients=[self._user2])
        yo_payload = YoPayload(yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.DEFAULT_YO)
        self.assertEquals(yo_payload.get_push_text(), 'From %s' % self._user1.username)
        self.assertEquals(yo_payload.category, 'Response_Category')

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('link', payload_extras)

        # Test base yo with non-legacy android endpoint
        # android requires the capital F because of how Ari wrote it.
        # NOTE: The swipe/tap text is never sent to android
        yo_payload = YoPayload(yo, self.android_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.DEFAULT_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          'Yo From %s' % self._user1.username)
        self.assertEquals(yo_payload.category, 'Response_Category')

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('link', payload_extras)

        # Test base yo to a pseduo user.
        yo_payload = YoPayload(yo, self.pseudo_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.DEFAULT_YO)

        response = 'Yo from %s.\n\nTap to Yo back: https://app.justyo.co/%s' % (
                self._user1.display_name, yo.recipient.api_token)
        response = DOUBLE_PERIOD_RE.sub('.', response)
        self.assertEquals(yo_payload.get_yo_sms_text(yo),
                          response)

        self.assertNiceSMS(response)

        # Test base yo with non-legacy ios endpoint
        yo_payload = YoPayload(yo, self.ios_beta_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.DEFAULT_YO)
        self.assertEquals(yo_payload.category, YoPayloadConst.DEFAULT_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          'Yo from %s' % self._user1.username)
        self.assertEquals(yo_payload.get_yo_inbox_text(yo.get_flattened_yo()),
                          yo.sender.display_name)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('link', payload_extras)

        # Test base yo with super support dict
        yo_payload = YoPayload(yo, self.perfect_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.DEFAULT_YO)
        self.assertEquals(yo_payload.category, 'test_l.test_r')
        self.assertEquals(yo_payload.get_push_text(),
                          'Yo from %s' % self._user1.display_name)
        self.assertEquals(yo_payload.get_yo_inbox_text(yo.get_flattened_yo()),
                          yo.sender.display_name)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('link', payload_extras)

    def test_02_yo_payload_link_yo(self):
        # Test yo link with legacy endpoint
        self.become(self._user1)
        yo = construct_yo(sender=self._user1, recipients=[self._user2],
                          link='http://test.justyo.co')
        yo_payload = YoPayload(yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LINK_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '* From %s' % self._user1.username)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('link'), yo.link)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)

        # Test yo link with non-legacy android endpoint
        yo_payload = YoPayload(yo, self.android_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LINK_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '%s Yo Link From %s' % (YoPayloadConst.LINK_SYMBOL,
                                                  self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('link'), yo.link)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)

        # Test yo link to a pseduo user.
        yo_payload = YoPayload(yo, self.pseudo_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LINK_YO)

        response = 'Yo Link from %s.\n\nTap to view: https://app.justyo.co/%s' % (
                self._user1.display_name, yo.recipient.api_token)
        response = DOUBLE_PERIOD_RE.sub('.', response)
        self.assertEquals(yo_payload.get_yo_sms_text(yo),
                          response)
        self.assertNiceSMS(response)

        # Test yo link with non-legacy ios endpoint
        yo_payload = YoPayload(yo, self.ios_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LINK_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '%s Yo Link from %s' % (YoPayloadConst.LINK_SYMBOL,
                                                  self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('link'), yo.link)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)

    def test_03_yo_payload_location_yo(self):
        # Test yo location with legacy endpoint
        self.become(self._user1)
        yo = construct_yo(sender=self._user1, recipients=[self._user2],
                          location='0,0')
        yo_payload = YoPayload(yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LOCATION_YO)
        self.assertEquals(yo_payload.get_push_text(),
                         '@ From %s' % self._user1.username)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('location'), '0.0;0.0')
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('link', payload_extras)

        # Test yo location with non-legacy android endpoint
        yo_payload = YoPayload(yo, self.android_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LOCATION_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '%s Yo Location From %s' % (YoPayloadConst.ROUND_PIN,
                                                      self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('location'), '0.0;0.0')
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('link', payload_extras)

         # Test yo location to a pseduo user.
        yo_payload = YoPayload(yo, self.pseudo_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LOCATION_YO)

        response = 'Yo Location from %s.\n\nTap to see where they are: https://app.justyo.co/%s' % (
                self._user1.display_name, yo.recipient.api_token)
        response = DOUBLE_PERIOD_RE.sub('.', response)
        self.assertEquals(yo_payload.get_yo_sms_text(yo),
                          response)
        self.assertNiceSMS(response)

       # Test yo location with non-legacy ios endpoint
        yo_payload = YoPayload(yo, self.ios_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LOCATION_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '%s Yo Location from %s' % (YoPayloadConst.ROUND_PIN,
                                                      self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('location'), '0.0;0.0')
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('link', payload_extras)

    def test_04_yo_payload_legacy_group_yo(self):
        # Test group_yo with legacy
        self.become(self._user1)
        group_members = [self._user1, self._user2]
        yo = construct_yo(sender=self._user1, recipients=group_members,
                          is_group_yo=True)
        yo.recipient_count = _create_child_yos(yo, group_members)
        child_yos = get_child_yos(yo)
        self.assertEquals(len(child_yos), 2)
        usernames = '+'.join([y.recipient.username for y in child_yos])

        child_yo = child_yos[0]
        yo_payload = YoPayload(child_yo, self.legacy_payload_support_dict)
        self.assertTrue(isinstance(yo_payload, YoGroupPayload))

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LEGACY_GROUP_YO)
        self.assertEquals(yo_payload.get_push_text(),
                         '%s From %s' % (usernames, yo.sender.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), usernames)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          self._user1.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('location', payload_extras)

        # Test group yo with non-legacy android endpoint
        yo_payload = YoPayload(child_yo, self.android_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LEGACY_GROUP_YO)
        push_text = yo_payload.get_push_text()
        self.assertIn(self._user1.username, push_text)
        self.assertIn(self._user2.username, push_text)
        self.assertIn('+', push_text)
        self.assertTrue(push_text.endswith('From %s' % self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        self.assertIn(self._user1.username, payload_extras.get('sender'))
        self.assertIn(self._user2.username, payload_extras.get('sender'))
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          self._user1.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('location', payload_extras)

        # Test group yo location with non-legacy ios endpoint
        yo_payload = YoPayload(child_yo, self.ios_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LEGACY_GROUP_YO)
        push_text = yo_payload.get_push_text()
        self.assertIn(self._user1.username, push_text)
        self.assertIn(self._user2.username, push_text)
        self.assertIn('+', push_text)
        self.assertTrue(push_text.endswith('from %s' % self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        self.assertIn(self._user1.username, payload_extras.get('sender'))
        self.assertIn(self._user2.username, payload_extras.get('sender'))
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          self._user1.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('location', payload_extras)

    def test_05_yo_payload_broadcast_yo(self):
        # Test that brodcast yo's send the right link

        # Create short link and follower
        test_link = UrlHelper('http://test.justyo.co/payload')
        test_short_link = UrlHelper('http://t.yo.co/p')
        contact1 = Contact(owner=self._user2, target=self._user1)
        contact1.save()
        self.short_url_mock.return_value = test_short_link.get_url()

        res = self.jsonpost('/rpc/yoall', data={'link': test_link.get_url()})
        self.assertEqual(res.status_code, 200)
        self.assertIn('yo_id', res.json)

        # Send yoall
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yo_id = res.json.get('yo_id')
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.link, test_link.get_url())
        self.assertEquals(yo.short_link, test_short_link.get_url())

        child_yos = get_child_yos(yo)
        child_yo = child_yos[0]
        flattened_yo = child_yo.get_flattened_yo()
        self.assertEquals(flattened_yo.link, test_link.get_url())
        self.assertEquals(flattened_yo.short_link, test_short_link.get_url())

        payload = YoPayload(child_yo, self.legacy_payload_support_dict)
        self.assertIn('link', payload.get_apns_payload())
        self.assertEquals(payload.get_apns_payload().get('link'),
                          test_short_link.get_url())

        self.short_url_mock.return_value = None

    def test_06_payload_supported_endpoints(self):
        # Test that setting the supported_endpoints list will
        # disable specific endpoitns

        payload = Payload('This is a test', None, sender='')
        self.assertTrue(payload.supports_platform(self.ios_endpoint.platform))
        self.assertTrue(payload.supports_platform(self.ios_beta_endpoint.platform))
        self.assertTrue(payload.supports_platform(self.android_endpoint.platform))

        payload.supported_platforms = [ANDROID]

        self.assertFalse(payload.supports_platform(self.ios_endpoint.platform))
        self.assertFalse(payload.supports_platform(self.ios_beta_endpoint.platform))
        self.assertTrue(payload.supports_platform(self.android_endpoint.platform))

        payload.supported_platforms = [ANDROID, IOS]

        self.assertFalse(payload.supports_platform(self.ios_beta_endpoint.platform))
        self.assertTrue(payload.supports_platform(self.android_endpoint.platform))
        self.assertTrue(payload.supports_platform(self.ios_endpoint.platform))

    def test_07_yo_payload_photo_yo(self):
        # Test yo photo link with legacy endpoint
        self.become(self._user1)
        yo = construct_yo(sender=self._user1, recipients=[self._user2],
                          link='http://test.justyo.co',
                          link_content_type='image/jpg')
        yo_payload = YoPayload(yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.PHOTO_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '* From %s' % self._user1.username)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('link'), yo.link)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)

         # Test yo photo link to a pseduo user.
        yo_payload = YoPayload(yo, self.pseudo_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.PHOTO_YO)

        response = 'Yo Photo from %s.\n\nTap to view: https://app.justyo.co/%s' % (
                self._user1.display_name, yo.recipient.api_token)
        response = DOUBLE_PERIOD_RE.sub('.', response)
        self.assertEquals(yo_payload.get_yo_sms_text(yo),
                          response)
        self.assertNiceSMS(response)

        # Test yo link with non-legacy android endpoint
        yo_payload = YoPayload(yo, self.android_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.PHOTO_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '%s Yo Photo From %s' % (YoPayloadConst.CAMERA,
                                                   self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('link'), yo.link)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)

        # Test yo link with non-legacy ios endpoint
        yo_payload = YoPayload(yo, self.ios_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.PHOTO_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '%s Yo Photo from %s' % (YoPayloadConst.CAMERA,
                                                   self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('link'), yo.link)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)

    def test_08_forwarded_yo(self):
        # Test yo photo link with legacy endpoint
        self.become(self._user2)
        test_link = UrlHelper('http://test.justyo.co/payload')
        origin_yo = construct_yo(sender=self._user2, recipients=[self._user2],
                          link=test_link.get_url())
        self.become(self._user1)
        yo = construct_yo(sender=self._user1, recipients=[self._user2],
                          link='http://test.justyo.co', origin_yo=origin_yo)

        self.assertEquals(yo.link, test_link.get_url())

        yo_payload = YoPayload(yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LINK_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '* From %s' % self._user1.username)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), origin_yo.yo_id)
        self.assertEquals(payload_extras.get('link'), yo.link)
        self.assertEquals(payload_extras.get('origin_sender'),
                          origin_yo.sender.username)
        self.assertNotIn('location', payload_extras)

        # Test yo link with non-legacy android endpoint
        yo_payload = YoPayload(yo, self.android_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.FORWARDED_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '%s Yo Link From %s via %s' % (YoPayloadConst.LINK_SYMBOL,
                                                         self._user2.username,
                                                         self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), origin_yo.yo_id)
        self.assertEquals(payload_extras.get('link'), yo.link)
        self.assertEquals(payload_extras.get('origin_sender'),
                          origin_yo.sender.username)

        # Test yo link with non-legacy ios endpoint
        yo_payload = YoPayload(yo, self.ios_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.FORWARDED_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          '%s Yo Link from %s via %s' % (YoPayloadConst.LINK_SYMBOL,
                                                         self._user2.username,
                                                         self._user1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), origin_yo.yo_id)
        self.assertEquals(payload_extras.get('link'), yo.link)
        self.assertEquals(payload_extras.get('origin_sender'),
                          origin_yo.sender.username)


    def test_09_group_yo(self):
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._group1.username})
        self.assertEquals(res.status_code, 200)

        # Test that location has been stored.
        yo_id = res.json.get('yo_id')
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.recipient, self._group1)
        self.assertTrue(yo.is_group_yo)

        # Send group group yo.
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yos = get_child_yos(yo)
        self.assertGreater(len(yos), 0)

        child_yo = yos[0]

        # Test default group yo to a non-legacy ios device.
        yo_payload = YoPayload(child_yo, self.ios_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.DEFAULT_YO)
        base_yo_text = 'from %s' % child_yo.parent.sender.username
        self.assertEquals(yo_payload.get_base_yo_text(), base_yo_text)
        self.assertEquals(yo_payload.get_push_text(),
                          'Yo %s to %s' % (base_yo_text, self._group1.username))
        self.assertEquals(yo_payload.get_yo_inbox_text(yo.get_flattened_yo()),
                          '%s to %s' % (yo.sender.display_name, self._group1.name))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group.
        self.assertEquals(payload_extras.get('sender'),
                          self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertIn('group_object', payload_extras)
        self.assertEquals(payload_extras.get('group_object').get('user_id'),
                          yo.recipient.user_id)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)

        # Test group yo with non-legacy android endpoint
        yo_payload = YoPayload(child_yo, self.android_payload_support_dict)
        base_yo_text = 'From %s' % child_yo.parent.sender.username

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.DEFAULT_YO)
        self.assertEquals(yo_payload.get_push_text(),
                          'Yo %s to %s' % (base_yo_text, self._group1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group's username.
        self.assertEquals(payload_extras.get('sender'), self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)

        # Test default group yo to a legacy device.
        yo_payload = YoPayload(child_yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type,
                          YoPayloadConst.DEFAULT_YO)
        base_yo_text = 'From %s' % self._group1.username
        self.assertEquals(yo_payload.get_base_yo_text(), base_yo_text)
        self.assertEquals(yo_payload.get_push_text(), base_yo_text)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group's username.
        self.assertEquals(payload_extras.get('sender'), self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertIn('group_object', payload_extras)
        self.assertEquals(payload_extras.get('group_object').get('user_id'),
                          yo.recipient.user_id)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('location', payload_extras)


    def test_10_location_group_yo(self):
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._group1.username,
                                  'location': '0,0'})
        self.assertEquals(res.status_code, 200)

        # Test that location has been stored.
        yo_id = res.json.get('yo_id')
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.recipient, self._group1)
        self.assertTrue(yo.is_group_yo)

        # Send group group yo.
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yos = get_child_yos(yo)
        self.assertGreater(len(yos), 0)

        child_yo = yos[0]

        # Test location group yo to a non-legacy ios device.
        yo_payload = YoPayload(child_yo, self.ios_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LOCATION_YO)
        base_yo_text = 'from %s' % child_yo.parent.sender.username
        self.assertEquals(yo_payload.get_base_yo_text(), base_yo_text)
        self.assertEquals(yo_payload.get_push_text(),
            '%s Yo Location %s to %s' % (YoPayloadConst.ROUND_PIN, base_yo_text,
                                         self._group1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group.
        self.assertEquals(payload_extras.get('sender'),
                          self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('location'), '0.0;0.0')
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertIn('group_object', payload_extras)
        self.assertEquals(payload_extras.get('group_object').get('user_id'),
                          yo.recipient.user_id)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)

        # Test location group yo with non-legacy android endpoint
        yo_payload = YoPayload(child_yo, self.android_payload_support_dict)

        base_yo_text = 'From %s' % child_yo.parent.sender.username
        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LOCATION_YO)
        self.assertEquals(yo_payload.get_push_text(),
            '%s Yo Location %s to %s' % (YoPayloadConst.ROUND_PIN, base_yo_text,
                                         self._group1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group's username.
        self.assertEquals(payload_extras.get('sender'), self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('location'), '0.0;0.0')
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)

        # Test location group yo to a legacy device.
        yo_payload = YoPayload(child_yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type,
                          YoPayloadConst.LOCATION_YO)
        base_yo_text = 'From %s' % self._group1.username
        self.assertEquals(yo_payload.get_base_yo_text(), base_yo_text)
        self.assertEquals(yo_payload.get_push_text(), '@ %s' % base_yo_text)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group's username.
        self.assertEquals(payload_extras.get('sender'), self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('location'), '0.0;0.0')
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertIn('group_object', payload_extras)
        self.assertEquals(payload_extras.get('group_object').get('user_id'),
                          yo.recipient.user_id)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)


    def test_11_link_group_yo(self):
        urlhelper = UrlHelper('http://test.justyo.co')
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._group1.username,
                                  'link': urlhelper.get_url()})
        self.assertEquals(res.status_code, 200)

        # Test that location has been stored.
        yo_id = res.json.get('yo_id')
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.recipient, self._group1)
        self.assertTrue(yo.is_group_yo)

        # Send group group yo.
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yos = get_child_yos(yo)
        self.assertGreater(len(yos), 0)

        child_yo = yos[0]

        # Test location group yo to a non-legacy ios device.
        yo_payload = YoPayload(child_yo, self.ios_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LINK_YO)
        base_yo_text = 'from %s' % child_yo.parent.sender.username
        self.assertEquals(yo_payload.get_base_yo_text(), base_yo_text)
        self.assertEquals(yo_payload.get_push_text(),
            '%s Yo Link %s to %s' % (YoPayloadConst.LINK_SYMBOL, base_yo_text,
                                     self._group1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group.
        self.assertEquals(payload_extras.get('sender'),
                          self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertIn('group_object', payload_extras)
        self.assertEquals(payload_extras.get('group_object').get('user_id'),
                          yo.recipient.user_id)
        self.assertEquals(payload_extras.get('link'), urlhelper.get_url())
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)

        # Test location group yo with non-legacy android endpoint
        yo_payload = YoPayload(child_yo, self.android_payload_support_dict)
        base_yo_text = 'From %s' % child_yo.parent.sender.username

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.LINK_YO)
        self.assertEquals(yo_payload.get_push_text(),
            '%s Yo Link %s to %s' % (YoPayloadConst.LINK_SYMBOL, base_yo_text,
                                     self._group1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group's username.
        self.assertEquals(payload_extras.get('sender'), self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('link'), urlhelper.get_url())
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)

        # Test location group yo to a legacy device.
        yo_payload = YoPayload(child_yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type,
                          YoPayloadConst.LINK_YO)
        base_yo_text = 'From %s' % self._group1.username
        self.assertEquals(yo_payload.get_base_yo_text(), base_yo_text)
        self.assertEquals(yo_payload.get_push_text(), '* %s' % base_yo_text)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group's username.
        self.assertEquals(payload_extras.get('sender'), self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertIn('group_object', payload_extras)
        self.assertEquals(payload_extras.get('group_object').get('user_id'),
                          yo.recipient.user_id)
        self.assertEquals(payload_extras.get('link'), urlhelper.get_url())
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)


    def test_12_photo_group_yo(self):
        urlhelper = UrlHelper('http://test.justyo.co')
        # change the link content type mock to simulate a photo yo.
        self.get_link_content_type_mock.return_value = 'image/jpeg'
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._group1.username,
                                  'link': urlhelper.get_url()})
        self.assertEquals(res.status_code, 200)

        # Test that location has been stored.
        yo_id = res.json.get('yo_id')
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.recipient, self._group1)
        self.assertTrue(yo.is_group_yo)

        # Send group group yo.
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Reset the link content type mock.
        self.get_link_content_type_mock.return_value = 'application/unknown'

        yos = get_child_yos(yo)
        self.assertGreater(len(yos), 0)

        child_yo = yos[0]

        # Test location group yo to a non-legacy ios device.
        yo_payload = YoPayload(child_yo, self.ios_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.PHOTO_YO)
        base_yo_text = 'from %s' % child_yo.parent.sender.username
        self.assertEquals(yo_payload.get_base_yo_text(), base_yo_text)
        self.assertEquals(yo_payload.get_push_text(),
            '%s Yo Photo %s to %s' % (YoPayloadConst.CAMERA, base_yo_text,
                                      self._group1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group.
        self.assertEquals(payload_extras.get('sender'),
                          self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertIn('group_object', payload_extras)
        self.assertEquals(payload_extras.get('group_object').get('user_id'),
                          yo.recipient.user_id)
        self.assertEquals(payload_extras.get('link'), urlhelper.get_url())
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)

        # Test location group yo with non-legacy android endpoint
        yo_payload = YoPayload(child_yo, self.android_payload_support_dict)

        base_yo_text = 'From %s' % child_yo.parent.sender.username
        self.assertEquals(yo_payload.payload_type, YoPayloadConst.PHOTO_YO)
        self.assertEquals(yo_payload.get_push_text(),
            '%s Yo Photo %s to %s' % (YoPayloadConst.CAMERA, base_yo_text,
                                     self._group1.username))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group's username.
        self.assertEquals(payload_extras.get('sender'), self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('link'), urlhelper.get_url())
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)

        # Test location group yo to a legacy device.
        yo_payload = YoPayload(child_yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.PHOTO_YO)
        base_yo_text = 'From %s' % self._group1.username
        self.assertEquals(yo_payload.get_base_yo_text(), base_yo_text)
        self.assertEquals(yo_payload.get_push_text(), '* %s' % base_yo_text)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), child_yo.yo_id)
        # test that the sender is set to the group's username.
        self.assertEquals(payload_extras.get('sender'), self._group1.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertIn('group_object', payload_extras)
        self.assertEquals(payload_extras.get('group_object').get('user_id'),
                          yo.recipient.user_id)
        self.assertEquals(payload_extras.get('link'), urlhelper.get_url())
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)

    def test_13_group_yo_sms(self):
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._group2.username})
        self.assertEquals(res.status_code, 200)

        # Test that location has been stored.
        yo_id = res.json.get('yo_id')
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.recipient, self._group2)
        self.assertTrue(yo.is_group_yo)

        # Send group group yo.
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yos = get_child_yos(yo)
        self.assertGreater(len(yos), 0)

        child_yo = [yo for yo in yos if yo.recipient == self.pseudo_user2]
        child_yo = child_yo[0]
        flattened_yo = child_yo.get_flattened_yo()

        # Test default group yo to a non-legacy ios device.
        group_contacts = get_group_contacts(self._group2)
        yo_payload = YoPayload(child_yo, self.pseudo_payload_support_dict)
        yo_payload.set_yo_social_text(flattened_yo, group_contacts)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.DEFAULT_YO)
        response = ('Yo from %s to \'%s\' with Pseudo U.\n\n'
                    'Tap to Yo back: https://app.justyo.co/%s')
        response = response % (self._user1.display_name,
                               self._group2.name,
                               self.pseudo_user2.api_token)
        response = DOUBLE_PERIOD_RE.sub('.', response)
        self.assertEquals(yo_payload.get_yo_sms_text(flattened_yo),
                          response)
        self.assertNiceSMS(response)

    def test_14_emoji_category_map(self):
        # Test context yo with an emoji.
        self.become(self._user1)
        update_user(self._user1, phone=self._phone1, verified=True)
        emoji = u'\U0001f4de'
        yo = construct_yo(sender=self._user1, recipients=[self._user2],
                          context=u'\U0001f4de')
        yo_payload = YoPayload(yo, self.legacy_payload_support_dict)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.DEFAULT_YO)
        self.assertEquals(yo_payload.get_push_text(),
                         'From %s' % self._user1.username)

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('location', payload_extras)
        self.assertNotIn('left_deep_link', payload_extras)
        self.assertNotIn('right_deep_link', payload_extras)

        # Test yo emoji context with ios 2.0.3 endpoint
        support = NotificationEndpoint.perfect_payload_support_dict()
        yo_payload = YoPayload(yo, support)

        self.assertEquals(yo_payload.payload_type, YoPayloadConst.CONTEXT_YO)
        self.assertEquals(yo_payload.category, CALL_TEXT_CATEGORY)
        self.assertEquals(yo_payload.get_push_text(),
                          u'%s from %s' % (emoji, self._user1.display_name,))

        payload_extras = yo_payload.get_extras()
        self.assertEquals(payload_extras.get('yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('sender'), yo.sender.username)
        self.assertEquals(payload_extras.get('origin_yo_id'), yo.yo_id)
        self.assertEquals(payload_extras.get('left_deep_link'),
                          'tel:%s' % self._phone1)
        self.assertEquals(payload_extras.get('right_deep_link'),
                          'sms:%s' % self._phone1)
        self.assertIn('sender_object', payload_extras)
        self.assertEquals(payload_extras.get('sender_object').get('user_id'),
                          yo.sender.user_id)
        self.assertNotIn('group_object', payload_extras)
        self.assertNotIn('origin_sender', payload_extras)
        self.assertNotIn('link', payload_extras)
        self.assertNotIn('location', payload_extras)
